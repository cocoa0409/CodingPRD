"""IrrigationPlan state machine helpers."""

from clock import CLOCK
from db import DB
from services.common import bump_version, to_aware_utc


def find_overlap_plan(plot_id, window_start, window_end, exclude_plan_id=None):
    """Return the first IrrigationPlan on the plot whose [start,end) overlaps and whose status is
    in {ACTIVE, SUSPENDED}. Half-open intervals: [a,b) overlaps [c,d) iff a < d and c < b."""
    ws = to_aware_utc(window_start)
    we = to_aware_utc(window_end)
    for p in DB.irrigation_plans.values():
        if p.get("plot_id") != plot_id:
            continue
        if exclude_plan_id is not None and p.get("id") == exclude_plan_id:
            continue
        if p.get("status") not in ("ACTIVE", "SUSPENDED"):
            continue
        ps = to_aware_utc(p["window_start"])
        pe = to_aware_utc(p["window_end"])
        if ws < pe and ps < we:
            return p
    return None


def fail_pending_commands_for_plan(plan, reason):
    """When a plan is suspended, transition every PENDING command to FAILED with the reason.
    Releases reservations (final_used_liters/provisional_used_liters are recomputed).
    """
    affected = []
    for cmd in list(DB.control_commands.values()):
        if cmd.get("plan_id") != plan["id"]:
            continue
        if cmd.get("status") != "PENDING":
            continue
        cmd["status"] = "FAILED"
        cmd["failure_reason"] = reason
        bump_version(cmd)
        affected.append(cmd)
    return affected


def suspend_plan_system(plan):
    """System suspension cascade: ACTIVE -> SUSPENDED, fail PENDING commands, refresh quota."""
    if plan.get("status") != "ACTIVE":
        return
    plan["status"] = "SUSPENDED"
    bump_version(plan)
    fail_pending_commands_for_plan(plan, "PLAN_SUSPENDED")
    # Recompute the covering quota's provisional usage.
    from services.quota import find_quota_for_command, recompute_quota_aggregates
    q = find_quota_for_command(plan)
    if q is not None:
        recompute_quota_aggregates(q)


def auto_complete_plans(now):
    """If now() >= window_end and no command is in PENDING/DISPATCHING/EXECUTING, ACTIVE -> COMPLETED."""
    now = to_aware_utc(now)
    for plan in list(DB.irrigation_plans.values()):
        if plan.get("status") != "ACTIVE":
            continue
        we = to_aware_utc(plan["window_end"])
        if now < we:
            continue
        # No in-flight commands?
        in_flight = False
        for cmd in DB.control_commands.values():
            if cmd.get("plan_id") != plan["id"]:
                continue
            if cmd.get("status") in ("PENDING", "DISPATCHING", "EXECUTING"):
                in_flight = True
                break
        if in_flight:
            continue
        plan["status"] = "COMPLETED"
        bump_version(plan)
        # Reservation reconciles automatically (we recompute aggregates on demand).
        from services.quota import find_quota_for_command, recompute_quota_aggregates
        q = find_quota_for_command(plan)
        if q is not None:
            recompute_quota_aggregates(q)
