"""The eight calculations (PRD 2.7 and section 3).

Every monetary figure is an integer number of cents.  Wherever a proportion is
applied the quotient is rounded half up -- a fractional part of exactly one
half rounds away from zero to the larger magnitude -- and the arithmetic is
performed with decimal.Decimal so no binary floating point ever touches money.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from db import (
    ADMIN_RETENTION_TIER_BPS,
    BACKGROUND_POINTS_ADJUDICATED_PASS,
    BACKGROUND_POINTS_CLEARED,
    COVERAGE_POINTS_CAP,
    DISPUTED_REFERENCE_PENALTY,
    EXPERIENCE_POINTS_CAP,
    EXPERIENCE_POINTS_PER_YEAR,
    FROZEN_INVOICE_STATUSES,
    PENALTY_CAP_CENTS,
    PENALTY_FLOOR_CENTS,
    POACHING_RATE_TIERS_BPS,
    REFERENCE_POINTS_CAP,
    RELATIONSHIP_WEIGHTS,
)
from timeutil import month_index


def round_half_up_div(numerator, denominator):
    """Integer division rounded half up (away from zero on an exact half)."""
    if denominator == 0:
        return 0
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, bps):
    """amount * bps / 10000 rounded half up."""
    return round_half_up_div(Decimal(amount_cents) * Decimal(bps), Decimal(10000))


# ---------------------------------------------------------------------------
# 1. Fee schedule band resolution (PRD 2.7 / 3.2)
# ---------------------------------------------------------------------------
def resolve_fee_schedule(role_type, compensation_cents):
    """Half-open band matching: floor <= comp and (ceiling is null or comp <
    ceiling).  The winner is the greatest effective_from; the earliest
    created_at breaks a tie.  No rounding occurs here."""
    candidates = []
    for row in db.store.fee_schedules.values():
        if row["status"] != "ACTIVE":
            continue
        if row["role_type"] != role_type:
            continue
        if compensation_cents < row["comp_band_floor_cents"]:
            continue
        ceiling = row["comp_band_ceiling_cents"]
        if ceiling is not None and compensation_cents >= ceiling:
            continue
        candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["effective_from"], "",), reverse=False)
    best = None
    for row in candidates:
        if best is None:
            best = row
            continue
        if row["effective_from"] > best["effective_from"]:
            best = row
        elif row["effective_from"] == best["effective_from"]:
            if (row["created_at"], row["_seq"]) < (best["created_at"], best["_seq"]):
                best = row
    return best


def bands_overlap(floor_a, ceiling_a, floor_b, ceiling_b):
    """Half-open [floor, ceiling) comparison; a null ceiling is unbounded.  A
    band whose ceiling equals another's floor does not overlap."""
    hi_a = Decimal("Infinity") if ceiling_a is None else Decimal(ceiling_a)
    hi_b = Decimal("Infinity") if ceiling_b is None else Decimal(ceiling_b)
    return Decimal(floor_a) < hi_b and Decimal(floor_b) < hi_a


# ---------------------------------------------------------------------------
# 2. Placement fee, two variants (PRD 2.7 / 3.6)
# ---------------------------------------------------------------------------
def provisional_fee_cents(first_year_compensation_cents, fee_percent_bps):
    """One rounding applied to the aggregate."""
    return apply_bps(first_year_compensation_cents, fee_percent_bps)


FINAL_FEE_COMPONENT_ORDER = (
    "base_salary_cents",
    "guaranteed_bonus_cents",
    "accommodation_imputed_cents",
    "overtime_allowance_cents",
)


def final_fee_cents(components, fee_percent_bps):
    """Four independent roundings summed, in the fixed component order base
    salary, guaranteed bonus, accommodation imputed, overtime allowance."""
    total = 0
    for name in FINAL_FEE_COMPONENT_ORDER:
        total += apply_bps(components[name], fee_percent_bps)
    return total


# ---------------------------------------------------------------------------
# 3. Milestone waterfall allocation (PRD 2.7 / 3.7)
# ---------------------------------------------------------------------------
def allocate_milestones(fee_cents, milestones):
    """Frozen rows keep their amounts; the open partition shares the remainder
    pro rata by weight_bps and the last open row absorbs the exact remainder so
    that the non-voided amounts always sum to fee_cents."""
    ordered = sorted(milestones, key=lambda m: m["sequence_no"])
    frozen_total = 0
    open_rows = []
    for row in ordered:
        status = row["invoice_status"]
        if status == "VOIDED":
            continue
        if status in FROZEN_INVOICE_STATUSES:
            frozen_total += row["amount_cents"]
        else:
            open_rows.append(row)
    if not open_rows:
        return {}
    remaining = fee_cents - frozen_total
    open_weight_total = sum(r["weight_bps"] for r in open_rows)
    assigned = {}
    running = 0
    for row in open_rows[:-1]:
        amount = round_half_up_div(
            Decimal(remaining) * Decimal(row["weight_bps"]), Decimal(open_weight_total)
        )
        assigned[row["id"]] = amount
        running += amount
    assigned[open_rows[-1]["id"]] = remaining - running
    return assigned


# ---------------------------------------------------------------------------
# 4. Reference coverage interval merge (PRD 2.7 / 3.3)
# ---------------------------------------------------------------------------
def reference_coverage(verified_rows):
    """Closed inclusive month intervals merged on overlap or adjacency.
    Returns (total_covered_months, longest_contiguous_months)."""
    intervals = []
    for row in verified_rows:
        start = month_index(row["employment_start_month"])
        end = month_index(row["employment_end_month"])
        intervals.append((start, end))
    if not intervals:
        return 0, 0
    intervals.sort()
    merged = []
    current_start, current_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= current_end + 1:
            # overlapping, or adjacent with a zero month gap
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    lengths = [end - start + 1 for start, end in merged]
    return sum(lengths), max(lengths)


def periods_overlap(start_a, end_a, start_b, end_b):
    """Closed inclusive month interval intersection."""
    return start_a <= end_b and start_b <= end_a


# ---------------------------------------------------------------------------
# 5. Candidate vetting scores (PRD 2.7 / 3.3)
# ---------------------------------------------------------------------------
def vetting_figures(candidate, reference_rows, background_rows):
    verified = [r for r in reference_rows if r["status"] == "VERIFIED"]
    disputed_count = len([r for r in reference_rows if r["status"] == "DISPUTED"])
    coverage_months, longest = reference_coverage(verified)

    experience_points = min(
        candidate["years_experience"] * EXPERIENCE_POINTS_PER_YEAR, EXPERIENCE_POINTS_CAP
    )
    reference_points = min(
        sum(RELATIONSHIP_WEIGHTS[r["relationship_type"]] for r in verified), REFERENCE_POINTS_CAP
    )
    coverage_points = min(coverage_months, COVERAGE_POINTS_CAP)

    statuses = {r["status"] for r in background_rows}
    if "CLEARED" in statuses:
        background_points = BACKGROUND_POINTS_CLEARED
    elif "ADJUDICATED_PASS" in statuses:
        background_points = BACKGROUND_POINTS_ADJUDICATED_PASS
    else:
        background_points = 0

    screening_score = experience_points + reference_points + coverage_points
    placement_ready_score = max(
        screening_score + background_points - DISPUTED_REFERENCE_PENALTY * disputed_count, 0
    )
    return {
        "verified_reference_count": len(verified),
        "reference_coverage_months": coverage_months,
        "longest_contiguous_months": longest,
        "screening_score": screening_score,
        "placement_ready_score": placement_ready_score,
    }


# ---------------------------------------------------------------------------
# 6. Refund proration (PRD 2.7 / 3.8)
# ---------------------------------------------------------------------------
def refund_proration(fee_cents, guarantee_window_days, start_date, separation_date):
    """Five ordered steps; the administrative tier is keyed on the prorated
    gross refund, never on the full fee."""
    elapsed_days = (separation_date - start_date).days
    unused_days = max(guarantee_window_days - elapsed_days, 0)
    gross_refund_cents = round_half_up_div(
        Decimal(fee_cents) * Decimal(unused_days), Decimal(guarantee_window_days)
    )
    tier_bps = _tier_for(gross_refund_cents, ADMIN_RETENTION_TIER_BPS)
    admin_retained_cents = apply_bps(gross_refund_cents, tier_bps)
    net_refund_cents = gross_refund_cents - admin_retained_cents
    return {
        "elapsed_days": elapsed_days,
        "unused_days": unused_days,
        "gross_refund_cents": gross_refund_cents,
        "admin_retained_cents": admin_retained_cents,
        "net_refund_cents": net_refund_cents,
    }


def _tier_for(amount, tiers):
    for bound, bps in tiers:
        if bound is None or amount < bound:
            return bps
    return tiers[-1][1]


# ---------------------------------------------------------------------------
# 7. Non-solicitation penalty (PRD 2.7 / 3.9)
# ---------------------------------------------------------------------------
def non_solicitation_penalty(base_cents, prior_substantiated_count):
    """Regressive tier keyed on the pre-multiplier base, then the repeat
    multiplier, then the floor and cap clamp."""
    rate_bps = _tier_for(base_cents, POACHING_RATE_TIERS_BPS)
    rated_cents = apply_bps(base_cents, rate_bps)
    multiplied = rated_cents * (1 + prior_substantiated_count)
    return min(max(multiplied, PENALTY_FLOOR_CENTS), PENALTY_CAP_CENTS)


# ---------------------------------------------------------------------------
# 8. Ledger running balance (PRD 2.7 / 3.7)
# ---------------------------------------------------------------------------
def fold_balance(entries):
    total = 0
    for row in sorted(entries, key=lambda r: r["sequence_no"]):
        total += row["signed_amount_cents"]
    return total
