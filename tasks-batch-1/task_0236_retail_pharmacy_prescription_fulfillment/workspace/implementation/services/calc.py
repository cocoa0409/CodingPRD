"""Pure calculation rules (scaffold §1.3). All money in integer cents."""
from decimal import Decimal, ROUND_HALF_UP

from clock import parse_iso

# PDMP weighted-scoring constants (§1.3 pdmp_risk_score).
FILL_WEIGHT = 10
PRESCRIBER_WEIGHT = 15
REVIEW_THRESHOLD = 30
BLOCK_THRESHOLD = 60
PDMP_LOOKBACK_DAYS = 90

# DUR high-dose threshold (§1.3 dur_severity_rollup).
HIGH_DOSE_UNITS_PER_DAY = 4

# Refill-too-soon default (also defaulted on plan creation).
DEFAULT_THRESHOLD_PCT = 0.80

SEVERITY_RANK = {"NONE": 0, "MINOR": 1, "MODERATE": 2, "SEVERE": 3}
RANK_SEVERITY = {v: k for k, v in SEVERITY_RANK.items()}


def round_half_up_cents(amount):
    """Round a Decimal/number to a whole integer of cents, half-up."""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def coinsurance_raw(allowed_amount_per_unit, quantity, dispensing_fee, copay_pct):
    """Allowed total then a single half-up round of (total * copay_pct)."""
    allowed_total = allowed_amount_per_unit * quantity + dispensing_fee
    raw_copay = round_half_up_cents(Decimal(allowed_total) * Decimal(str(copay_pct)))
    return allowed_total, raw_copay


def provisional_copay(allowed_amount_per_unit, quantity, dispensing_fee,
                      copay_pct, copay_min, copay_max):
    """Forward-looking estimate: per-fill cap (§1.3 provisional_copay_estimate)."""
    _, raw_copay = coinsurance_raw(
        allowed_amount_per_unit, quantity, dispensing_fee, copay_pct
    )
    return min(max(raw_copay, copay_min), copay_max)


def final_copay(allowed_amount_per_unit, quantity, dispensing_fee,
                copay_pct, copay_min, copay_max, prior_oop):
    """Chronological adjudicated copay: cumulative annual cap.

    Returns (final_copay_cents, plan_paid_cents).
    """
    allowed_total, raw_copay = coinsurance_raw(
        allowed_amount_per_unit, quantity, dispensing_fee, copay_pct
    )
    this_fill_copay = max(raw_copay, copay_min)
    remaining_cap = max(copay_max - prior_oop, 0)
    fc = min(this_fill_copay, remaining_cap)
    plan_paid = allowed_total - fc
    return fc, plan_paid


def floor_days_between(earlier_iso, later_iso):
    """Whole calendar days (floored) between two ISO timestamps, later - earlier."""
    earlier = parse_iso(earlier_iso)
    later = parse_iso(later_iso)
    delta = later - earlier
    return delta.days  # timedelta.days already floors toward negative infinity


def refill_required_days(prior_days_supply, threshold_pct):
    """floor(prior_days_supply * threshold_pct)."""
    import math
    return int(math.floor(prior_days_supply * threshold_pct))


def severity_max(severities):
    """Max severity by rank; NONE when empty."""
    if not severities:
        return "NONE"
    return RANK_SEVERITY[max(SEVERITY_RANK[s] for s in severities)]


def pdmp_risk_score(controlled_fill_count, distinct_prescriber_count):
    score = (controlled_fill_count * FILL_WEIGHT
             + max(distinct_prescriber_count - 1, 0) * PRESCRIBER_WEIGHT)
    return score


def pdmp_flag_for_score(score):
    if score >= BLOCK_THRESHOLD:
        return "BLOCKED"
    if score >= REVIEW_THRESHOLD:
        return "REVIEW"
    return "CLEAR"
