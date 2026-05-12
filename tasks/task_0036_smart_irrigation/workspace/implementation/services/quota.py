"""WaterQuota helpers: locate covering quota, recompute state and cascades."""

from clock import CLOCK
from db import DB
from services.common import bump_version, to_aware_utc
from services.calculations import (
    compute_provisional_used_liters,
    compute_final_used_liters,
    derive_usage_state,
    compute_severity,
)


def find_covering_quota(plot_id, window_start, window_end):
    """Return the quota whose [period_start, period_end) covers [window_start, window_end).

    Uses overlap check for partial coverage (any overlap with the plan window).
    Prefers a fully-covering quota, otherwise returns first overlapping quota.
    """
    ws = to_aware_utc(window_start)
    we = to_aware_utc(window_end)
    fully = []
    overlapping = []
    for q in DB.water_quotas.values():
        if q.get("plot_id") != plot_id:
            continue
        ps = to_aware_utc(q["period_start"])
        pe = to_aware_utc(q["period_end"])
        if ps <= ws and we <= pe:
            fully.append(q)
        elif ps < we and ws < pe:
            overlapping.append(q)
    if fully:
        fully.sort(key=lambda q: q.get("created_at"))
        return fully[0]
    if overlapping:
        overlapping.sort(key=lambda q: q.get("created_at"))
        return overlapping[0]
    return None


def find_quota_for_command(plan):
    """Resolve the WaterQuota covering the plan's window for the plan's plot."""
    return find_covering_quota(plan["plot_id"], plan["window_start"], plan["window_end"])


def recompute_quota_aggregates(quota):
    """Recompute provisional_used_liters, final_used_liters, and usage_state."""
    quota["provisional_used_liters"] = compute_provisional_used_liters(quota)
    quota["final_used_liters"] = compute_final_used_liters(quota)
    quota["usage_state"] = derive_usage_state(quota)
    bump_version(quota)
    return quota


def emit_warning_alert_for_plot(quota):
    """Emit ABNORMAL_FLOW WARN alert when quota crosses to WARNING from UNDER."""
    from services.alerts import emit_alert
    emit_alert(
        rule_code="ABNORMAL_FLOW",
        subject_type="PLOT",
        subject_id=quota["plot_id"],
        tenant_id=_tenant_for_plot(quota["plot_id"]),
    )


def emit_over_alert_for_plot(quota):
    """When usage flips to OVER, emit alert and cascade plan suspensions."""
    from services.alerts import emit_alert
    emit_alert(
        rule_code="ABNORMAL_FLOW",
        subject_type="PLOT",
        subject_id=quota["plot_id"],
        tenant_id=_tenant_for_plot(quota["plot_id"]),
    )


def _tenant_for_plot(plot_id):
    plot = DB.plots.get(plot_id)
    return plot.get("tenant_id") if plot else None


def cascade_active_plans_to_suspended(plot_id):
    """When quota flips to OVER and approval_state == NOT_REQUIRED, suspend all ACTIVE plans on the plot.

    Each suspended plan also cascades to fail PENDING ControlCommands tied to it
    and releases the remaining reservation.
    """
    from services.plans import suspend_plan_system
    affected = []
    for plan in list(DB.irrigation_plans.values()):
        if plan.get("plot_id") != plot_id:
            continue
        if plan.get("status") != "ACTIVE":
            continue
        suspend_plan_system(plan)
        affected.append(plan["id"])
    return affected


def on_quota_state_change(quota, prev_usage_state):
    """After recomputing usage_state, fire side effects for cross-state transitions.

    UNDER -> WARNING: emit ABNORMAL_FLOW WARN alert
    *     -> OVER (and approval_state == NOT_REQUIRED): emit alert and cascade suspensions
    """
    new_state = quota["usage_state"]
    if new_state == prev_usage_state:
        return
    if new_state == "WARNING" and prev_usage_state == "UNDER":
        emit_warning_alert_for_plot(quota)
    elif new_state == "OVER" and prev_usage_state != "OVER":
        if quota.get("approval_state") == "NOT_REQUIRED":
            emit_over_alert_for_plot(quota)
            cascade_active_plans_to_suspended(quota["plot_id"])
