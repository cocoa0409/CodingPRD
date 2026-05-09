"""Production lifecycle routes."""
import copy
from flask import Blueprint, g

import errors as E
from db import store, init_common, touch
from clock import parse_iso8601
from middleware import require_roles, parse_pagination
from response import ok_object, ok_array
from body import (
    get_json_body,
    require_string,
    require_enum,
    require_int,
)
from services.occ import check_version
from services.audit import log as audit_log
from services.budget import (
    categories_for_production,
    recompute_posture,
    evaluate_posture,
    category_alert_state,
)
from services.calc import cast_commit_estimate, crew_payroll, residual_budget
from services.serializers import (
    serialize_production,
    serialize_scene,
    paginate,
)


bp = Blueprint("productions", __name__)


PRODUCTION_TYPES = {"FILM", "TV_SERIES", "DOCUMENTARY", "COMMERCIAL"}
PRODUCTION_STATUSES = {"PLANNING", "IN_PRODUCTION", "WRAP_PENDING", "WRAPPED", "CANCELLED"}


def _get_production_or_404(pid):
    p = store.productions.get(pid)
    if not p:
        E.not_found(f"Production {pid} not found")
    return p


def _existing_active_titles_excluding(pid=None):
    out = set()
    for p in store.productions.values():
        if pid is not None and p["id"] == pid:
            continue
        if p["status"] in {"CANCELLED", "WRAPPED"}:
            continue
        out.add(p["title"])
    return out


@bp.route("/productions", methods=["POST"])
@require_roles("ExecutiveProducer")
def create_production():
    body = get_json_body()
    title = require_string(body, "title", min_len=1, max_len=200)
    production_type = require_enum(body, "production_type", PRODUCTION_TYPES)
    sw_start = require_string(body, "shoot_window_start")
    sw_end = require_string(body, "shoot_window_end")
    total_budget = require_int(body, "total_budget_cents", minv=0)
    reserve = require_int(body, "reserve_fund_cents", minv=0)

    # Validate datetimes
    try:
        start_dt = parse_iso8601(sw_start)
        end_dt = parse_iso8601(sw_end)
    except Exception:
        E.validation_err("Invalid datetime format for shoot_window")
    if start_dt >= end_dt:
        E.validation_err("shoot_window_start must be before shoot_window_end")
    if reserve > total_budget:
        E.validation_err("reserve_fund_cents must be <= total_budget_cents")

    with store.lock:
        if title in _existing_active_titles_excluding():
            E.validation_err("Title already in use by an active production")

        rec = {
            "title": title,
            "production_type": production_type,
            "shoot_window_start": sw_start,
            "shoot_window_end": sw_end,
            "total_budget_cents": total_budget,
            "reserve_fund_cents": reserve,
            "status": "PLANNING",
            "posture": "GREEN",
            "schedule_baseline_locked_at": None,
            "spent_cents": 0,
            "committed_cents": 0,
            "residual_cents": 0,
        }
        init_common(rec)
        store.productions[rec["id"]] = rec
        return ok_object(serialize_production(rec), http_status=201)


@bp.route("/productions/<pid>", methods=["GET"])
@require_roles(
    "ExecutiveProducer",
    "LineProducer",
    "FinanceController",
    "CastingDirector",
    "ProductionCoordinator",
)
def get_production(pid):
    p = _get_production_or_404(pid)
    return ok_object(serialize_production(p))


@bp.route("/productions", methods=["GET"])
@require_roles(
    "ExecutiveProducer",
    "LineProducer",
    "FinanceController",
    "CastingDirector",
    "ProductionCoordinator",
)
def list_productions():
    limit, offset = parse_pagination()
    from flask import request
    status_filter = request.args.get("status")
    type_filter = request.args.get("production_type")
    items = list(store.productions.values())
    if status_filter:
        if status_filter not in PRODUCTION_STATUSES:
            E.validation_err("Invalid status filter")
        items = [i for i in items if i["status"] == status_filter]
    if type_filter:
        if type_filter not in PRODUCTION_TYPES:
            E.validation_err("Invalid production_type filter")
        items = [i for i in items if i["production_type"] == type_filter]
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize_production(p) for p in page], limit, offset, total, has_more)


@bp.route("/productions/<pid>/lock-baseline", methods=["POST"])
@require_roles("LineProducer")
def lock_baseline(pid):
    body = get_json_body()
    with store.lock:
        p = _get_production_or_404(pid)
        check_version(p, body)
        # State precondition
        if p["status"] != "PLANNING":
            E.invalid_state("Baseline can only be locked from PLANNING")
        # Posture gate (FROZEN blocks)
        if p["posture"] == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        # Preconditions
        if p.get("schedule_baseline_locked_at") is not None:
            E.invalid_state("Baseline already locked")
        # at least one Scene SCHEDULED
        scenes = [s for s in store.scenes.values() if s["production_id"] == pid]
        if not any(s["status"] == "SCHEDULED" for s in scenes):
            E.invalid_state("At least one Scene must be SCHEDULED before lock-baseline")
        # sum of planned <= total - reserve
        cats = categories_for_production(pid)
        planned_sum = sum(c.get("planned_cents", 0) for c in cats)
        if planned_sum > p["total_budget_cents"] - p["reserve_fund_cents"]:
            E.budget_overallocated(
                "Sum of planned_cents exceeds total_budget_cents - reserve_fund_cents"
            )

        before = copy.deepcopy(p)
        # Cascade: BOOKED → ACTIVE for all crew assignments
        crew_cat = next((c for c in cats if c["code"] == "CREW"), None)
        for ca in store.crew_assignments.values():
            if ca["production_id"] != pid:
                continue
            if ca["status"] == "BOOKED":
                ca["status"] = "ACTIVE"
                touch(ca)
                if crew_cat is not None:
                    crew_cat["committed_cents"] = crew_cat.get("committed_cents", 0) + ca[
                        "day_rate_cents"
                    ] * ca["scheduled_days"]
                    touch(crew_cat)

        from clock import clock as _clock
        p["schedule_baseline_locked_at"] = _clock.now_iso()
        p["status"] = "IN_PRODUCTION"
        touch(p)
        # recompute posture
        recompute_posture(p, actor_user_id=g.user_id)
        # AuditLog SCHEDULE_CHANGE
        audit_log(
            production_id=pid,
            actor_user_id=g.user_id,
            action="SCHEDULE_CHANGE",
            subject_entity="Production",
            subject_id=pid,
            before=before,
            after=copy.deepcopy(p),
        )
        return ok_object(serialize_production(p))


@bp.route("/productions/<pid>/begin-wrap", methods=["POST"])
@require_roles("LineProducer")
def begin_wrap(pid):
    body = get_json_body()
    with store.lock:
        p = _get_production_or_404(pid)
        check_version(p, body)
        if p["status"] != "IN_PRODUCTION":
            E.invalid_state("begin-wrap requires IN_PRODUCTION")
        # Posture FROZEN blocks non-wrap-progression — but begin-wrap IS a wrap-progression
        # Preconditions
        scenes = [s for s in store.scenes.values() if s["production_id"] == pid]
        for s in scenes:
            if s["status"] not in {"SHOT", "OMITTED"}:
                E.invalid_state("All scenes must be SHOT or OMITTED before begin-wrap")
        for r in store.location_reservations.values():
            if r["production_id"] != pid:
                continue
            if r["status"] not in {"FULFILLED", "RELEASED"}:
                E.invalid_state("All reservations must be FULFILLED or RELEASED before begin-wrap")
        # No equipment for this production currently CHECKED_OUT — last check_event for the prod
        for ev in store.equipment_events.values():
            pass
        for eq in store.equipment.values():
            if eq["status"] == "CHECKED_OUT":
                # Find last event to determine production
                last_ev_id = eq.get("last_check_event_id")
                if last_ev_id:
                    ev = store.equipment_events.get(last_ev_id)
                    if ev and ev.get("production_id") == pid:
                        E.invalid_state("Equipment still CHECKED_OUT for this production")

        before = copy.deepcopy(p)
        p["status"] = "WRAP_PENDING"
        p["posture"] = "FROZEN"
        touch(p)
        # Cascade: ACTIVE → RELEASED for all crew assignments
        for ca in store.crew_assignments.values():
            if ca["production_id"] != pid:
                continue
            if ca["status"] == "ACTIVE":
                ca["status"] = "RELEASED"
                touch(ca)
        audit_log(
            production_id=pid,
            actor_user_id=g.user_id,
            action="SCHEDULE_CHANGE",
            subject_entity="Production",
            subject_id=pid,
            before=before,
            after=copy.deepcopy(p),
        )
        return ok_object(serialize_production(p))


@bp.route("/productions/<pid>/close-account", methods=["POST"])
@require_roles("FinanceController")
def close_account(pid):
    body = get_json_body()
    with store.lock:
        p = _get_production_or_404(pid)
        check_version(p, body)
        if p["status"] != "WRAP_PENDING":
            E.invalid_state("close-account requires WRAP_PENDING")
        # Preconditions: all CrewAssignment in {RELEASED, SETTLED}; all VendorInvoice in {PAID, DISPUTED}
        # Per PRD §3.8: any breach of these state requirements is rejected with ERR_OPEN_OBLIGATIONS.
        crew = [ca for ca in store.crew_assignments.values() if ca["production_id"] == pid]
        for ca in crew:
            if ca["status"] not in {"RELEASED", "SETTLED"}:
                E.open_obligations("All crew assignments must be RELEASED or SETTLED")
        invoices = [v for v in store.vendor_invoices.values() if v["production_id"] == pid]
        for v in invoices:
            if v["status"] not in {"PAID", "DISPUTED"}:
                E.open_obligations("All vendor invoices must be PAID or DISPUTED")

        # Equipment must not be in DAMAGED/LOST/CHECKED_OUT for this production.
        for eq in store.equipment.values():
            last_ev_id = eq.get("last_check_event_id")
            if last_ev_id:
                ev = store.equipment_events.get(last_ev_id)
                if ev and ev.get("production_id") == pid:
                    if eq["status"] in {"DAMAGED", "LOST", "CHECKED_OUT"}:
                        E.open_obligations("Equipment in DAMAGED/LOST/CHECKED_OUT state for this production")

        cats = categories_for_production(pid)

        # Pre-cascade check: every NON-CREW category's committed_cents must be zero.
        # CREW.committed_cents will be released by the settlement cascade below; per PRD §3.8
        # the post-cascade invariant is that all committed_cents are zero.
        for c in cats:
            if c["code"] == "CREW":
                continue
            if c.get("committed_cents", 0) != 0:
                E.open_obligations("Open committed_cents on a budget category")

        before = copy.deepcopy(p)
        # Cascade: each RELEASED crew assignment → SETTLED with payroll calc
        for ca in crew:
            if ca["status"] == "RELEASED":
                payroll = crew_payroll(
                    ca["day_rate_cents"], ca["scheduled_days"], ca.get("actual_days", 0) or 0,
                    variant="per_component_rounding",
                )
                ca["payroll_cents"] = payroll
                ca["status"] = "SETTLED"
                touch(ca)
                # CREW category committed -= day_rate * scheduled; actual += payroll
                crew_cat = next((c for c in cats if c["code"] == "CREW"), None)
                if crew_cat is not None:
                    crew_cat["committed_cents"] = crew_cat.get("committed_cents", 0) - ca[
                        "day_rate_cents"
                    ] * ca["scheduled_days"]
                    crew_cat["actual_cents"] = crew_cat.get("actual_cents", 0) + payroll
                    touch(crew_cat)

        # After cascade: every category's committed_cents must be 0
        cats = categories_for_production(pid)
        for c in cats:
            if c.get("committed_cents", 0) != 0:
                E.open_obligations("Open committed_cents on a budget category after settlement")

        # Compute residual
        p["residual_cents"] = residual_budget(p, variant="final_at_wrapped")
        p["status"] = "WRAPPED"
        # spent_cents already updated by invoice pays; recompute as sum of actuals
        p["spent_cents"] = sum(c.get("actual_cents", 0) for c in cats)
        p["committed_cents"] = sum(c.get("committed_cents", 0) for c in cats)
        touch(p)

        audit_log(
            production_id=pid,
            actor_user_id=g.user_id,
            action="WRAP_CLOSE",
            subject_entity="Production",
            subject_id=pid,
            before=before,
            after=copy.deepcopy(p),
        )
        return ok_object(serialize_production(p))


@bp.route("/productions/<pid>/cancel", methods=["POST"])
@require_roles("ExecutiveProducer")
def cancel_production(pid):
    body = get_json_body()
    from flask import request
    override = (request.headers.get("X-Override-Reason", "") or "").strip()
    with store.lock:
        p = _get_production_or_404(pid)
        check_version(p, body)
        if p["status"] not in {"PLANNING", "IN_PRODUCTION"}:
            E.invalid_state("Cancel requires PLANNING or IN_PRODUCTION")

        before = copy.deepcopy(p)

        if p["status"] == "PLANNING":
            # No SIGNED roles
            for r in store.roles.values():
                if r["production_id"] == pid and r["casting_status"] == "SIGNED":
                    E.invalid_state("Cannot cancel: signed roles exist")
            # Cascade
            for r in store.location_reservations.values():
                if r["production_id"] != pid:
                    continue
                if r["status"] in {"HELD", "CONFIRMED"}:
                    r["status"] = "RELEASED"
                    touch(r)
            for role in store.roles.values():
                if role["production_id"] != pid:
                    continue
                if role["casting_status"] in {"OPEN", "AUDITIONING", "SHORTLISTED", "OFFERED"}:
                    role["casting_status"] = "RECAST"
                    touch(role)
            p["status"] = "CANCELLED"
            touch(p)
            audit_log(
                production_id=pid, actor_user_id=g.user_id,
                action="SCHEDULE_CHANGE", subject_entity="Production", subject_id=pid,
                before=before, after=copy.deepcopy(p),
            )
        else:
            # IN_PRODUCTION
            if not override:
                E.invalid_state("X-Override-Reason header is required to cancel IN_PRODUCTION")
            for r in store.location_reservations.values():
                if r["production_id"] != pid:
                    continue
                if r["status"] in {"HELD", "CONFIRMED", "RESCHEDULING"}:
                    r["status"] = "RELEASED"
                    touch(r)
            for ca in store.crew_assignments.values():
                if ca["production_id"] != pid:
                    continue
                if ca["status"] == "ACTIVE":
                    ca["status"] = "RELEASED"
                    touch(ca)
            for co in store.change_orders.values():
                if co["production_id"] != pid:
                    continue
                if co["status"] == "PENDING":
                    co["status"] = "CANCELLED"
                    touch(co)
            p["status"] = "CANCELLED"
            touch(p)
            audit_log(
                production_id=pid, actor_user_id=g.user_id,
                action="SCHEDULE_CHANGE", subject_entity="Production", subject_id=pid,
                before=before, after=copy.deepcopy(p),
                extra={"override_reason": override},
            )
        return ok_object(serialize_production(p))


@bp.route("/productions/<pid>/wrap-preview", methods=["GET"])
@require_roles("LineProducer", "FinanceController")
def wrap_preview(pid):
    p = _get_production_or_404(pid)
    cats = categories_for_production(pid)
    actual_sum = sum(c.get("actual_cents", 0) for c in cats)
    committed_sum = sum(c.get("committed_cents", 0) for c in cats)
    provisional_residual = p["total_budget_cents"] - actual_sum - committed_sum
    # Forecasted payroll for each crew assignment using total_then_round (display) variant
    payroll_forecast = []
    for ca in store.crew_assignments.values():
        if ca["production_id"] != pid:
            continue
        actual_days = ca.get("actual_days", 0) or 0
        amt = crew_payroll(
            ca["day_rate_cents"], ca["scheduled_days"], actual_days,
            variant="total_then_round",
        )
        payroll_forecast.append({
            "crew_assignment_id": ca["id"],
            "forecast_payroll_cents": amt,
        })
    return ok_object({
        "production_id": pid,
        "provisional_residual_cents": provisional_residual,
        "actual_cents_sum": actual_sum,
        "committed_cents_sum": committed_sum,
        "payroll_forecast": payroll_forecast,
    })
