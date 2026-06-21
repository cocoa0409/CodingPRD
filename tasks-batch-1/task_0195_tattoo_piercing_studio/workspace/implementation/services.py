"""Business-logic calculations and cross-entity helpers (PRD §3, SCAFFOLD §1.3).

All monetary amounts are whole integers of cents. Decimal + ROUND_HALF_UP is
used wherever the PRD specifies half-up rounding.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import db

# ---- Constants (SCAFFOLD §1.3 / PRD §2.8, §3) ----
DEPOSIT_RATE = Decimal("0.20")
TAX_RATE = Decimal("0.08")
INCREMENT_MINUTES = 15
SUPPLY_FEE_CENTS = 3500
FREE_WINDOW_DAYS = 90
TOUCHUP_FLAT_FEE_CENTS = 6000
MIN_AGE_YEARS = 18

# Reliability scoring weights
CANCEL_WEIGHT = 5
RESCHED_WEIGHT = 10
SCORE_FLOOR = 0


def _round_half_up(value):
    """Round a Decimal to the nearest whole integer, ties away from zero (up)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# calculations.required_deposit  (PRD §3.6)
# ---------------------------------------------------------------------------
def required_deposit(pricing_mode, piece_price_cents, hourly_rate_cents, estimated_minutes):
    if pricing_mode == "PIECE":
        estimate_cents = piece_price_cents
    else:  # HOURLY
        whole_hours = math.ceil(estimated_minutes / 60)
        estimate_cents = whole_hours * hourly_rate_cents
    raw = Decimal(estimate_cents) * DEPOSIT_RATE
    # Single rounding step, applied to the full multiplied estimate (sum-then-round):
    # round UP to the next whole dollar (100 cents).
    dollars = math.ceil(raw / Decimal(100))
    return dollars * 100


# ---------------------------------------------------------------------------
# calculations.session_gross  (PRD §3.9)
# ---------------------------------------------------------------------------
def session_gross(appointment):
    if appointment["pricing_mode"] == "PIECE":
        return appointment["piece_price_cents"]
    # HOURLY: bill in 15-minute increments, rounding actual time UP.
    actual = appointment["actual_minutes"]
    increments = math.ceil(actual / INCREMENT_MINUTES)
    per_increment = appointment["hourly_rate_cents"] // 4  # divisible by 4 by validation
    return increments * per_increment


# ---------------------------------------------------------------------------
# calculations.session_final_balance  (PRD §3.9)
# ---------------------------------------------------------------------------
def session_final_balance(gross_cents, deposit_paid_cents):
    pre_tax_balance = max(0, gross_cents - deposit_paid_cents)
    tax_cents = _round_half_up(Decimal(pre_tax_balance) * TAX_RATE)
    return pre_tax_balance + tax_cents


# ---------------------------------------------------------------------------
# calculations.artist_payout  (PRD §3.9)
# ---------------------------------------------------------------------------
def artist_payout(gross_cents, commission_pct):
    commission = _round_half_up(Decimal(gross_cents) * Decimal(str(commission_pct)))
    artist_cut = max(0, commission - SUPPLY_FEE_CENTS)
    studio_cut = gross_cents - artist_cut
    return {
        "artist_cut_cents": artist_cut,
        "studio_cut_cents": studio_cut,
        "gross_cents": gross_cents,
    }


# ---------------------------------------------------------------------------
# calculations.artist_reliability_score  (PRD §3.9)
# ---------------------------------------------------------------------------
def strict_reliability_score(artist):
    cancel_penalty = CANCEL_WEIGHT * artist.get("artist_cancel_count", 0)
    resched_penalty = RESCHED_WEIGHT * artist.get("late_reschedule_count", 0)
    return max(SCORE_FLOOR, 100 - cancel_penalty - resched_penalty)


def lenient_reliability_score(artist):
    cancel_penalty = CANCEL_WEIGHT * artist.get("artist_cancel_count", 0)
    return max(SCORE_FLOOR, 100 - cancel_penalty)


def recompute_reliability(artist):
    artist["reliability_score"] = strict_reliability_score(artist)


# ---------------------------------------------------------------------------
# calculations.touchup_fee  (PRD §3.10)
# ---------------------------------------------------------------------------
def touchup_fee(parent_completed_dt, request_clock_dt, aftercare_acknowledged):
    delta_seconds = (request_clock_dt - parent_completed_dt).total_seconds()
    days_since = math.floor(delta_seconds / 86400)
    if days_since <= FREE_WINDOW_DAYS and aftercare_acknowledged:
        return 0
    return TOUCHUP_FLAT_FEE_CENTS


# ---------------------------------------------------------------------------
# Age computation (PRD §3.2) — whole-year age as of a reference date.
# ---------------------------------------------------------------------------
def whole_year_age(date_of_birth, as_of_date):
    """date_of_birth: 'YYYY-MM-DD' string; as_of_date: aware/naive date.
    Returns whole-year age (int), or None if dob unparseable."""
    try:
        parts = date_of_birth.split("-")
        by, bm, bd = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, AttributeError, IndexError):
        return None
    ay, am, ad = as_of_date.year, as_of_date.month, as_of_date.day
    age = ay - by
    if (am, ad) < (bm, bd):
        age -= 1
    return age


# ---------------------------------------------------------------------------
# Deposit cascade helpers (PRD §2.5, §3.8, §3.9)
# ---------------------------------------------------------------------------
def confirmed_deposits_for(appointment_id):
    return [d for d in db.deposits.values()
            if d["appointment_id"] == appointment_id and d["status"] == "CONFIRMED"]


def forfeit_deposits(appointment):
    """Move every CONFIRMED deposit to FORFEITED and recompute deposit_paid_cents
    to 0. Each touched deposit independently bumps its version/updated_at."""
    for d in confirmed_deposits_for(appointment["id"]):
        d["status"] = "FORFEITED"
        db.touch(d)
    appointment["deposit_paid_cents"] = 0


def apply_deposits(appointment):
    """Move every CONFIRMED deposit to APPLIED (on completion). deposit_paid_cents
    is preserved (the money is consumed by the session, not forfeited)."""
    for d in confirmed_deposits_for(appointment["id"]):
        d["status"] = "APPLIED"
        db.touch(d)
