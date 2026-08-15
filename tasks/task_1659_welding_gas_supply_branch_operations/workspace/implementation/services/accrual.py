"""Rental accrual math per scaffold calculations.rental_accrual.

chargeable_days(t) := max(0, (t - start).days - grace_days)
value_ceil(t)      := ceil(chargeable / period) * rate     (provisional)
value_floor(t)     := floor(chargeable / period) * rate    (billed cycle)
accrued_unbilled   := max(0, value_ceil(as-of) - lifetime_billed - waived)

The as-of date is the logical clock date for ACTIVE/SUSPENDED agreements and
the close date for CLOSED agreements (a closed agreement always nets to 0
because the final charge was posted into lifetime_billed_cents at close).
"""
import db


def rate_for(agreement):
    plan = agreement["rate_plan"]
    if plan == "DEMURRAGE":
        return db.DEMURRAGE_MONTHLY_CENTS
    machine = db.store.machines[agreement["machine_id"]]
    if plan == "DAILY":
        return machine["daily_rate_cents"]
    if plan == "WEEKLY":
        return machine["weekly_rate_cents"]
    return machine["monthly_rate_cents"]


def chargeable_days(agreement, as_of):
    return max(0, (as_of - agreement["_start"]).days - agreement["grace_days"])


def value_ceil(agreement, as_of):
    cd = chargeable_days(agreement, as_of)
    period = db.PERIOD_DAYS[agreement["rate_plan"]]
    return (-(-cd // period)) * rate_for(agreement)


def value_floor(agreement, as_of):
    cd = chargeable_days(agreement, as_of)
    period = db.PERIOD_DAYS[agreement["rate_plan"]]
    return (cd // period) * rate_for(agreement)


def as_of_date(agreement):
    if agreement["status"] == "CLOSED":
        return agreement["_closed_date"]
    return db.clock_date()


def accrued_unbilled(agreement):
    """Provisional (ceil) accrual minus billed and waived, floored at 0."""
    return max(0, value_ceil(agreement, as_of_date(agreement))
               - agreement["lifetime_billed_cents"] - agreement["waived_cents"])


def agreement_view(agreement):
    agreement["accrued_unbilled_cents"] = accrued_unbilled(agreement)
    return agreement
