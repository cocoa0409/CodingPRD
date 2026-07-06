"""Pure calculation rules (SCAFFOLD §1.3 / PRD §2.8, §3.5, §3.8).

All money in integer cents. Decimal + ROUND_HALF_UP everywhere; never float for
money. Hour quantities carried to 2 decimals; utilization & match score to 4.
"""
import math
from decimal import Decimal, ROUND_HALF_UP


def _d(x):
    return Decimal(str(x))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)  # 10^-places
    return _d(value).quantize(q, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round to whole cents, half-up; return int."""
    return int(round_half_up(value, 0))


def round_hours2(value):
    """Hours to 2 decimals, half-up; return float."""
    return float(round_half_up(value, 2))


# --- calc B: time_entry_billable (ceil to 15-min grid) ----------------------
def billable_hours(raw_minutes):
    """raw_minutes -> hours, rounded UP to next 0.25h (15-min grid).

    1 min -> 0.25 ; 15 min -> 0.25 ; 16 min -> 0.5
    """
    quarter_hours = math.ceil(raw_minutes / 15)
    return float(_d(quarter_hours) * _d("0.25"))


# --- calc A: cycle_balance --------------------------------------------------
def cycle_balance(granted, rolled_in, approved_billable_hours):
    """Sum of APPROVED billable_hours -> consumed/available/overage (2dp)."""
    consumed = round_half_up(sum(_d(h) for h in approved_billable_hours), 2) if approved_billable_hours else _d("0.00")
    bank = _d(granted) + _d(rolled_in)
    available = bank - consumed
    if available < 0:
        available = _d("0")
    overage = consumed - bank
    if overage < 0:
        overage = _d("0")
    return (
        round_hours2(consumed),
        round_hours2(available),
        round_hours2(overage),
    )


# --- calc D: rollover_carry -------------------------------------------------
def rollover_carry(granted, rolled_in, consumed, rollover_cap_hours):
    """Unused (floored 0) capped by rollover_cap_hours; 2dp half-up."""
    bank = _d(granted) + _d(rolled_in)
    unused = bank - _d(consumed)
    if unused < 0:
        unused = _d("0")
    carry = min(unused, _d(rollover_cap_hours))
    return round_hours2(carry)


# --- calc E: va_match_score -------------------------------------------------
W_SKILL = _d("0.5")
W_RATING = _d("0.3")
W_CAPACITY = _d("0.2")


def va_match_score(required_count, covered_count, rating, weekly_capacity_hours):
    """Weighted score to 4 decimals, half-up."""
    skill_coverage = _d(covered_count) / _d(max(1, required_count))
    rating_norm = _d(rating) / _d("5.0")
    cap = _d(weekly_capacity_hours) / _d("40.0")
    capacity_norm = min(_d("1.0"), cap)
    score = W_SKILL * skill_coverage + W_RATING * rating_norm + W_CAPACITY * capacity_norm
    return float(round_half_up(score, 4))
