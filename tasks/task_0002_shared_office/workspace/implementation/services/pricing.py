"""Reservation pricing: provisional and final fee calculations."""
import math
from decimal import Decimal

from clock import parse_iso
from db import db
from services.money import round_half_up_to_int
from services.lease_lookup import governing_lease


def _hours_between(start_at, end_at) -> Decimal:
    start_dt = parse_iso(start_at) if isinstance(start_at, str) else start_at
    end_dt = parse_iso(end_at) if isinstance(end_at, str) else end_at
    seconds = Decimal(str((end_dt - start_dt).total_seconds()))
    return seconds / Decimal(3600)


def provisional_fee(reservation: dict) -> int:
    resource = db.resources.get(reservation["resource_id"])
    if not resource:
        return 0
    hours = _hours_between(reservation["start_at"], reservation["end_at"])
    if hours <= 0:
        return 0

    kind = resource["kind"]
    if kind == "MEETING_ROOM":
        # units = ceil(hours * 2) / 2 — half-hour granularity
        units_half = math.ceil(float(hours) * 2)  # number of half-hours
        units = Decimal(units_half) / Decimal(2)
        fee = units * Decimal(resource["hourly_rate_cents"])
        return round_half_up_to_int(fee)

    if kind == "EVENT_AREA":
        blocks = math.ceil(float(hours) / 4)
        start_dt = parse_iso(reservation["start_at"])
        end_dt = parse_iso(reservation["end_at"])
        is_weekend = (start_dt.weekday() in (5, 6)) and (end_dt.weekday() in (5, 6))
        gross = blocks * resource["block_rate_cents"]
        return gross // 2 if is_weekend else gross

    if kind == "WORKSTATION":
        member = db.members.get(reservation["member_id"])
        tenant_id = reservation["tenant_id"]
        lease = governing_lease(tenant_id)
        if lease is None:
            # No active lease — fallback: hourly
            plan = "HOURLY"
        else:
            plan = lease["billing_plan"]
        if plan == "HOURLY":
            fee = hours * Decimal(resource["hourly_rate_cents"])
            return round_half_up_to_int(fee)
        if plan == "DAILY":
            days = math.ceil(float(hours) / 8)
            return days * resource["daily_rate_cents"]
        if plan == "MONTHLY":
            return 0
    return 0


def final_fee(reservation: dict, transition: str) -> int:
    """
    transition in {"COMPLETED", "NO_SHOW"}
    For NO_SHOW, returns provisional_fee_cents already on the reservation.
    """
    if transition == "NO_SHOW":
        return reservation.get("provisional_fee_cents", 0)

    resource = db.resources.get(reservation["resource_id"])
    if not resource:
        return 0

    start_at = parse_iso(reservation["start_at"])
    end_at = parse_iso(reservation["end_at"])
    actual_start = parse_iso(reservation["actual_start_at"]) if reservation.get("actual_start_at") else start_at
    actual_end = parse_iso(reservation["actual_end_at"]) if reservation.get("actual_end_at") else end_at

    billable_start = max(start_at, actual_start)
    kind = resource["kind"]
    if kind == "WORKSTATION":
        billable_end = actual_end
    else:
        billable_end = min(end_at, actual_end)

    hours_sec = (billable_end - billable_start).total_seconds()
    hours_actual = Decimal(str(max(0.0, hours_sec))) / Decimal(3600)

    if kind == "MEETING_ROOM":
        units_half = math.ceil(float(hours_actual) * 2)
        units = Decimal(units_half) / Decimal(2)
        fee = units * Decimal(resource["hourly_rate_cents"])
        return round_half_up_to_int(fee)

    if kind == "EVENT_AREA":
        return reservation.get("provisional_fee_cents", 0)

    if kind == "WORKSTATION":
        lease = governing_lease(reservation["tenant_id"])
        plan = lease["billing_plan"] if lease else "HOURLY"
        if plan == "MONTHLY":
            return 0
        hourly_cost = round_half_up_to_int(hours_actual * Decimal(resource["hourly_rate_cents"]))
        days_used = math.ceil(float(hours_actual) / 8) if hours_actual > 0 else 0
        daily_cost = days_used * resource["daily_rate_cents"]
        # pick cheaper — tie-break: hourly wins
        if hourly_cost <= daily_cost:
            return hourly_cost
        return daily_cost

    return 0
