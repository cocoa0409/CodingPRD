"""IrrigationPlan routes."""

from flask import Blueprint, g, request

from clock import CLOCK, parse_iso
from db import DB, LOCK, new_id
from errors import (
    forbidden,
    invalid_state,
    not_found,
    plan_window_overlap,
    precondition_not_met,
    validation_error,
)
from middleware import require_roles
from response import success_array, success_no_content, success_object
from services.audit import append_audit
from services.calculations import compute_crop_water_demand
from services.common import (
    bump_version,
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    round_half_up_2,
    stamp_create,
    to_aware_utc,
)
from services.plans import fail_pending_commands_for_plan, find_overlap_plan
from services.quota import find_quota_for_command, recompute_quota_aggregates
from services.serializers import irrigation_plan_view


bp = Blueprint("irrigation_plans", __name__)


VALID_SOURCES = {"AUTO", "MANUAL_OVERRIDE"}


def _validate_plot_param(plot_id):
    return fetch_or_404(DB.plots, plot_id)


def _resolve_plan(plot_id, plan_id):
    """Path-resolution: plot first, then plan; return plan record or 404."""
    plot = _validate_plot_param(plot_id)
    plan = DB.irrigation_plans.get(plan_id)
    if plan is None or plan.get("plot_id") != plot["id"]:
        raise not_found()
    return plot, plan


def _parse_window(body, *, allow_partial=False):
    ws_raw = body.get("window_start")
    we_raw = body.get("window_end")
    if not allow_partial and (ws_raw is None or we_raw is None):
        raise validation_error("window_start and window_end are required")
    ws = parse_iso(ws_raw) if ws_raw else None
    we = parse_iso(we_raw) if we_raw else None
    if ws is not None and we is not None and not (we > ws):
        raise validation_error("window_end must be after window_start")
    return ws, we


@bp.route("/plots/<plot_id>/irrigation-plans", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def create_plan(plot_id):
    body = get_json_body()
    with LOCK:
        plot = _validate_plot_param(plot_id)
        try:
            ws, we = _parse_window(body)
        except validation_error.__class__ as exc:  # not used; placeholder
            raise
        ws, we = _parse_window(body)

        source = body.get("source") or "AUTO"
        if source not in VALID_SOURCES:
            raise validation_error("source invalid")

        # PRD §3.2 places the overlap check inside the activation
        # preconditions ("the plan's [window_start, window_end) must not
        # overlap any other IrrigationPlan on the same plot whose status
        # is in the set of ACTIVE or SUSPENDED"). Plan CREATE never
        # touches a plan in ACTIVE/SUSPENDED (it stays DRAFT until
        # activation), so we deliberately skip the overlap check here.

        # Compute planned_volume_liters
        if source == "MANUAL_OVERRIDE":
            if "planned_volume_liters" not in body or body["planned_volume_liters"] is None:
                raise validation_error("planned_volume_liters required for MANUAL_OVERRIDE")
            pv = body["planned_volume_liters"]
            if isinstance(pv, bool) or not isinstance(pv, (int, float)):
                raise validation_error("planned_volume_liters must be a number")
            planned = round_half_up_2(pv)
        else:
            if "planned_volume_liters" in body and body["planned_volume_liters"] is not None:
                pv = body["planned_volume_liters"]
                if isinstance(pv, bool) or not isinstance(pv, (int, float)):
                    raise validation_error("planned_volume_liters must be a number")
                planned = round_half_up_2(pv)
            else:
                planned = compute_crop_water_demand(plot, CLOCK.now())

        rec = stamp_create({
            "id": new_id(),
            "plot_id": plot["id"],
            "window_start": ws,
            "window_end": we,
            "planned_volume_liters": planned,
            "source": source,
            "status": "DRAFT",
            "plan_version": 1,
            "parent_plan_id": None,
        })
        DB.irrigation_plans[rec["id"]] = rec
    return success_object(irrigation_plan_view(rec), status=201)


@bp.route("/plots/<plot_id>/irrigation-plans/<plan_id>/activate", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def activate_plan(plot_id, plan_id):
    with LOCK:
        plot, plan = _resolve_plan(plot_id, plan_id)
        if plan["status"] != "DRAFT":
            raise invalid_state("Plan must be DRAFT to activate")

        # Preconditions
        if plot.get("status") != "ACTIVE":
            raise precondition_not_met("Plot must be ACTIVE")
        # At least one ONLINE sensor
        has_online = any(
            s.get("plot_id") == plot["id"] and s.get("status") == "ONLINE"
            for s in DB.sensors.values()
        )
        if not has_online:
            raise precondition_not_met("Plot must have at least one ONLINE sensor")

        # Window overlap (priority 10)
        overlap = find_overlap_plan(plot["id"], plan["window_start"], plan["window_end"], exclude_plan_id=plan["id"])
        if overlap is not None:
            raise plan_window_overlap()

        # Quota precondition
        q = find_quota_for_command(plan)
        if q is None:
            raise precondition_not_met("No covering quota for plan window")
        recompute_quota_aggregates(q)
        if q["usage_state"] == "OVER" and q.get("approval_state") != "APPROVED":
            from errors import quota_exceeded
            raise quota_exceeded()

        plan["status"] = "ACTIVE"
        bump_version(plan)

        # Reservation: provisional_used_liters is recomputed from in-flight commands;
        # the planned_volume_liters reservation does not count there. We instead bump
        # the version so OCC reflects the change.
        recompute_quota_aggregates(q)
    return success_object(irrigation_plan_view(plan))


@bp.route("/plots/<plot_id>/irrigation-plans/<plan_id>/suspend", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def suspend_plan(plot_id, plan_id):
    with LOCK:
        plot, plan = _resolve_plan(plot_id, plan_id)
        if plan["status"] != "ACTIVE":
            raise invalid_state("Plan must be ACTIVE to suspend")
        plan["status"] = "SUSPENDED"
        bump_version(plan)
        fail_pending_commands_for_plan(plan, "PLAN_SUSPENDED")

        q = find_quota_for_command(plan)
        if q is not None:
            recompute_quota_aggregates(q)
    return success_object(irrigation_plan_view(plan))


@bp.route("/plots/<plot_id>/irrigation-plans/<plan_id>/resume", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def resume_plan(plot_id, plan_id):
    with LOCK:
        plot, plan = _resolve_plan(plot_id, plan_id)
        if plan["status"] != "SUSPENDED":
            raise invalid_state("Plan must be SUSPENDED to resume")

        q = find_quota_for_command(plan)
        if q is None:
            raise precondition_not_met("No covering quota for plan window")
        recompute_quota_aggregates(q)
        if q.get("usage_state") == "OVER" and q.get("approval_state") != "APPROVED":
            raise precondition_not_met("Quota is OVER without APPROVED override")

        plan["status"] = "ACTIVE"
        bump_version(plan)
        recompute_quota_aggregates(q)
    return success_object(irrigation_plan_view(plan))


@bp.route("/plots/<plot_id>/irrigation-plans/<plan_id>/override", methods=["POST"])
@require_roles("WaterAdmin")
def override_plan(plot_id, plan_id):
    body = get_json_body()
    with LOCK:
        plot, plan = _resolve_plan(plot_id, plan_id)
        if plan["status"] != "ACTIVE":
            raise invalid_state("Plan must be ACTIVE to override")

        # Override request body provides new planned_volume_liters or a window
        new_pv = body.get("planned_volume_liters")
        new_ws_raw = body.get("window_start")
        new_we_raw = body.get("window_end")
        if new_pv is None and new_ws_raw is None and new_we_raw is None:
            raise validation_error("override requires planned_volume_liters or window")

        original_pv = plan.get("planned_volume_liters")
        # Original plan ACTIVE -> DRAFT (cycle)
        plan["status"] = "DRAFT"
        bump_version(plan)

        # Compute new draft fields
        new_ws = plan["window_start"] if new_ws_raw is None else parse_iso(new_ws_raw)
        new_we = plan["window_end"] if new_we_raw is None else parse_iso(new_we_raw)
        if not (new_we > new_ws):
            raise validation_error("window_end must be after window_start")
        if new_pv is None:
            planned = original_pv
        else:
            if isinstance(new_pv, bool) or not isinstance(new_pv, (int, float)):
                raise validation_error("planned_volume_liters must be a number")
            planned = round_half_up_2(new_pv)

        # Window overlap check excluding the original plan
        overlap = find_overlap_plan(plot["id"], new_ws, new_we, exclude_plan_id=plan["id"])
        if overlap is not None:
            raise plan_window_overlap()

        new_rec = stamp_create({
            "id": new_id(),
            "plot_id": plot["id"],
            "window_start": new_ws,
            "window_end": new_we,
            "planned_volume_liters": planned,
            "source": "MANUAL_OVERRIDE",
            "status": "DRAFT",
            "plan_version": int(plan.get("plan_version", 1)) + 1,
            "parent_plan_id": plan["id"],
        })
        DB.irrigation_plans[new_rec["id"]] = new_rec

        append_audit(
            action_type="PLAN_OVERRIDDEN",
            subject_type="IRRIGATION_PLAN",
            subject_id=plan["id"],
            payload={
                "original_planned_volume_liters": original_pv,
                "override_planned_volume_liters": planned,
                "new_plan_id": new_rec["id"],
            },
        )

        # Release reservation: recompute covering quota
        q = find_quota_for_command(plan)
        if q is not None:
            recompute_quota_aggregates(q)
    return success_object(irrigation_plan_view(new_rec), status=201)


@bp.route("/plots/<plot_id>/irrigation-plans/<plan_id>", methods=["DELETE"])
@require_roles("Operator", "WaterAdmin")
def cancel_plan(plot_id, plan_id):
    with LOCK:
        plot, plan = _resolve_plan(plot_id, plan_id)
        if plan["status"] != "DRAFT":
            raise invalid_state("Plan must be DRAFT to cancel")
        plan["status"] = "CANCELLED"
        bump_version(plan)
    return success_no_content(204)


@bp.route("/plots/<plot_id>/irrigation-plans", methods=["GET"])
def list_plans(plot_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator"}:
        raise forbidden()
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    with LOCK:
        plot = _validate_plot_param(plot_id)
        items = [p for p in DB.irrigation_plans.values() if p.get("plot_id") == plot["id"]]
        if status_filter:
            items = [p for p in items if p.get("status") == status_filter]
        items.sort(key=lambda r: r.get("created_at"))
        page, total, has_more = paginate(items, limit, offset)
        data = [irrigation_plan_view(p) for p in page]
    return success_array(data, limit, offset, total, has_more)
