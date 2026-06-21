"""Calculation rules (scaffold §1.3 / PRD §3.9-§3.10, §3.12).

All money is integer cents. Ratios/fractions are rounded to 4 dp, round-half-up.
Never use float for the rounding decisions — use decimal.Decimal.
"""
from decimal import Decimal, ROUND_HALF_UP

# Constants (scaffold §1.3).
MIN_LOSS_RATIO = Decimal("0.20")          # below this, no residual benefit
PRESUMED_TOTAL_RATIO = Decimal("0.80")    # at/above this, treat as total disability
MAX_COLA_MULTIPLIER = Decimal("2.0")      # COLA compounding caps benefit at 2x base
OFFSET_FLOOR_CENTS = 0                     # net benefit never goes negative
DAYS_PER_MONTH = 30
PROOF_INTERVAL_MONTHS = 3                  # continued-disability proof cadence

_Q4 = Decimal("0.0001")


def round4(value) -> Decimal:
    """Round to 4 decimal places, round-half-up."""
    return Decimal(value).quantize(_Q4, rounding=ROUND_HALF_UP)


def round_cents(value) -> int:
    """Round a (possibly fractional) cent figure to the nearest whole cent, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator: int, denominator: int) -> int:
    """Integer ceiling division for non-negative numerator."""
    q = numerator // denominator
    if numerator % denominator != 0:
        q += 1
    return q


def income_loss_ratio(pre_disability_cents: int, current_cents: int) -> Decimal:
    """(pre - current)/pre, floored at 0, rounded to 4 dp (scaffold IncomeReport)."""
    if pre_disability_cents <= 0:
        return Decimal("0.0000")
    raw = (Decimal(pre_disability_cents) - Decimal(current_cents)) / Decimal(pre_disability_cents)
    if raw < 0:
        raw = Decimal("0")
    return round4(raw)


def claim_window_months(disability_onset_month: int, elimination_period_days: int,
                        occupation_definition: str, own_occ_window_months: int):
    """Return (elimination_satisfied_month, own_occ_expiry_month) (scaffold claim_window_months)."""
    elimination_satisfied_month = disability_onset_month + ceil_div(elimination_period_days, DAYS_PER_MONTH)
    if occupation_definition == "OWN_OCC":
        own_occ_expiry_month = elimination_satisfied_month + own_occ_window_months
    else:
        own_occ_expiry_month = elimination_satisfied_month
    return elimination_satisfied_month, own_occ_expiry_month


def residual_benefit_factor(claimed_disability_type: str, R, occupation_definition: str,
                            coverage_month: int, own_occ_expiry_month: int) -> Decimal:
    """benefit_fraction for a coverage_month (scaffold residual_benefit_factor).

    TOTAL -> 1.0 always.
    RESIDUAL: dual variant.
      presumptive_total when OWN_OCC and coverage_month < own_occ_expiry_month.
      proportionate otherwise.
    R is the income_loss_ratio of the report in effect (Decimal); caller resolves it.
    """
    if claimed_disability_type == "TOTAL":
        return Decimal("1.0000")

    R = Decimal(R)

    presumptive = (occupation_definition == "OWN_OCC" and coverage_month < own_occ_expiry_month)
    if presumptive:
        # presumptive_total variant: any qualifying loss pays in full.
        if R >= MIN_LOSS_RATIO:
            return Decimal("1.0000")
        return Decimal("0.0000")

    # proportionate variant (default).
    if R < MIN_LOSS_RATIO:
        return Decimal("0.0000")
    if R >= PRESUMED_TOTAL_RATIO:
        return Decimal("1.0000")
    return round4(R)


def cola_multiplier(cola_rider: bool, cola_annual_rate, coverage_month: int,
                    elimination_satisfied_month: int) -> Decimal:
    """COLA multiplier for a coverage_month (scaffold gross_benefit_cents)."""
    years_elapsed = (coverage_month - elimination_satisfied_month) // 12
    if not cola_rider or years_elapsed <= 0:
        return Decimal("1.0")
    base = Decimal("1") + Decimal(str(cola_annual_rate))
    compounded = base ** years_elapsed
    if compounded > MAX_COLA_MULTIPLIER:
        return MAX_COLA_MULTIPLIER
    return compounded


def gross_benefit_cents(monthly_benefit_cents: int, cola_rider: bool, cola_annual_rate,
                        coverage_month: int, elimination_satisfied_month: int,
                        benefit_fraction) -> int:
    """COLA-adjusted gross with two independent half-up roundings (scaffold gross_benefit_cents)."""
    mult = cola_multiplier(cola_rider, cola_annual_rate, coverage_month, elimination_satisfied_month)
    cola_adjusted_cents = round_cents(Decimal(monthly_benefit_cents) * mult)
    gross = round_cents(Decimal(cola_adjusted_cents) * Decimal(benefit_fraction))
    return gross


def net_benefit_cents(gross: int, offset_applied: int) -> int:
    """max(OFFSET_FLOOR_CENTS, gross - offset_applied) (scaffold net_benefit_cents)."""
    return max(OFFSET_FLOOR_CENTS, gross - offset_applied)
