"""Calculation rules (SCAFFOLD §1.3). Integer cents, decimal-safe rounding."""
from decimal import Decimal

import db
from helpers import round_half_up, ceil_div

# Skill ladder ordering
SKILL_ORDER = {"BEGINNER": 0, "INTERMEDIATE": 1, "ADVANCED": 2, "PROFESSIONAL": 3}

# calculations.booking_charge constants
SKILL_SURCHARGE = {"BEGINNER": 0, "INTERMEDIATE": 500, "ADVANCED": 1200, "PROFESSIONAL": 2500}

# calculations.cancellation_refund constants
CANCELLATION_FEE_CENTS = 300

# calculations.member_reliability_score constants
NO_SHOW_PENALTY = 25
LATE_CANCEL_PENALTY = 10
BLOCK_THRESHOLD = 40


def skill_at_least(have, need):
    return SKILL_ORDER[have] >= SKILL_ORDER[need]


# --------------------------------------------------------------------------
# prep_cost_per_seat — MODE (b): round per line THEN sum (pinned order)
# --------------------------------------------------------------------------
def prep_cost_per_seat(session):
    lines = [il for il in db.ingredient_lines.values() if il["session_id"] == session["id"]]
    lines.sort(key=lambda il: il["_seq"])  # created_at ASC
    ingredient_per_seat = 0
    for line in lines:
        line_cost = round_half_up(Decimal(str(line["qty_per_seat"])) * Decimal(line["unit_cost_cents"]))
        ingredient_per_seat += line_cost
    template = db.templates[session["template_id"]]
    station_per_seat = ceil_div(template["station_fixed_cost_cents"], session["planned_seats"])
    return ingredient_per_seat + station_per_seat


def refresh_prep_cost(session):
    session["prep_cost_per_seat_cents"] = prep_cost_per_seat(session)


# --------------------------------------------------------------------------
# booking_charge — MODE (a): tiered pricing (pinned evaluation order)
# --------------------------------------------------------------------------
def booking_charge(session, template, seats_requested):
    if session["event_type"] == "PRIVATE":
        return session["private_event_fee_cents"]
    skill_surcharge_per_seat = SKILL_SURCHARGE[template["skill_level"]]
    line_base = template["base_price_cents"] * seats_requested
    skill_total = skill_surcharge_per_seat * seats_requested
    subtotal = line_base + skill_total
    if seats_requested <= 2:
        pct = Decimal("0.00")
    elif seats_requested <= 5:
        pct = Decimal("0.05")
    elif seats_requested <= 9:
        pct = Decimal("0.10")
    else:
        pct = Decimal("0.15")
    discount = round_half_up(Decimal(subtotal) * pct)
    return subtotal - discount


# --------------------------------------------------------------------------
# cancellation_refund — forward-looking tiers
# --------------------------------------------------------------------------
def refund_tier_pct(hours_before):
    if hours_before >= 168:
        return Decimal("1.00")
    elif hours_before >= 72:
        return Decimal("0.75")
    elif hours_before >= 24:
        return Decimal("0.50")
    return Decimal("0.00")


def cancellation_refund_provisional(booking, session):
    """Base refund using the hours_before tier at the moment of cancel."""
    start_at = session["_start_at_dt"]
    current = db.current_utc()
    hours_before = (start_at - current).total_seconds() / 3600.0
    pct = refund_tier_pct(hours_before)
    gross = round_half_up(Decimal(booking["charge_cents"]) * pct)
    return max(0, gross - CANCELLATION_FEE_CENTS)


def cancellation_refund_final(booking):
    """FINAL: if seat refilled, full charge minus fee; else provisional stands."""
    if booking.get("refilled_from_waitlist"):
        return max(0, booking["charge_cents"] - CANCELLATION_FEE_CENTS)
    return booking["refund_cents"]


def is_within_late_window(session):
    """True if current_utc is within 24h before start_at (late-cancel window)."""
    start_at = session["_start_at_dt"]
    current = db.current_utc()
    hours_before = (start_at - current).total_seconds() / 3600.0
    return hours_before < 24


# --------------------------------------------------------------------------
# member_reliability_score — provisional vs final differ only by which strikes
# count; here we always count SETTLED strikes, and the caller controls timing
# by flipping PENDING -> SETTLED before invoking the FINAL recompute.
# --------------------------------------------------------------------------
def recompute_reliability(member):
    settled = [
        r for r in db.no_show_records.values()
        if r["member_id"] == member["id"] and r["settlement_status"] == "SETTLED"
    ]
    no_show_count = sum(1 for r in settled if r["kind"] == "NO_SHOW")
    late_cancel_count = sum(1 for r in settled if r["kind"] == "LATE_CANCEL")
    score = 100 - (NO_SHOW_PENALTY * no_show_count) - (LATE_CANCEL_PENALTY * late_cancel_count)
    score = max(0, min(100, score))
    member["no_show_count"] = no_show_count
    member["late_cancel_count"] = late_cancel_count
    member["reliability_score"] = score
    member["booking_status"] = "BLOCKED" if score < BLOCK_THRESHOLD else "GOOD_STANDING"
    return score


# --------------------------------------------------------------------------
# substitution_surcharge
# --------------------------------------------------------------------------
def substitution_surcharge(alternate_unit_cost_cents, line, booking):
    delta_per_unit = max(0, alternate_unit_cost_cents - line["unit_cost_cents"])
    return round_half_up(
        Decimal(delta_per_unit) * Decimal(str(line["qty_per_seat"])) * Decimal(booking["seats_requested"])
    )
