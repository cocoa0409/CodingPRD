"""Numeric constants and pure-Python reference calculators.

Every constant here is stated verbatim in the PRD; every helper reproduces a
PRD calculation in the PRD's own pinned rounding order so expected values can
be derived rather than hand-copied.
"""

from typing import Iterable, List, Tuple

# ---------------------------------------------------------------------------
# Scales (PRD §2.6)
# ---------------------------------------------------------------------------
BPS_SCALE = 10000
PPM_SCALE = 1000000
CENTI_SCALE = 100

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Family maturity (PRD §3.2)
# ---------------------------------------------------------------------------
MATURITY_MIN_HISTORY_MONTHS = 12
MATURITY_MIN_EXPOSURE_UNITS = 5000

# ---------------------------------------------------------------------------
# Reserve posture (PRD §2.10)
# ---------------------------------------------------------------------------
POSTURE_CONSTRAINED_BPS = 10000
POSTURE_ELEVATED_BPS = 8000

# ---------------------------------------------------------------------------
# Disclosure threshold (PRD §3.1 / §3.9)
# ---------------------------------------------------------------------------
SIGNIFICANT_EXPOSURE_THRESHOLD_CENTS = 50000000

# ---------------------------------------------------------------------------
# Accrual calculations (PRD §3.3)
# ---------------------------------------------------------------------------
LIFETIME_DEVELOPMENT_FACTOR_BPS = 25000
ANALOG_ENGINEERING_WEIGHT_BPS = 6000
ANALOG_OBSERVED_WEIGHT_BPS = 4000

# ---------------------------------------------------------------------------
# Adequacy review tiers (PRD §3.4)
# ---------------------------------------------------------------------------
ADEQUACY_REDUNDANT_MAX_BPS = 8000
ADEQUACY_SUFFICIENT_MAX_BPS = 12000
ADEQUACY_DEFICIENT_MAX_BPS = 15000
ADEQUACY_TREND_REDUNDANT_BPS = -1000
ADEQUACY_TREND_SUFFICIENT_BPS = 0
ADEQUACY_TREND_DEFICIENT_BPS = 1500
ADEQUACY_TREND_SEVERE_BPS = 3000

# ---------------------------------------------------------------------------
# Remedy cost model / field actions (PRD §3.5)
# ---------------------------------------------------------------------------
FIELD_LABOR_RATE_CENTS_PER_HOUR = 9500
FIELD_ACTION_BUFFER_DAYS = 30

# ---------------------------------------------------------------------------
# Service contract recognition (PRD §3.6)
# ---------------------------------------------------------------------------
CLAIMS_PATTERN_TIERS: Tuple[Tuple[int, int], ...] = (
    (2500, 1000),
    (5000, 3000),
    (7500, 6000),
)
CLAIMS_PATTERN_FINAL_BPS = 10000

# ---------------------------------------------------------------------------
# Supplier collectability (PRD §3.7)
# ---------------------------------------------------------------------------
BASE_RATING_BY_CREDIT = {
    "AAA": "HIGH",
    "BBB": "MEDIUM",
    "CCC": "LOW",
    "D": "IMPAIRED",
}
DOWNGRADE_LADDER: Tuple[str, ...] = ("HIGH", "MEDIUM", "LOW", "IMPAIRED")
REALIZATION_HOLD_BPS = 7500
REALIZATION_ONE_NOTCH_BPS = 4000
COLLECTABILITY_WEIGHT_BPS = {
    "HIGH": 9000,
    "MEDIUM": 6000,
    "LOW": 2500,
    "IMPAIRED": 0,
}

# ---------------------------------------------------------------------------
# Liability reserve (PRD §3.8)
# ---------------------------------------------------------------------------
LAG_FACTOR_BPS_PER_MONTH = 1200
LAG_FACTOR_CEILING_BPS = 6000
IBNR_CAP_BPS = 15000
EXPOSURE_FLOOR_CENTS_PER_UNIT = 25
MIN_REPORTING_LAG_MONTHS = 0
MAX_REPORTING_LAG_MONTHS = 24
MIN_SEVERITY_TREND_BPS = -5000
MAX_SEVERITY_TREND_BPS = 10000


# ---------------------------------------------------------------------------
# Rounding (PRD §2.6): round half away from zero.
# ---------------------------------------------------------------------------
def round_half_away(numerator: int, denominator: int) -> int:
    """Divide and round to the nearest integer, halves going away from zero."""
    if denominator == 0:
        raise ValueError("denominator must be non-zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


# ---------------------------------------------------------------------------
# Reference calculators
# ---------------------------------------------------------------------------
def historical_rate_accrual(
    units_shipped: int, per_mode: Iterable[Tuple[int, int]]
) -> Tuple[int, int, int]:
    """Per-mode round-then-sum HISTORICAL_RATE arithmetic (PRD §3.3).

    `per_mode` yields (observed_claim_count, cost_per_claim_cents) pairs in
    `mode_code` ascending order. Returns
    (expected_claim_rate_ppm, cost_per_claim_basis_cents, gross_ultimate_cents).
    """
    rate_sum = 0
    ultimate_sum = 0
    gross = 0
    for claim_count, cost_per_claim in per_mode:
        rate_ppm = round_half_away(claim_count * PPM_SCALE, units_shipped)
        ultimate = round_half_away(
            rate_ppm * units_shipped * LIFETIME_DEVELOPMENT_FACTOR_BPS, PPM_SCALE * BPS_SCALE
        )
        rate_sum += rate_ppm
        ultimate_sum += ultimate
        gross += ultimate * cost_per_claim
    basis = 0 if ultimate_sum == 0 else round_half_away(gross, ultimate_sum)
    return rate_sum, basis, gross


def analog_blend_accrual(
    units_shipped: int,
    engineering_estimate_rate_ppm: int,
    analog_claim_count: int,
    analog_exposure_units: int,
    standard_cost_per_claim_cents: int,
) -> Tuple[int, int, int]:
    """Single-rounding ANALOG_BLEND arithmetic (PRD §3.3)."""
    observed = (
        0
        if analog_exposure_units == 0
        else round_half_away(analog_claim_count * PPM_SCALE, analog_exposure_units)
    )
    developed = round_half_away(observed * LIFETIME_DEVELOPMENT_FACTOR_BPS, BPS_SCALE)
    blended = round_half_away(
        engineering_estimate_rate_ppm * ANALOG_ENGINEERING_WEIGHT_BPS
        + developed * ANALOG_OBSERVED_WEIGHT_BPS,
        BPS_SCALE,
    )
    ultimate = round_half_away(blended * units_shipped, PPM_SCALE)
    return blended, standard_cost_per_claim_cents, ultimate * standard_cost_per_claim_cents


def accrued_amount(gross_ultimate_cents: int, paid_to_date_cents: int) -> int:
    """Gross ultimate less paid-to-date, floored at zero (PRD §3.3)."""
    return max(0, gross_ultimate_cents - paid_to_date_cents)


def per_unit_expected_cents(
    parts_cost_cents: int,
    labor_hours_centi: int,
    admin_cost_cents: int,
    expected_take_rate_bps: int,
) -> int:
    """Remedy option per-unit expected cost in the PRD's pinned order (PRD §3.5)."""
    labor = round_half_away(labor_hours_centi * FIELD_LABOR_RATE_CENTS_PER_HOUR, CENTI_SCALE)
    gross = parts_cost_cents + labor + admin_cost_cents
    return round_half_away(gross * expected_take_rate_bps, BPS_SCALE)


def specific_accrual_cents(per_unit: int, affected_unit_count: int) -> int:
    """Round per unit first, then multiply by the population (PRD §3.5)."""
    return per_unit * affected_unit_count


def claims_pattern_fraction_bps(months_elapsed: int, term_months: int) -> int:
    """Front-loaded CLAIMS_PATTERN cumulative fraction (PRD §3.6)."""
    elapsed_bps = round_half_away(months_elapsed * BPS_SCALE, term_months)
    for upper, fraction in CLAIMS_PATTERN_TIERS:
        if elapsed_bps <= upper:
            return fraction
    return CLAIMS_PATTERN_FINAL_BPS


def reserve_posture(balance_cents: int, reserve_cap_cents: int) -> str:
    """Utilisation-ratio posture derivation (PRD §2.10)."""
    ratio = round_half_away(max(0, balance_cents) * BPS_SCALE, reserve_cap_cents)
    if ratio >= POSTURE_CONSTRAINED_BPS:
        return "CONSTRAINED"
    if ratio >= POSTURE_ELEVATED_BPS:
        return "ELEVATED"
    return "NORMAL"


def realization_bps(realized_recovery_cents: int, written_off_recovery_cents: int) -> int:
    """Supplier realization ratio (PRD §3.7)."""
    denominator = realized_recovery_cents + written_off_recovery_cents
    if denominator == 0:
        return BPS_SCALE
    return round_half_away(realized_recovery_cents * BPS_SCALE, denominator)


def collectability_rating(
    credit_rating: str, closed_recovery_count: int, realization: int
) -> str:
    """Base rating plus the downgrade ladder (PRD §3.7)."""
    base = BASE_RATING_BY_CREDIT[credit_rating]
    if closed_recovery_count == 0 or realization >= REALIZATION_HOLD_BPS:
        return base
    notches = 1 if realization >= REALIZATION_ONE_NOTCH_BPS else 2
    ladder: List[str] = list(DOWNGRADE_LADDER)
    index = min(ladder.index(base) + notches, len(ladder) - 1)
    return ladder[index]


def contractual_ceiling_cents(
    annual_purchase_volume_cents: int, contractual_recovery_cap_bps: int
) -> int:
    """Supplier-level annual recovery ceiling (PRD §3.7)."""
    return round_half_away(annual_purchase_volume_cents * contractual_recovery_cap_bps, BPS_SCALE)


def expected_value_recovery_cents(
    asserted_amount_cents: int, rating: str, ceiling_cents: int
) -> int:
    """EXPECTED_VALUE valuation: round the weighting, then apply the ceiling."""
    weighted = round_half_away(asserted_amount_cents * COLLECTABILITY_WEIGHT_BPS[rating], BPS_SCALE)
    return min(weighted, ceiling_cents)


def contractual_floor_recovery_cents(settled_amount_cents: int, ceiling_cents: int) -> int:
    """CONTRACTUAL_FLOOR valuation: the lesser of ceiling and settlement."""
    return min(ceiling_cents, settled_amount_cents)


def liability_reserve_figures(
    reported_claim_count: int,
    asserted_case_reserve_cents: int,
    reporting_lag_months: int,
    severity_trend_bps: int,
    units_sold_lifetime: int,
):
    """Full liability-reserve chain with the cap-then-floor clamp (PRD §3.8).

    Returns (avg_case_severity_cents, lag_factor_bps, ibnr_claim_count,
    ibnr_reserve_cents, total_liability_reserve_cents).
    """
    avg_severity = (
        0
        if reported_claim_count == 0
        else round_half_away(asserted_case_reserve_cents, reported_claim_count)
    )
    lag_factor = min(reporting_lag_months * LAG_FACTOR_BPS_PER_MONTH, LAG_FACTOR_CEILING_BPS)
    ibnr_count = round_half_away(reported_claim_count * lag_factor, BPS_SCALE)
    trended_severity = round_half_away(avg_severity * (BPS_SCALE + severity_trend_bps), BPS_SCALE)
    raw = ibnr_count * trended_severity
    cap = round_half_away(asserted_case_reserve_cents * IBNR_CAP_BPS, BPS_SCALE)
    floor = units_sold_lifetime * EXPOSURE_FLOOR_CENTS_PER_UNIT
    ibnr_reserve = max(min(raw, cap), floor)
    return (
        avg_severity,
        lag_factor,
        ibnr_count,
        ibnr_reserve,
        asserted_case_reserve_cents + ibnr_reserve,
    )
