"""Calculation engine — SCAFFOLD §1.3 / PRD §2.8 + §3.

Money is integer cents. Where a fractional cent (or fractional unit) arises
before storage, we round half up. Rounding discipline (PRD §2.8): each charge
component is independently round-half-up to integer cents FIRST, then summed
(round-per-component-then-sum). Use Decimal everywhere — never float for money.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# ---- Constants (verbatim from SCAFFOLD §1.3) ----
DENSITY_LBS_PER_CF = 7

CRATE_FEE_CENTS = 9500

RATE_PER_100_CENTS = 110          # $1.10 per $100 of declared value
MIN_PREMIUM_CENTS = 7500          # $75 floor
DEDUCTIBLE_CREDIT = {0: Decimal("0.00"), 25000: Decimal("0.10"),
                     50000: Decimal("0.18"), 100000: Decimal("0.30")}
ALLOWED_DEDUCTIBLES = {0, 25000, 50000, 100000}
MIN_VALUATION_PER_LB_CENTS = 600  # $6.00/lb declared-value floor

CWT_RATE_CENTS = {"0_250": 9000, "251_750": 14000,
                  "751_1500": 21000, "1501_plus": 29000}
FUEL_PCT = Decimal("0.085")
STAIR_FEE_CENTS = 7500
LONG_CARRY_FEE_CENTS = 9000
CF_PER_CREW_HOUR = 45
MIN_HOURS = Decimal("3.0")
TRAVEL_HOURS = Decimal("0.5")
HOURLY_RATE_CENTS = {2: 14000, 3: 19000, 4: 24000, 5: 28500}

BINDING_TOLERANCE_PCT = Decimal("0.10")

DAILY_RATE_CENTS = 4200
FREE_SIT_DAYS = 3
WAREHOUSE_HANDLING_CENTS = 11000

RELEASED_RATE_CENTS_PER_LB = 60   # $0.60 per pound per article

SECONDS_PER_DAY = 86400


def round_half_up(value):
    """Round a Decimal/number half up to the nearest integer (cents)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _d(x):
    return Decimal(str(x))


# =============================================================================
# cubic_feet_rollup (SCAFFOLD §1.3 / PRD §3.2)
# =============================================================================
def cubic_feet_rollup(items):
    """items: list of SurveyItem dicts (quantity, cubic_feet_each).

    total_cubic_feet kept exact; estimated_weight_lbs = round_half_up(
    total_cubic_feet * DENSITY_LBS_PER_CF).
    """
    total = Decimal("0")
    for it in items:
        total += _d(it["quantity"]) * _d(it["cubic_feet_each"])
    estimated_weight = round_half_up(total * DENSITY_LBS_PER_CF)
    # Return total as a JSON-friendly number; kept exact via Decimal math.
    total_num = float(total) if total != total.to_integral_value() else int(total)
    return total_num, estimated_weight, total


# =============================================================================
# packing_total (SCAFFOLD §1.3 / PRD §3.3)
# =============================================================================
def packing_total(crate_count, packing_lines):
    subtotal = Decimal("0")
    for line in packing_lines:
        subtotal += _d(line["quantity"]) * _d(line["unit_price_cents"])
    total = subtotal + _d(crate_count) * _d(CRATE_FEE_CENTS)
    return round_half_up(total)


# =============================================================================
# valuation_premium (SCAFFOLD §1.3 / PRD §3.4)
# =============================================================================
def valuation_premium(valuation_coverage, declared_value_cents, deductible_cents):
    if valuation_coverage == "RELEASED":
        return 0
    # FULL_VALUE: round base, floor at MIN, apply deductible credit, round again.
    rate_figure = round_half_up(_d(declared_value_cents) / _d(10000) * _d(RATE_PER_100_CENTS))
    base_cents = max(MIN_PREMIUM_CENTS, rate_figure)
    credit_pct = DEDUCTIBLE_CREDIT[deductible_cents]
    premium = round_half_up(_d(base_cents) * (Decimal("1") - credit_pct))
    return premium


# =============================================================================
# estimate_total (SCAFFOLD §1.3 / PRD §3.4)
# =============================================================================
def _accessorial(stair_flights, long_carry_units):
    return round_half_up(_d(stair_flights) * _d(STAIR_FEE_CENTS)
                         + _d(long_carry_units) * _d(LONG_CARRY_FEE_CENTS))


def cwt_tier(distance_miles):
    d = distance_miles
    if d <= 250:
        return "0_250"
    if d <= 750:
        return "251_750"
    if d <= 1500:
        return "751_1500"
    return "1501_plus"


def crew_size_by_cf(total_cubic_feet):
    cf = _d(total_cubic_feet)
    if cf <= 300:
        return 2
    if cf <= 600:
        return 3
    if cf <= 1000:
        return 4
    return 5


def ceil_to_quarter(hours):
    # round up to next quarter-hour
    quarters = (_d(hours) / Decimal("0.25")).quantize(Decimal("1"), rounding=ROUND_CEILING)
    return quarters * Decimal("0.25")


def weight_driven_components(service_type, weight_lbs, total_cubic_feet, distance_miles):
    """Compute (linehaul_cents, labor_cents, fuel_surcharge_cents) for the given
    weight / volume / distance. For LOCAL, total_cubic_feet drives crew/hours;
    for LONG_HAUL, weight_lbs drives the cwt tariff.
    """
    if service_type == "LONG_HAUL":
        cwt = _d(weight_lbs) / Decimal("100")  # hundredweight, exact
        rate_cents = CWT_RATE_CENTS[cwt_tier(distance_miles)]
        linehaul = round_half_up(cwt * _d(rate_cents))
        labor = 0
        fuel = round_half_up(_d(linehaul) * FUEL_PCT)
        return linehaul, labor, fuel
    # LOCAL
    crew_size = crew_size_by_cf(total_cubic_feet)
    raw_hours = _d(total_cubic_feet) / _d(CF_PER_CREW_HOUR) / _d(crew_size)
    billable_hours = max(MIN_HOURS, ceil_to_quarter(raw_hours))
    hourly_rate = HOURLY_RATE_CENTS[crew_size]
    labor = round_half_up(_d(hourly_rate) * billable_hours)
    travel = round_half_up(_d(hourly_rate) * TRAVEL_HOURS)
    linehaul = 0
    fuel = travel  # LOCAL stores its travel fee in the fuel field slot
    return linehaul, labor, fuel


def estimate_total(move_job, survey, estimate, packing_total_cents):
    """Compute every charge component + estimate_total_cents.

    Returns a dict of component fields. Uses estimated_weight_lbs and
    total_cubic_feet from the linked survey, the MoveJob accessorials, and
    the estimate's coverage/valuation inputs.
    """
    weight = survey["estimated_weight_lbs"]
    total_cf = survey["total_cubic_feet"]

    accessorial = _accessorial(move_job["stair_flights"], move_job["long_carry_units"])
    premium = valuation_premium(
        estimate["valuation_coverage"],
        estimate["declared_value_cents"],
        estimate["deductible_cents"],
    )
    linehaul, labor, fuel = weight_driven_components(
        move_job["service_type"], weight, total_cf, move_job["distance_miles"]
    )

    total = (linehaul + labor + fuel + packing_total_cents + premium + accessorial)
    return {
        "linehaul_cents": linehaul,
        "labor_cents": labor,
        "fuel_surcharge_cents": fuel,
        "packing_cents": packing_total_cents,
        "valuation_premium_cents": premium,
        "accessorial_cents": accessorial,
        "estimate_total_cents": total,
    }


# =============================================================================
# final_charge_reconciliation (SCAFFOLD §1.3 / PRD §3.7)
# =============================================================================
def final_charge_reconciliation(move_job, survey, estimate,
                                actual_weight_lbs, actual_cubic_feet, addendum_present):
    """Return final_charge_cents at delivery."""
    if estimate["binding_type"] == "BINDING":
        re_rate = (
            addendum_present
            and actual_cubic_feet is not None
            and _d(actual_cubic_feet) > _d(survey["total_cubic_feet"]) * (Decimal("1") + BINDING_TOLERANCE_PCT)
        )
        if re_rate:
            # Re-run the full pricing engine with W = actual weight.
            linehaul, labor, fuel = weight_driven_components(
                move_job["service_type"], actual_weight_lbs,
                survey["total_cubic_feet"], move_job["distance_miles"]
            )
            return (linehaul + labor + fuel
                    + estimate["packing_cents"]
                    + estimate["valuation_premium_cents"]
                    + estimate["accessorial_cents"])
        # locked
        return estimate["estimate_total_cents"]
    # NON_BINDING: re-rate weight-driven components at actual weight; carry over
    # packing + valuation + accessorial unchanged.
    linehaul, labor, fuel = weight_driven_components(
        move_job["service_type"], actual_weight_lbs,
        survey["total_cubic_feet"], move_job["distance_miles"]
    )
    return (linehaul + labor + fuel
            + estimate["packing_cents"]
            + estimate["valuation_premium_cents"]
            + estimate["accessorial_cents"])


# =============================================================================
# sit_accrual (SCAFFOLD §1.3 / PRD §3.8)
# =============================================================================
def sit_accrual(intake_date, release_date):
    """intake_date / release_date are datetime objects. Returns
    (billable_days, sit_charge_cents).

    raw_days = ceil((release - intake) in days); billable = max(0, raw - FREE);
    charge = round_half_up(billable*DAILY + 2*WAREHOUSE_HANDLING).
    """
    delta_seconds = (release_date - intake_date).total_seconds()
    raw_days = int(_d(delta_seconds / SECONDS_PER_DAY).quantize(Decimal("1"), rounding=ROUND_CEILING))
    billable_days = max(0, raw_days - FREE_SIT_DAYS)
    charge = round_half_up(_d(billable_days) * _d(DAILY_RATE_CENTS)
                           + 2 * _d(WAREHOUSE_HANDLING_CENTS))
    return billable_days, charge


# =============================================================================
# claim_settlement (SCAFFOLD §1.3 / PRD §3.10)
# =============================================================================
def claim_settlement(coverage_snapshot, deductible_cents, items):
    if coverage_snapshot == "RELEASED":
        total = Decimal("0")
        for it in items:
            total += _d(it["item_weight_lbs"]) * _d(RELEASED_RATE_CENTS_PER_LB)
        return round_half_up(total)
    # FULL_VALUE
    gross = 0
    for it in items:
        gross += min(it["repair_cost_cents"], it["replacement_value_cents"])
    return max(0, gross - deductible_cents)
