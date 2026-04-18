from decimal import Decimal
from datetime import datetime

from util import fractional_hours, round_half_up, ceil_to_days, ceil_to_blocks

from db import db


def ceil_half_hour_count(hours: Decimal) -> Decimal:
    """Round up hours to the nearest 0.5; return the resulting hours value (Decimal)."""
    if hours <= 0:
        return Decimal(0)
    # Number of half-hour units needed to cover 'hours'
    half_units = (hours * Decimal(2)).to_integral_value(rounding="ROUND_CEILING")
    return half_units / Decimal(2)


def is_full_weekend(start: datetime, end: datetime) -> bool:
    # Both endpoints fall on Saturday or Sunday
    # Monday=0 ... Sunday=6
    return start.weekday() >= 5 and end.weekday() >= 5


def governing_lease_billing_plan(tenant_id: str):
    lease = db.active_lease_for_tenant(tenant_id)
    if lease is None:
        return None, None
    return lease["billing_plan"], lease


def compute_provisional_fee(reservation: dict, resource: dict, tenant_id: str) -> int:
    start = reservation["_start_at_dt"]
    end = reservation["_end_at_dt"]
    hours = fractional_hours(start, end)
    kind = resource["kind"]

    if kind == "MEETING_ROOM":
        billable_hours = ceil_half_hour_count(hours)
        fee = billable_hours * Decimal(resource["hourly_rate_cents"])
        return round_half_up(fee)

    if kind == "EVENT_AREA":
        blocks = ceil_to_blocks(hours, 4)
        gross = blocks * resource["block_rate_cents"]
        if is_full_weekend(start, end):
            return gross // 2
        return gross

    if kind == "WORKSTATION":
        plan, _ = governing_lease_billing_plan(tenant_id)
        if plan == "HOURLY":
            fee = hours * Decimal(resource["hourly_rate_cents"])
            return round_half_up(fee)
        if plan == "DAILY":
            days = ceil_to_days(hours, 8)
            return days * resource["daily_rate_cents"]
        if plan == "MONTHLY":
            return 0
        # No active lease / unsupported -> 0
        return 0

    return 0


def compute_final_fee(reservation: dict, resource: dict, tenant_id: str,
                     actual_start: datetime, actual_end: datetime) -> int:
    start = reservation["_start_at_dt"]
    end = reservation["_end_at_dt"]
    kind = resource["kind"]

    if kind == "EVENT_AREA":
        # Blocks do not refund; final = provisional
        return reservation.get("provisional_fee_cents", 0)

    billable_start = max(start, actual_start)

    if kind == "MEETING_ROOM":
        billable_end = min(end, actual_end)
        if billable_end <= billable_start:
            hours = Decimal(0)
        else:
            hours = fractional_hours(billable_start, billable_end)
        billable_hours = ceil_half_hour_count(hours)
        fee = billable_hours * Decimal(resource["hourly_rate_cents"])
        return round_half_up(fee)

    if kind == "WORKSTATION":
        plan, _ = governing_lease_billing_plan(tenant_id)
        billable_end = actual_end
        if billable_end <= billable_start:
            hours = Decimal(0)
        else:
            hours = fractional_hours(billable_start, billable_end)
        if plan == "MONTHLY":
            return 0
        if plan in ("HOURLY", "DAILY") or plan is None:
            hourly_candidate = round_half_up(hours * Decimal(resource["hourly_rate_cents"]))
            days = ceil_to_days(hours, 8)
            daily_candidate = days * resource["daily_rate_cents"]
            # Pick smaller; tie -> hourly wins
            return hourly_candidate if hourly_candidate <= daily_candidate else daily_candidate
        return 0

    return 0
