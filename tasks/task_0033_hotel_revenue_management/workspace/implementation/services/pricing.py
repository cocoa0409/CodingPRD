"""Pricing engine: applicable nightly rate, booked total, refund/no-show calculations."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timezone, timedelta

from db import rate_overrides, room_types, overbooking_policies
from clock import parse_date, daterange


def round_half_up(numerator: int, denominator: int) -> int:
    """Round (numerator / denominator) half-up to integer."""
    if denominator == 0:
        return 0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def applicable_nightly_rate_for(room_type_id: str, d: date) -> int:
    """Return per-night rate cents for (room_type_id, d) — APPROVED override wins, else base."""
    rt = room_types.get(room_type_id)
    base = rt["base_rate_cents"] if rt else 0
    iso_date = d.isoformat()
    for o in rate_overrides.values():
        if (o.get("room_type_id") == room_type_id
                and o.get("stay_date") == iso_date
                and o.get("status") == "APPROVED"):
            return o["applied_rate_cents"]
    return base


def compute_booked_total_cents(reservation: dict) -> int:
    """Sum of applicable_nightly_rate over [check_in_date, check_out_date)."""
    ci = parse_date(reservation["check_in_date"])
    co = parse_date(reservation["check_out_date"])
    total = 0
    for d in daterange(ci, co):
        total += applicable_nightly_rate_for(reservation["room_type_id"], d)
    return total


def refund_ratio_basis_points(refund_tier_code: str, lead_time_hours: float) -> int:
    """Look up refund ratio for (tier, lead_time_hours)."""
    if refund_tier_code == "FLEXIBLE":
        return 10000 if lead_time_hours >= 24 else 5000
    if refund_tier_code == "MODERATE":
        if lead_time_hours >= 168:
            return 10000
        if lead_time_hours >= 72:
            return 5000
        return 0
    if refund_tier_code == "STRICT":
        return 5000 if lead_time_hours >= 336 else 0
    if refund_tier_code == "NON_REFUNDABLE":
        return 0
    return 0


def compute_refund_amount_cents(reservation: dict, rate_plan: dict, cancelled_at_dt: datetime) -> int:
    """Compute refund_amount_cents for a CONFIRMED -> CANCELLED transition.

    Lead time is local-midnight-of-check_in_date minus cancelled_at, expressed in hours.
    Treat 'local midnight' as UTC midnight (the API does not specify a timezone).
    """
    ci_date = parse_date(reservation["check_in_date"])
    ci_midnight = datetime.combine(ci_date, datetime.min.time(), tzinfo=timezone.utc)
    if cancelled_at_dt.tzinfo is None:
        cancelled_at_dt = cancelled_at_dt.replace(tzinfo=timezone.utc)
    delta_seconds = (ci_midnight - cancelled_at_dt).total_seconds()
    lead_time_hours = delta_seconds / 3600.0

    ratio_bp = refund_ratio_basis_points(rate_plan["refund_tier_code"], lead_time_hours)
    booked = reservation["booked_total_cents"]
    return round_half_up(booked * ratio_bp, 10000)


def compute_no_show_charge_cents(reservation: dict, rate_plan: dict) -> int:
    """Tiered no-show charge."""
    booked = reservation["booked_total_cents"]
    tier = rate_plan["refund_tier_code"]
    if tier in ("NON_REFUNDABLE", "STRICT"):
        return booked
    if tier == "MODERATE":
        return round_half_up(booked * 5000, 10000)
    if tier == "FLEXIBLE":
        return round_half_up(booked * 1000, 10000)
    return 0


def compute_commission_settlement(reservation: dict, channel: dict) -> dict:
    """Channel commission at check-out."""
    booked = reservation["booked_total_cents"]
    bp = channel["commission_basis_points"]
    commission = round_half_up(booked * bp, 10000)
    net = booked - commission
    return {"commission_amount_cents": commission, "net_to_hotel_cents": net}


def find_active_policy(room_type_id: str, stay_date_iso: str):
    """Return the ACTIVE OverbookingPolicy for (room_type_id, stay_date_iso) or None."""
    for p in overbooking_policies.values():
        if (p.get("room_type_id") == room_type_id
                and p.get("stay_date") == stay_date_iso
                and p.get("status") == "ACTIVE"):
            return p
    return None


def compute_walkout_estimate(room_type_id: str, stay_date_iso: str) -> dict:
    """Forward-looking walkout cost estimate."""
    from db import reservations as reservations_table, rooms as rooms_table, maintenance_blocks
    from clock import parse_date

    policy = find_active_policy(room_type_id, stay_date_iso)
    if policy is None:
        return None  # caller raises ERR_NOT_FOUND

    sd = parse_date(stay_date_iso)

    # reservations_for_date: CONFIRMED and stay window covers stay_date
    reservations_for_date = 0
    for r in reservations_table.values():
        if (r.get("booking_status") == "CONFIRMED"
                and r.get("room_type_id") == room_type_id):
            ci = parse_date(r["check_in_date"])
            co = parse_date(r["check_out_date"])
            if ci <= sd < co:
                reservations_for_date += 1

    # physical capacity = ACTIVE rooms minus rooms blocked by maintenance covering sd
    active_rooms = [
        rm for rm in rooms_table.values()
        if rm.get("room_type_id") == room_type_id and rm.get("lifecycle_status") == "ACTIVE"
    ]
    physical_count = len(active_rooms)
    blocked_count = 0
    for rm in active_rooms:
        for b in maintenance_blocks.values():
            if (b.get("room_id") == rm["id"]
                    and b.get("status") in ("SCHEDULED", "ACTIVE")):
                bs = parse_date(b["start_date"])
                be = parse_date(b["end_date"])
                if bs <= sd < be:
                    blocked_count += 1
                    break

    physical_capacity = physical_count - blocked_count

    # expected_arrivals = reservations_for_date * (10000 - p_no_show)/10000
    p_ns = policy["estimated_no_show_probability_basis_points"]
    expected_arrivals = (Decimal(reservations_for_date) * Decimal(10000 - p_ns)) / Decimal(10000)
    expected_walkouts = expected_arrivals - Decimal(physical_capacity)
    if expected_walkouts < 0:
        expected_walkouts = Decimal(0)

    # estimated_cost_cents: expected_walkouts * walkout_compensation_cents, half-up to int cents
    cost_dec = expected_walkouts * Decimal(policy["walkout_compensation_cents"])
    estimated_cost_cents = int(cost_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return {
        "room_type_id": room_type_id,
        "stay_date": stay_date_iso,
        "expected_walkouts": float(expected_walkouts),
        "estimated_cost_cents": estimated_cost_cents,
    }
