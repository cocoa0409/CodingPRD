"""Effective submission date, agency turnaround, the completion projection and
the feasibility verdict (PRD 3.9, calculations effective_submission_date /
agency_turnaround_days / projected_completion_date / feasibility_evaluation)."""
import datetime as _dt

import clock
from calendar_util import (
    advance_business_days,
    is_business_day,
    next_business_day_on_or_after,
)
from constants import (
    BUSINESS_DAY_MINUTES,
    COURIER_LEG_BUSINESS_DAYS,
    DELIVERY_BUSINESS_DAYS,
    TIER_CUTOFF_HOUR,
    TIER_TURNAROUND_DAYS,
    TRAVEL_DATE_BUFFER_DAYS,
)
from services import lookup, sla


def effective_submission_date(order, consulate=None):
    """Strict `<` on the cutoff: submitting AT the cutoff hour rolls forward."""
    if consulate is None:
        consulate = lookup.consulate_of(order)
    cutoff = TIER_CUTOFF_HOUR[order["service_level"]]
    instant = clock.now()
    day = instant.date()
    if is_business_day(day, consulate) and instant.hour < cutoff:
        return day
    return advance_business_days(day, 1, consulate)


def agency_turnaround_days(order):
    catalog = lookup.catalog_of(order)
    override = catalog.get("agency_turnaround_override_days") if catalog else None
    if override is not None:
        return override
    return TIER_TURNAROUND_DAYS[order["service_level"]]


def project(order):
    """Returns (projected_completion_date, effective_submission_date_used,
    turnaround_days, variant_used)."""
    consulate = lookup.consulate_of(order)
    turnaround = agency_turnaround_days(order)

    if order["submitted_at"] is None:
        base = effective_submission_date(order, consulate)
        d1 = advance_business_days(base, COURIER_LEG_BUSINESS_DAYS, consulate)
        d2 = advance_business_days(d1, turnaround, consulate)
        d3 = advance_business_days(d2, COURIER_LEG_BUSINESS_DAYS, consulate)
        projected = advance_business_days(d3, DELIVERY_BUSINESS_DAYS, consulate)
        return projected, base, turnaround, "tier_nominal"

    base = next_business_day_on_or_after(clock.now().date(), consulate)
    consumed = sla.running_minutes(order) // BUSINESS_DAY_MINUTES
    remaining = max(turnaround - consumed, 0)
    d2 = advance_business_days(base, remaining, consulate)
    d3 = advance_business_days(d2, COURIER_LEG_BUSINESS_DAYS, consulate)
    projected = advance_business_days(d3, DELIVERY_BUSINESS_DAYS, consulate)
    return projected, order["effective_submission_date"], turnaround, "observed_actual"


def deadline_date(order):
    return order["travel_date"] - _dt.timedelta(days=TRAVEL_DATE_BUFFER_DAYS)


def verdict(order, projected):
    """Inclusive boundary: landing exactly on the deadline date is FEASIBLE."""
    return "FEASIBLE" if projected <= deadline_date(order) else "INFEASIBLE"


def run_projection_and_feasibility(order):
    """Writes projected_completion_date and feasibility_status; every re-run
    revokes a standing acknowledgment."""
    projected, _base, _turnaround, _variant = project(order)
    order["projected_completion_date"] = projected
    order["feasibility_status"] = verdict(order, projected)
    order["acknowledged_by_user_id"] = None
    return order["feasibility_status"]
