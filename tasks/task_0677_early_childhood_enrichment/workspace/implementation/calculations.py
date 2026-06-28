"""Calculation rules (scaffold 1.3 / PRD 3.6, 3.7, 3.9).

All money is integer cents; intermediate fractions are rounded half-up. The
load-bearing ordering throughout billing is sum-of-rounded (round each child
line first, then sum), NEVER round-of-sum.
"""
from decimal import Decimal

from util import round_half_up, months_between

MEMBERSHIP_BASE_FEE_CENTS = {"CORE": 3000, "PLUS": 5000, "UNLIMITED": 9000}
CYCLE_DAYS = 30
CREDIT_TTL_DAYS = 60

SIBLING_RATE_2 = Decimal("0.10")
SIBLING_RATE_3 = Decimal("0.15")
SIBLING_RATE_4_PLUS = Decimal("0.20")


def sibling_rate(n):
    """Tiered sibling-discount rate by billed-child count n (PRD 3.6)."""
    if n <= 1:
        return Decimal("0.00")
    if n == 2:
        return SIBLING_RATE_2
    if n == 3:
        return SIBLING_RATE_3
    return SIBLING_RATE_4_PLUS  # n >= 4


def child_line_full(tuition_cents):
    """Full-cycle per-child line: program tuition, no proration (rounding no-op)."""
    return round_half_up(tuition_cents)


def child_line_prorated(tuition_cents, active_days):
    """Mid-cycle prorated per-child line (PRD 3.6 mid_cycle_prorated variant).

    round_half_up(tuition_cents * active_days / CYCLE_DAYS) per line, before
    summing. active_days is clamped to [0, 30] by the caller.
    """
    return round_half_up(Decimal(tuition_cents) * Decimal(active_days) / Decimal(CYCLE_DAYS))


def active_days_for(cycle_start_dt, cycle_end_dt):
    """Whole-day active count = floor((cycle_end - current_cycle_start)/1 day),
    clamped to [0, 30] (PRD 3.6).
    """
    elapsed = cycle_end_dt - cycle_start_dt
    days = int(elapsed.total_seconds() // 86400)
    if days < 0:
        days = 0
    if days > CYCLE_DAYS:
        days = CYCLE_DAYS
    return days


def compute_invoice(base_fee_cents, child_lines, billed_child_count):
    """Assemble subtotal, sibling discount, and total from rounded child lines.

    child_lines: list of already-rounded per-child tuition cents (one per
    distinct billed child). billed_child_count: Family.child_count used for the
    sibling-discount tier.

    Returns (subtotal_cents, sibling_discount_cents, total_cents).
    """
    tuition_only = sum(child_lines)
    subtotal = base_fee_cents + tuition_only

    rate = sibling_rate(billed_child_count)
    raw_discount = round_half_up(Decimal(tuition_only) * rate)
    if child_lines:
        cap_cents = max(child_lines)  # one full child line cap
        discount = min(raw_discount, cap_cents)
    else:
        discount = 0
    total = max(0, subtotal - discount)
    return subtotal, discount, total


def redemption_residual(issued_tuition_cents, target_tuition_cents):
    """residual_owed_cents = max(0, target_program.tuition - credit issued value)."""
    return max(0, target_tuition_cents - issued_tuition_cents)


def age_eligible(birth_date, session_start_dt, min_age_months, max_age_months):
    """Half-open age band: min <= age_months < max (PRD 3.4 / calc threshold)."""
    age = months_between(birth_date, session_start_dt)
    return min_age_months <= age < max_age_months
