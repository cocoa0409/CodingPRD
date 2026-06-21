"""Calculation rules (scaffold §1.3, PRD §2.8/§2.9/§3.5/§3.6/§3.9/§3.11).

All monetary amounts are integer cents. Rounding is round-half-up. We use
decimal.Decimal with ROUND_HALF_UP for every rounding step (never float).
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List

import db


# ---- constants (scaffold §1.3) --------------------------------------------
SERVICE_FEE_RATE = Decimal("0.085")
TIER_LOW_MAX_CENTS = 499
TIER_MID_MAX_CENTS = 999
TIER_LOW_PCT = 0
TIER_MID_PCT = 5
TIER_HIGH_PCT = 10

STRIKE_WEIGHT = 10
GOOD_CREDIT = 3
SUSPEND_THRESHOLD = 30

UTIL_DECIMAL_PLACES = 2


def _round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal to the nearest whole cent, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# amenity_chargeback (scaffold §1.3, PRD §3.5) — PINNED evaluation order.
# ---------------------------------------------------------------------------

def amenity_chargeback(lines: List[Dict]) -> int:
    """Compute the whole-cent chargeback for a selected set of amenity lines.

    Steps (pinned):
      1. line_amounts = [unit_price_cents * quantity for each line]
      2. subtotal     = sum(line_amounts)
      3. per_line_fee = [round_half_up(amount * 0.085) for amount in line_amounts]
      4. fee          = sum(per_line_fee)
      5. pre_discount = subtotal + fee
      6. discount_pct = tier(pre_discount)
      7. discount     = round_half_up(pre_discount * pct / 100)
      8. chargeback   = pre_discount - discount
    Empty set -> 0.
    """
    if not lines:
        return 0

    line_amounts = [int(l["unit_price_cents"]) * int(l["quantity"]) for l in lines]
    subtotal = sum(line_amounts)

    # Step 3: round PER LINE, then sum.
    per_line_fee = [
        _round_half_up_cents(Decimal(amount) * SERVICE_FEE_RATE) for amount in line_amounts
    ]
    fee = sum(per_line_fee)

    pre_discount = subtotal + fee

    if pre_discount <= TIER_LOW_MAX_CENTS:
        pct = TIER_LOW_PCT
    elif pre_discount <= TIER_MID_MAX_CENTS:
        pct = TIER_MID_PCT
    else:
        pct = TIER_HIGH_PCT

    discount = _round_half_up_cents(Decimal(pre_discount) * Decimal(pct) / Decimal(100))
    return pre_discount - discount


def provisional_lines(reservation_id: str) -> List[Dict]:
    """Lines with line_status in {REQUESTED, APPROVED} for a reservation."""
    return [
        a for a in db.amenity_requests.values()
        if a["reservation_id"] == reservation_id
        and a["line_status"] in ("REQUESTED", "APPROVED")
    ]


def final_lines(reservation_id: str) -> List[Dict]:
    """Lines with line_status == APPROVED for a reservation."""
    return [
        a for a in db.amenity_requests.values()
        if a["reservation_id"] == reservation_id and a["line_status"] == "APPROVED"
    ]


def compute_provisional(reservation_id: str) -> int:
    return amenity_chargeback(provisional_lines(reservation_id))


def compute_final(reservation_id: str) -> int:
    return amenity_chargeback(final_lines(reservation_id))


# ---------------------------------------------------------------------------
# strike_score (scaffold §1.3, PRD §3.6) — sum deltas after last reinstate,
# floor at 0, derive privilege.
# ---------------------------------------------------------------------------

def compute_strike_score(employee: Dict) -> int:
    """Sum deltas of the employee's NoShowEvent rows created strictly after the
    most recent reinstatement (or all rows if never reinstated), floored at 0."""
    baseline_seq = employee.get("_reinstate_seq", 0)
    raw = 0
    for ev in db.no_show_events.values():
        if ev["employee_id"] != employee["id"]:
            continue
        if ev["_seq"] <= baseline_seq:
            continue
        raw += ev["delta"]
    return max(0, raw)


def derive_privilege(strike_score: int) -> str:
    return "SUSPENDED" if strike_score >= SUSPEND_THRESHOLD else "ACTIVE"


# ---------------------------------------------------------------------------
# neighborhood derived fields (PRD §2.8/§3.1/§3.9): seat_count + effective_cap.
# ---------------------------------------------------------------------------

def recompute_neighborhood(neigh: Dict) -> None:
    """Recompute seat_count (non-RETIRED seats) and effective_cap_seats =
    ceil(seat_count * capacity_cap_pct / 100)."""
    seat_count = sum(
        1 for s in db.seats.values()
        if s["neighborhood_id"] == neigh["id"] and s["status"] != "RETIRED"
    )
    cap_pct = neigh["capacity_cap_pct"]
    effective = math.ceil(seat_count * cap_pct / 100)
    neigh["seat_count"] = seat_count
    neigh["effective_cap_seats"] = effective


# ---------------------------------------------------------------------------
# neighborhood_capacity_check (scaffold §1.3, PRD §3.9).
# ---------------------------------------------------------------------------

def distinct_reserved_seats(neighborhood_id: str, booking_date: str) -> set:
    """Distinct seat_id values across reservations in the neighborhood on the
    date whose occupancy_status is BOOKED or CHECKED_IN."""
    out = set()
    for r in db.reservations.values():
        if r["resource_type"] != "SEAT":
            continue
        if r["booking_date"] != booking_date:
            continue
        if r["occupancy_status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        seat = db.seats.get(r["seat_id"])
        if seat is None or seat["neighborhood_id"] != neighborhood_id:
            continue
        out.add(r["seat_id"])
    return out


def capacity_allows(neigh: Dict, booking_date: str, new_seat_id: str) -> bool:
    """True iff booking new_seat_id on booking_date respects effective_cap_seats.
    If new_seat_id is already among the distinct reserved seats, no extra capacity
    is consumed. Otherwise distinct + 1 <= effective_cap_seats (<= at boundary)."""
    recompute_neighborhood(neigh)
    effective = neigh["effective_cap_seats"]
    reserved = distinct_reserved_seats(neigh["id"], booking_date)
    if new_seat_id in reserved:
        return True
    return (len(reserved) + 1) <= effective


# ---------------------------------------------------------------------------
# utilization_report (scaffold §1.3, PRD §3.11) — dual variant.
# ---------------------------------------------------------------------------

_PLANNED_STATUSES = ("BOOKED", "CHECKED_IN", "COMPLETED")
_REALIZED_STATUSES = ("CHECKED_IN", "COMPLETED")


def _round_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def utilization_report(floor: Dict, date: str, mode: str) -> Dict:
    """Compute floor utilization for a date in PLANNED (default) or REALIZED mode."""
    statuses = _REALIZED_STATUSES if mode == "REALIZED" else _PLANNED_STATUSES
    capacity_minutes = floor["capacity_minutes"]

    # seats on this floor (via neighborhood) whose status != RETIRED
    neigh_ids = {n["id"] for n in db.neighborhoods.values() if n["floor_id"] == floor["id"]}
    seats = [
        s for s in db.seats.values()
        if s["neighborhood_id"] in neigh_ids and s["status"] != "RETIRED"
    ]

    seat_breakdown = []
    seat_pcts = []
    # order by creation for a deterministic breakdown (mean is order-free anyway)
    for s in sorted(seats, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0))):
        booked = 0
        for r in db.reservations.values():
            if r["resource_type"] != "SEAT":
                continue
            if r["seat_id"] != s["id"]:
                continue
            if r["booking_date"] != date:
                continue
            if r["occupancy_status"] not in statuses:
                continue
            # occupied minutes for this variant = end - start while counted
            booked += (r["end_minute"] - r["start_minute"])
        if capacity_minutes > 0:
            seat_pct = _round_2dp(Decimal(booked) / Decimal(capacity_minutes) * Decimal(100))
        else:
            seat_pct = Decimal("0.00")
        seat_pcts.append(seat_pct)
        seat_breakdown.append({
            "seat_id": s["id"],
            "booked_minutes": booked,
            "seat_utilization_pct": float(seat_pct),
        })

    if not seat_pcts:
        floor_pct = Decimal("0.00")
    else:
        mean = sum(seat_pcts) / Decimal(len(seat_pcts))
        floor_pct = _round_2dp(mean)

    return {
        "floor_utilization_pct": float(floor_pct),
        "capacity_minutes": capacity_minutes,
        "seat_breakdown": seat_breakdown,
        "mode": "REALIZED" if mode == "REALIZED" else "PLANNED",
        "date": date,
    }
