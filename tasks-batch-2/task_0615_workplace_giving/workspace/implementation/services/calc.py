"""Calculation rules (PRD §3 / SCAFFOLD §1.3).

All money is integer cents. floor is applied at every rate multiplication step
(PRD §2.5); where sub-amounts are summed, each is floored first.
"""
from services.common import floor_mul

ROUNDUP_DOLLAR_CENTS = 100
MINUTES_PER_HOUR = 60
MAX_DEDUCTION_FRACTION = 0.20


def donation_amount_breakdown(program, base_amount_cents):
    """calc donation_amount_breakdown — pinned order (PRD §3.5).

    Returns (roundup_increment_cents, subtotal_cents, processing_fee_cents,
    total_charged_cents).
    """
    # (1) roundup increment
    if program.get("roundup_enabled"):
        rem = base_amount_cents % ROUNDUP_DOLLAR_CENTS
        roundup = 0 if rem == 0 else (ROUNDUP_DOLLAR_CENTS - rem)
    else:
        roundup = 0
    # (2) subtotal
    subtotal = base_amount_cents + roundup
    # (3) processing fee from the SUBTOTAL tier
    if subtotal >= program["processing_fee_tier_threshold_cents"]:
        rate = program["processing_fee_low_rate"]
    else:
        rate = program["processing_fee_high_rate"]
    fee = floor_mul(subtotal, rate)
    # (4) total
    total = subtotal + fee
    return roundup, subtotal, fee, total


def raw_match(program, base_amount_cents):
    """Raw match before annual-cap clamp (PRD §3.6)."""
    if program.get("tiered_matching_enabled"):
        ceiling = program["tier_1_ceiling_cents"]
        t1 = min(base_amount_cents, ceiling)
        t2 = max(0, base_amount_cents - ceiling)
        # floor each tier BEFORE summing
        return floor_mul(t1, program["tier_1_rate"]) + floor_mul(t2, program["tier_2_rate"])
    return floor_mul(base_amount_cents, program["match_ratio"])


def clamp_match(program, raw, consumed_ytd_cents):
    """Clamp raw match to remaining annual cap (PRD §3.6)."""
    remaining = program["annual_match_cap_cents"] - consumed_ytd_cents
    return max(0, min(raw, remaining))


def dollars_for_doers_grant(program, minutes, dfd_consumed_ytd_cents):
    """calc dollars_for_doers_grant (PRD §3.7). Returns (raw, clamped)."""
    # floor on the (minutes/60*rate) product
    raw = floor_mul(minutes, program["dfd_rate_cents_per_hour"] / MINUTES_PER_HOUR)
    remaining = program["dfd_annual_cap_cents"] - dfd_consumed_ytd_cents
    clamped = max(0, min(raw, remaining))
    return raw, clamped


def payroll_ceiling_cents(employee):
    """ceiling = floor(floor(annual_salary/12) * 0.20) (PRD §3.5)."""
    monthly = employee["annual_salary_cents"] // 12
    return floor_mul(monthly, MAX_DEDUCTION_FRACTION)
