"""Regulatory arithmetic (§1.3 / PRD §2.6, §3.1, §3.5, §3.6, §3.7, §3.8).

All money is integer cents. Two rounding conventions only:
  - derived money is FLOORED (ROUND_DOWN) at each named division step, in order;
  - fractions are ROUND_HALF_UP to a fixed number of decimal places.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

# §1.3 constants
HH_FACTOR_BP = {1: 7000, 2: 8000, 3: 9000, 4: 10000, 5: 10800, 6: 11600}
RENT_PCT = 30
MONTHS = 12
OVER_INCOME_BP = 14000
CREDIT_BP = {"NINE_PERCENT": 900, "FOUR_PERCENT": 400}
AMI_PCT = {"AMI_40": 40, "AMI_50": 50, "AMI_60": 60, "AMI_80": 80}
INSPECTION_BUFFER_DAYS = 7
PASS_THRESHOLD = 60

LOW_INCOME_DESIGNATIONS = {"AMI_40", "AMI_50", "AMI_60", "AMI_80"}


def _floor(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_DOWN))


def _round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def imputed_household_size(bedroom_count):
    """Studio (0)->1; otherwise round_half_up(bedroom_count * 1.5), never below 1."""
    if bedroom_count == 0:
        return 1
    raw = (Decimal(bedroom_count) * Decimal("1.5")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return max(1, int(raw))


def unit_income_and_rent_limits(ami_cents, ami_designation, bedroom_count, utility_allowance_cents):
    """Return (income_limit_cents, gross_rent_ceiling_cents, net_max_rent_cents).

    MARKET units carry no limits (caller handles None). Floors at each named step,
    in pinned order: income_limit -> gross_rent_ceiling -> net_max_rent.
    """
    pct = AMI_PCT[ami_designation]
    hh = imputed_household_size(bedroom_count)
    factor_bp = HH_FACTOR_BP[hh]
    income_limit = _floor(
        Decimal(ami_cents) * Decimal(pct) / Decimal(100) * Decimal(factor_bp) / Decimal(10000)
    )
    gross_rent_ceiling = _floor(
        Decimal(income_limit) * Decimal(RENT_PCT) / Decimal(100) / Decimal(MONTHS)
    )
    net_max_rent = gross_rent_ceiling - utility_allowance_cents
    return income_limit, gross_rent_ceiling, net_max_rent


def over_income_threshold(income_limit_cents):
    """floor(income_limit * 140/100)."""
    return _floor(Decimal(income_limit_cents) * Decimal(140) / Decimal(100))


def building_applicable_fraction_and_credit(building, units):
    """Compute (applicable_fraction, qualified_basis_cents, annual_credit_cents).

    units: all Unit records under the building. Numerator filtered to
    is_low_income_counted==true (li_status in {QUALIFIED, OVER_INCOME}).
    Evaluation order pinned: fraction -> qualified_basis -> credit.
    """
    total_units = building["total_residential_units"]
    total_sqft = building["total_residential_sqft"]
    li_units = [u for u in units if u.get("is_low_income_counted")]
    li_count = len(li_units)
    li_sqft = sum(u["sqft"] for u in li_units)

    unit_fraction = _round4(Decimal(li_count) / Decimal(total_units))
    floor_space_fraction = _round4(Decimal(li_sqft) / Decimal(total_sqft))
    applicable_fraction = min(unit_fraction, floor_space_fraction)

    qualified_basis = _floor(Decimal(building["eligible_basis_cents"]) * applicable_fraction)
    credit_bp = CREDIT_BP[building["credit_type"]]
    annual_credit = _floor(Decimal(qualified_basis) * Decimal(credit_bp) / Decimal(10000))
    return applicable_fraction, qualified_basis, annual_credit


def provisional_fraction(building, units):
    """Forward-looking: all designated (non-MARKET) units treated as qualified full year."""
    total_units = building["total_residential_units"]
    designated = sum(1 for u in units if u["ami_designation"] != "MARKET")
    return _round4(Decimal(designated) / Decimal(total_units))


def credit_from_fraction(building, fraction):
    """annual_credit = floor(eligible_basis * fraction * credit_bp / 10000)."""
    credit_bp = CREDIT_BP[building["credit_type"]]
    return _floor(
        Decimal(building["eligible_basis_cents"]) * Decimal(fraction) * Decimal(credit_bp) / Decimal(10000)
    )


def final_chronological_fraction(building, monthly_qualified_units):
    """Average of 12 month-end qualified fractions, round_half_up to 4 decimals."""
    total_units = building["total_residential_units"]
    total = Decimal(0)
    for m in monthly_qualified_units:
        total += Decimal(m) / Decimal(total_units)
    return _round4(total / Decimal(MONTHS))


def minimum_set_aside_satisfied(minimum_set_aside, all_units, total_units):
    """Design-level set-aside test over unit COUNTS (§1.3 minimum_set_aside_test)."""
    if total_units <= 0:
        return False
    if minimum_set_aside == "TWENTY_FIFTY":
        designated = sum(1 for u in all_units if u["ami_designation"] in ("AMI_40", "AMI_50"))
        return designated * 100 >= 25 * total_units
    if minimum_set_aside == "FORTY_SIXTY":
        designated = sum(
            1 for u in all_units if u["ami_designation"] in ("AMI_40", "AMI_50", "AMI_60")
        )
        return designated * 100 >= 40 * total_units
    if minimum_set_aside == "AVERAGE_INCOME":
        li = [u for u in all_units if u["ami_designation"] in LOW_INCOME_DESIGNATIONS]
        if len(li) < 1:
            return False
        total_pct = sum(AMI_PCT[u["ami_designation"]] for u in li)
        avg = _round2(Decimal(total_pct) / Decimal(len(li)))
        return avg <= Decimal("60.00")
    return False


def inspection_score_and_result(deduction_points, has_exigent_health_safety):
    """score = max(0, 100 - sum(deductions)); FAIL if exigent OR score < 60."""
    score = 100 - sum(deduction_points)
    if score < 0:
        score = 0
    result = "FAIL" if (has_exigent_health_safety or score < PASS_THRESHOLD) else "PASS"
    return score, result
