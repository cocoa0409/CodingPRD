"""SLA deadline calculations (PRD 3.5).

  effective_sla_minutes : tighten base ack minutes by service budget posture.
  incident_sla_deadlines: stamp ack/resolve deadlines using calendar (TIER_2/3)
                          or business_hours (TIER_1) variant.
"""
import math
from datetime import timedelta

from services import budget

ACK_SLA_MINUTES = {"SEV1": 15, "SEV2": 30, "SEV3": 120, "SEV4": 480}
RESOLVE_SLA_MINUTES = {"SEV1": 240, "SEV2": 480, "SEV3": 1440, "SEV4": 4320}
BUDGET_PRESSURE_FACTOR = 0.5      # EXHAUSTED
WARNING_PRESSURE_FACTOR = 0.75    # WARNING
SLA_FLOOR_MINUTES = 5
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 17


def effective_ack_minutes(severity, service_budget_status):
    """Pinned order: base -> tighten by posture -> floor/min clamp."""
    base = ACK_SLA_MINUTES[severity]
    if service_budget_status == "EXHAUSTED":
        tightened = math.ceil(base * BUDGET_PRESSURE_FACTOR)
    elif service_budget_status == "WARNING":
        tightened = math.ceil(base * WARNING_PRESSURE_FACTOR)
    else:
        tightened = base
    return max(SLA_FLOOR_MINUTES, min(base, tightened))


def _is_business_minute(dt):
    """Mon-Fri (weekday 0-4) and hour in [09:00, 17:00) UTC."""
    if dt.weekday() >= 5:
        return False
    return BUSINESS_START_HOUR <= dt.hour < BUSINESS_END_HOUR


def _calendar_deadline(triggered_at, minutes):
    return triggered_at + timedelta(minutes=minutes)


def _business_hours_deadline(triggered_at, minutes):
    """Walk forward consuming only business minutes until `minutes` consumed.

    The wall-clock instant reached when the required count is consumed is the
    deadline. We advance minute by minute; a minute [t, t+1) counts toward the
    budget only if its start instant t falls inside the business window.
    """
    if minutes <= 0:
        return triggered_at
    cur = triggered_at
    consumed = 0
    # Cap iterations defensively; minutes are bounded (max 4320 business mins).
    max_iter = minutes * 6 + 60 * 24 * 14
    iters = 0
    while consumed < minutes and iters < max_iter:
        if _is_business_minute(cur):
            consumed += 1
            cur = cur + timedelta(minutes=1)
        else:
            cur = cur + timedelta(minutes=1)
        iters += 1
    return cur


def compute_deadlines(triggered_at, severity, service):
    """Return (ack_deadline_at, resolve_deadline_at) as aware datetimes.

    ack uses effective ack minutes (folds in budget pressure); resolve uses
    the base resolve minutes for the severity.
    """
    status = budget.budget_status(service)
    eff_ack = effective_ack_minutes(severity, status)
    base_res = RESOLVE_SLA_MINUTES[severity]

    if service["tier"] == "TIER_1":
        ack_deadline = _business_hours_deadline(triggered_at, eff_ack)
        res_deadline = _business_hours_deadline(triggered_at, base_res)
    else:
        ack_deadline = _calendar_deadline(triggered_at, eff_ack)
        res_deadline = _calendar_deadline(triggered_at, base_res)
    return ack_deadline, res_deadline
