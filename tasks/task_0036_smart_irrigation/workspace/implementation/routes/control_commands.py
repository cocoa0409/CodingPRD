"""ControlCommand routes: create, dispatch, feedback, list, read."""

from flask import Blueprint, g, request

from clock import CLOCK
from db import DB, LOCK, new_id
from errors import (
    feedback_already_recorded,
    forbidden,
    invalid_state,
    not_found,
    pump_interlock_busy,
    quota_exceeded,
    validation_error,
    valve_group_pump_mismatch,
)
from middleware import require_roles
from response import success_array, success_object
from services.alerts import emit_alert
from services.audit import append_audit
from services.calculations import derive_usage_state
from services.common import (
    bump_version,
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    round_half_up_2,
    stamp_create,
)
from services.quota import (
    find_quota_for_command,
    on_quota_state_change,
    recompute_quota_aggregates,
)
from services.serializers import control_command_view


bp = Blueprint("control_commands", __name__)


VALID_PHASES = {"STARTED", "COMPLETED", "ERROR"}


@bp.route("/control-commands", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def create_command():
    body = get_json_body()
    plan_id = require_str(body, "plan_id")
    valve_group_id = require_str(body, "valve_group_id")
    if "requested_volume_liters" not in body or body["requested_volume_liters"] is None:
        raise validation_error("requested_volume_liters is required")
    rv = body["requested_volume_liters"]
    if isinstance(rv, bool) or not isinstance(rv, (int, float)):
        raise validation_error("requested_volume_liters must be a number")
    if rv <= 0:
        raise validation_error("requested_volume_liters must be > 0")
    requested = round_half_up_2(rv)

    with LOCK:
        plan = DB.irrigation_plans.get(plan_id)
        if plan is None:
            raise validation_error("plan_id does not exist")
        valve_group = DB.valve_groups.get(valve_group_id)
        if valve_group is None:
            raise validation_error("valve_group_id does not exist")
        plot = DB.plots.get(plan["plot_id"])
        if plot is None:
            raise validation_error("plot does not exist")

        # PRD §3.4: "A control command represents a single dispatch of a
        # measured volume of water against an active plan." Plan-state
        # guard runs before domain checks per PRD §2.9 priority order
        # (state-machine guards before quota/referential checks).
        if plan.get("status") != "ACTIVE":
            raise invalid_state("Plan must be ACTIVE to create a control command")

        # Referential check: valve_group.pump_id must match plot.pump_id (priority 9)
        if valve_group.get("pump_id") != plot.get("pump_id"):
            raise valve_group_pump_mismatch()

        # Quota guard (priority 12)
        q = find_quota_for_command(plan)
        if q is None:
            raise quota_exceeded("No covering quota for plan window")
        recompute_quota_aggregates(q)

        # Hypothetical state if we accept this command. Use final_used + actual already executed
        # plus this requested_volume_liters as a worst-case projection on top of existing in-flight.
        # PRD §3.4: "evaluates whether reserving the new command's requested_volume_liters
        # against WaterQuota.provisional_used_liters would push the covering quota's
        # usage_state to OVER".
        # We model the projection by checking final_used + (provisional + requested) vs effective.
        from services.calculations import effective_allocation
        eff = effective_allocation(q)
        projected_final = float(q.get("final_used_liters", 0)) + float(q.get("provisional_used_liters", 0)) + requested
        would_be_over = projected_final >= eff - 1e-6 if eff > 0 else projected_final > 0
        if would_be_over and q.get("approval_state") != "APPROVED":
            raise quota_exceeded()

        rec = stamp_create({
            "id": new_id(),
            "plan_id": plan_id,
            "valve_group_id": valve_group_id,
            "requested_volume_liters": requested,
            "dispatch_mode": None,
            "status": "PENDING",
            "actual_volume_liters": 0,
            "feedback_received_at": None,
            "failure_reason": None,
        })
        DB.control_commands[rec["id"]] = rec
        # Recompute quota provisional usage to include this new in-flight command.
        recompute_quota_aggregates(q)
    return success_object(control_command_view(rec), status=201)


def _resolve_plot_for_command(cmd):
    plan = DB.irrigation_plans.get(cmd["plan_id"])
    if plan is None:
        return None, None
    plot = DB.plots.get(plan["plot_id"])
    return plan, plot


@bp.route("/control-commands/<command_id>/dispatch", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def dispatch_command(command_id):
    with LOCK:
        cmd = fetch_or_404(DB.control_commands, command_id)
        if cmd["status"] != "PENDING":
            raise invalid_state("Command must be PENDING to dispatch")
        plan, plot = _resolve_plot_for_command(cmd)
        if plan is None or plot is None:
            raise not_found()
        if plan.get("status") != "ACTIVE":
            raise invalid_state("Plan must be ACTIVE to dispatch command")

        device_mode = request.headers.get("X-Device-Mode", "").strip().upper()
        if device_mode == "OFFLINE":
            cmd["dispatch_mode"] = "LOCAL_DEGRADED"
            cmd["status"] = "OFFLINE_LOCAL"
            bump_version(cmd)
            append_audit(
                action_type="CONTROL_COMMAND_ISSUED",
                subject_type="CONTROL_COMMAND",
                subject_id=cmd["id"],
                payload={"dispatch_mode": "LOCAL_DEGRADED"},
            )
            return success_object(control_command_view(cmd))

        # Pump-and-valve interlock (priority 8)
        my_group = DB.valve_groups.get(cmd["valve_group_id"])
        my_pump = plot["pump_id"]
        my_mode = my_group.get("control_mode") if my_group else "SEQUENTIAL"
        for other in DB.control_commands.values():
            if other["id"] == cmd["id"]:
                continue
            if other.get("status") not in ("DISPATCHING", "EXECUTING"):
                continue
            other_plan = DB.irrigation_plans.get(other["plan_id"])
            if other_plan is None:
                continue
            other_plot = DB.plots.get(other_plan["plot_id"])
            if other_plot is None or other_plot.get("pump_id") != my_pump:
                continue
            other_group = DB.valve_groups.get(other["valve_group_id"])
            other_mode = other_group.get("control_mode") if other_group else "SEQUENTIAL"
            # Allowed only if BOTH new and existing are PARALLEL
            if my_mode != "PARALLEL" or other_mode != "PARALLEL":
                raise pump_interlock_busy()

        cmd["dispatch_mode"] = "REMOTE"
        cmd["status"] = "DISPATCHING"
        bump_version(cmd)
        append_audit(
            action_type="CONTROL_COMMAND_ISSUED",
            subject_type="CONTROL_COMMAND",
            subject_id=cmd["id"],
            payload={"dispatch_mode": "REMOTE"},
        )
    return success_object(control_command_view(cmd))


@bp.route("/control-commands/<command_id>/feedback", methods=["POST"])
@require_roles("DeviceAgent", "WaterAdmin")
def command_feedback(command_id):
    body = get_json_body()
    phase = body.get("phase")
    if phase not in VALID_PHASES:
        raise validation_error("phase must be STARTED|COMPLETED|ERROR")

    with LOCK:
        cmd = fetch_or_404(DB.control_commands, command_id)

        # Terminal-state guard: a COMPLETED/ERROR feedback for an already-terminal command
        # is rejected with ERR_FEEDBACK_ALREADY_RECORDED.
        terminal_states = {"EXECUTED", "FAILED"}
        if cmd["status"] in terminal_states:
            raise feedback_already_recorded()

        if phase == "STARTED":
            if cmd["status"] != "DISPATCHING":
                raise invalid_state("STARTED requires DISPATCHING")
            cmd["status"] = "EXECUTING"
            bump_version(cmd)
            return success_object(control_command_view(cmd))

        if phase == "COMPLETED":
            if cmd["status"] not in ("EXECUTING", "OFFLINE_LOCAL"):
                raise invalid_state("COMPLETED requires EXECUTING or OFFLINE_LOCAL")
            actual_raw = body.get("actual_volume_liters")
            if actual_raw is None:
                raise validation_error("actual_volume_liters is required")
            if isinstance(actual_raw, bool) or not isinstance(actual_raw, (int, float)):
                raise validation_error("actual_volume_liters must be a number")
            if actual_raw < 0:
                raise validation_error("actual_volume_liters must be >= 0")
            actual = round_half_up_2(actual_raw)

            cmd["status"] = "EXECUTED"
            cmd["actual_volume_liters"] = actual
            cmd["feedback_received_at"] = CLOCK.now()
            bump_version(cmd)

            # Plot.last_irrigated_at refresh
            plan = DB.irrigation_plans.get(cmd["plan_id"])
            if plan is not None:
                plot = DB.plots.get(plan["plot_id"])
                if plot is not None:
                    plot["last_irrigated_at"] = cmd["feedback_received_at"]
                    bump_version(plot)
                # Quota: debit final_used_liters and recompute usage_state
                q = find_quota_for_command(plan)
                if q is not None:
                    prev_usage = q.get("usage_state", "UNDER")
                    recompute_quota_aggregates(q)
                    on_quota_state_change(q, prev_usage)
            return success_object(control_command_view(cmd))

        # phase == ERROR
        if cmd["status"] not in ("DISPATCHING", "EXECUTING"):
            raise invalid_state("ERROR requires DISPATCHING or EXECUTING")
        reason = body.get("failure_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise validation_error("failure_reason is required")
        cmd["status"] = "FAILED"
        cmd["failure_reason"] = reason
        cmd["feedback_received_at"] = CLOCK.now()
        bump_version(cmd)

        plan = DB.irrigation_plans.get(cmd["plan_id"])
        plot = None
        if plan is not None:
            plot = DB.plots.get(plan["plot_id"])
            q = find_quota_for_command(plan)
            if q is not None:
                recompute_quota_aggregates(q)

        append_audit(
            action_type="CONTROL_COMMAND_FAILED",
            subject_type="CONTROL_COMMAND",
            subject_id=cmd["id"],
            payload={"failure_reason": reason},
        )
        if reason == "VALVE_FAULT":
            tenant_id = plot.get("tenant_id") if plot else None
            emit_alert(
                rule_code="VALVE_FAULT",
                subject_type="VALVE_GROUP",
                subject_id=cmd["valve_group_id"],
                tenant_id=tenant_id,
            )
    return success_object(control_command_view(cmd))


@bp.route("/control-commands/<command_id>", methods=["GET"])
def read_command(command_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator", "DeviceAgent"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.control_commands, command_id)
    return success_object(control_command_view(rec))


@bp.route("/control-commands", methods=["GET"])
def list_commands():
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator"}:
        raise forbidden()
    limit, offset = parse_pagination()
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    with LOCK:
        items = list(DB.control_commands.values())
        if plan_id:
            items = [c for c in items if c.get("plan_id") == plan_id]
        if status:
            items = [c for c in items if c.get("status") == status]
        items.sort(key=lambda r: r.get("created_at"))
        page, total, has_more = paginate(items, limit, offset)
        data = [control_command_view(c) for c in page]
    return success_array(data, limit, offset, total, has_more)
