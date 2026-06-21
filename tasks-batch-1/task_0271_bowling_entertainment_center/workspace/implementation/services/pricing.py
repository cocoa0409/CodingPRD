"""Pricing & temporal-conflict calculations (PRD §2.9, §3.3–§3.6 / SCAFFOLD §1.3).

All money is integer cents. Basis-point multiplications use round-half-up
(PRD §2.8). Decimal is used to avoid float drift.
"""
import math
from datetime import timedelta
from decimal import Decimal

from db import db
from services.util import round_half_up, bps_apply_round, parse_datetime

# Calculation constants (SCAFFOLD §1.3)
SALES_TAX_BPS = 825
BPS_DENOM = 10000
FULL_REFUND_NOTICE_MINUTES = 1440
PARTIAL_REFUND_NOTICE_MINUTES = 120
PARTIAL_REFUND_BPS = 5000
CHECKIN_WINDOW_MINUTES = 30
HOLD_TTL_MINUTES = 60


def _dt(value):
    return parse_datetime(value)


def duration_minutes(res):
    start = _dt(res["start_at"])
    end = _dt(res["end_at"])
    delta = end - start
    return int(delta.total_seconds() // 60)


def _is_peak(start, end, peak_start_hour, peak_end_hour):
    """True if any minute of [start, end) falls in local-hour [peak_start, peak_end).

    Times are UTC; "local hour" is taken as the hour component of the instant.
    We scan each whole minute of the half-open window.
    """
    if end <= start:
        return False
    cur = start
    while cur < end:
        if peak_start_hour <= cur.hour < peak_end_hour:
            return True
        cur = cur + timedelta(minutes=1)
    return False


def lane_subtotal(res, rate_card, party_package):
    """reservation_quote (SCAFFOLD §1.3 reservation_quote)."""
    mode = res["pricing_mode"]
    if mode == "PER_GAME":
        # per_game_cents * game_count * bowler_count; duration & peak ignored.
        return rate_card["per_game_cents"] * res["game_count"] * res["bowler_count"]

    # PER_HOUR
    block_minutes = rate_card["block_minutes"]
    dur = duration_minutes(res)
    blocks = math.ceil(dur / block_minutes) if dur > 0 else 0

    # Party-package bundled free blocks
    if party_package is not None:
        included_lane_hours = party_package.get("included_lane_hours", 0)
        free_blocks = math.ceil((included_lane_hours * 60) / block_minutes) if included_lane_hours > 0 else 0
        billable_blocks = max(0, blocks - free_blocks)
    else:
        billable_blocks = blocks

    start = _dt(res["start_at"])
    end = _dt(res["end_at"])
    peak = _is_peak(start, end, rate_card["peak_start_hour"], rate_card["peak_end_hour"])
    if peak:
        hourly_rate = Decimal(rate_card["per_hour_cents"]) * Decimal(rate_card["peak_multiplier_bps"]) / Decimal(BPS_DENOM)
    else:
        hourly_rate = Decimal(rate_card["per_hour_cents"])

    return round_half_up(Decimal(billable_blocks) * hourly_rate)


def package_subtotal(res, party_package):
    """party_package_total (SCAFFOLD §1.3). Exact cents, no rounding."""
    if party_package is None:
        return 0
    guest_count = res.get("guest_count", 0)
    billable_guests = max(0, min(guest_count, party_package["max_guests"]) - party_package["included_guests"])
    return party_package["base_cents"] + billable_guests * party_package["extra_guest_cents"]


def food_line_total(unit_cents, quantity, taxable):
    """Per food line: gross + round_half_up(tax) (PRD §3.4 food_total)."""
    gross = unit_cents * quantity
    tax = bps_apply_round(gross, SALES_TAX_BPS) if taxable else 0
    return gross + tax


def food_subtotal(reservation_id):
    """Round-per-line THEN sum (PRD §3.4 — pinned order)."""
    total = 0
    for line in db.food_lines.values():
        if line["reservation_id"] == reservation_id:
            total += line["line_total_cents"]
    return total


def rental_subtotal(reservation_id):
    """Sum unit_price_snapshot * quantity over OPEN rental lines (PRD §3.4)."""
    total = 0
    for line in db.rental_lines.values():
        if line["reservation_id"] == reservation_id and line["status"] == "OPEN":
            total += line["unit_price_snapshot"] * line["quantity"]
    return total


def deposit_amount(quoted_total_cents, rate_card):
    """held_deposit_cents = round_half_up(quoted_total * deposit_pct_bps / 10000)."""
    return bps_apply_round(quoted_total_cents, rate_card["deposit_pct_bps"])


def cancellation_refund(held_deposit_cents, start_at, cancelled_at):
    """Refund by notice tier (PRD §3.6 / SCAFFOLD cancellation_refund)."""
    start = parse_datetime(start_at)
    notice_minutes = int((start - cancelled_at).total_seconds() // 60)
    if notice_minutes >= FULL_REFUND_NOTICE_MINUTES:
        return held_deposit_cents
    if notice_minutes >= PARTIAL_REFUND_NOTICE_MINUTES:
        return bps_apply_round(held_deposit_cents, PARTIAL_REFUND_BPS)
    return 0


def recompute_subtotals(res):
    """Recompute all four subtotals + quoted_total + held_deposit on a reservation.

    Mutates res in place. Does NOT touch version/customer ledger — the caller
    owns ledger reconciliation. Returns the new held_deposit (based on the
    pinned rate card and deposit_pct_bps).
    """
    rate_card = db.rate_cards.get(res["rate_card_id"])
    party_package = db.party_packages.get(res.get("party_package_id")) if res.get("party_package_id") else None

    res["lane_subtotal_cents"] = lane_subtotal(res, rate_card, party_package)
    res["package_subtotal_cents"] = package_subtotal(res, party_package)
    res["food_subtotal_cents"] = food_subtotal(res["id"])
    res["rental_subtotal_cents"] = rental_subtotal(res["id"])
    res["quoted_total_cents"] = (
        res["lane_subtotal_cents"]
        + res["package_subtotal_cents"]
        + res["food_subtotal_cents"]
        + res["rental_subtotal_cents"]
    )
    return deposit_amount(res["quoted_total_cents"], rate_card)


# --- Temporal conflict arbitration (PRD §2.9) -----------------------------

# A reservation is "blocking" while it still holds its window. Per PRD §2.9 a
# blocking reservation is one that has not been cancelled, expired, no-showed,
# or completed away. Waitlisted/draft reservations do not hold a window.
BLOCKING_STATES = {"HELD", "CONFIRMED", "CHECKED_IN"}


def _intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: touching back-to-back is allowed."""
    return a_start < b_end and b_start < a_end


def lane_conflict(lane_id, start, end, exclude_reservation_id=None):
    """True if [start, end) overlaps a blocking reservation on the same lane."""
    for r in db.reservations.values():
        if r["id"] == exclude_reservation_id:
            continue
        if r.get("resource_kind") != "LANE" or r.get("lane_id") != lane_id:
            continue
        if r["status"] not in BLOCKING_STATES:
            continue
        rs = parse_datetime(r["start_at"])
        re = parse_datetime(r["end_at"])
        if _intervals_overlap_halfopen(start, end, rs, re):
            return True
    # League nights also block lanes they reserve (PRD §3.8)
    for n in db.league_nights.values():
        if n["status"] != "SCHEDULED":
            continue
        if lane_id not in n.get("reserved_lane_ids", []):
            continue
        ns = parse_datetime(n["start_at"])
        ne = parse_datetime(n["end_at"])
        if _intervals_overlap_halfopen(start, end, ns, ne):
            return True
    return False


def bay_conflict(bay_id, start, end, exclude_reservation_id=None):
    """Bay overlap with cleanup buffer (PRD §2.9).

    Conflict when the new window starts before a prior booking's end + buffer,
    or ends after a following booking's start - buffer, on the same bay.
    """
    bay = db.bays.get(bay_id)
    buffer_min = bay["cleanup_buffer_minutes"] if bay else 0
    buf = timedelta(minutes=buffer_min)
    for r in db.reservations.values():
        if r["id"] == exclude_reservation_id:
            continue
        if r.get("resource_kind") != "BAY" or r.get("bay_id") != bay_id:
            continue
        if r["status"] not in BLOCKING_STATES:
            continue
        rs = parse_datetime(r["start_at"])
        re = parse_datetime(r["end_at"])
        # New window must sit entirely outside [rs - buf, re + buf).
        # Conflict if new.start < prior.end + buffer AND new.end > prior.start - buffer.
        if start < re + buf and end > rs - buf:
            return True
    return False


def has_conflict(res, exclude_self=True):
    """Resource-appropriate conflict check for a reservation's current window."""
    start = parse_datetime(res["start_at"])
    end = parse_datetime(res["end_at"])
    exclude = res["id"] if exclude_self else None
    if res["resource_kind"] == "LANE":
        return lane_conflict(res["lane_id"], start, end, exclude_reservation_id=exclude)
    return bay_conflict(res["bay_id"], start, end, exclude_reservation_id=exclude)
