"""Calculation rules. All decimal arithmetic is exact; money is integer cents."""
from decimal import Decimal

from util import ceil_cents, ceil_int, days, dec, rhu

# ------------------------------------------------------------------ constants
STEWARDSHIP_PAYOUT_RATE = Decimal("0.0375")
STEWARDSHIP_ADMIN_FEE_PCT = Decimal("0.0150")
STEWARDSHIP_INTERIM_GATE_PCT = Decimal("0.25")
MIN_PERFORMANCE_BOND_CENTS = 25000000

IRT_QUORUM_MIN = 3
MAX_REVISION_ROUNDS = 2

MAX_REMEDIAL_ROUNDS = 3
REMEDIAL_DUE_DAYS = 365

RESERVATION_HOLD_DAYS = 30
MILESTONE_WINDOW_BUFFER_DAYS = 365

QUARTER_DAYS = 90
QUARTER_WEIGHTS = (Decimal("0.10"), Decimal("0.20"), Decimal("0.30"), Decimal("0.40"))
DEMAND_NORMALIZER_CREDITS = Decimal("10.00")
DEMAND_INDEX_CEILING = Decimal("3.0")
DEMAND_SENSITIVITY = Decimal("0.10")
DEMAND_ADJUSTMENT_CAP_PCT = Decimal("0.30")

BASE_PRICE_CENTS_PER_CREDIT = {
    "RIVERINE": Decimal("4250000"),
    "DEPRESSIONAL": Decimal("3800000"),
    "SLOPE": Decimal("3600000"),
    "FLATS": Decimal("3300000"),
    "ESTUARINE": Decimal("5100000"),
}
TIER1_MAX_CREDITS = Decimal("5.00")
TIER2_MAX_CREDITS = Decimal("10.00")
TIER1_MULTIPLIER = Decimal("1.000")
TIER2_MULTIPLIER = Decimal("0.950")
TIER3_MULTIPLIER = Decimal("0.900")
SECONDARY_SERVICE_AREA_PREMIUM_PCT = Decimal("0.12")
STEWARDSHIP_SURCHARGE_PCT = Decimal("0.08")
PRICE_CAP_MULTIPLIER = Decimal("1.15")
EXECUTION_REPRICE_CAP_MULTIPLIER = Decimal("1.10")

ATTAINMENT_FULL_RELEASE_MIN = Decimal("0.95")
ATTAINMENT_PARTIAL_RELEASE_MIN = Decimal("0.85")
PARTIAL_RELEASE_FACTOR = Decimal("0.90")
FULL_RELEASE_FACTOR = Decimal("1.00")
COMPLIANCE_PARTIAL_MIN = Decimal("0.85")

FORECAST_HORIZON_QUARTERS = 40

HGM_CLASSES = tuple(sorted(BASE_PRICE_CENTS_PER_CREDIT.keys()))
STRATUM_CODES = ("UPLAND_BUFFER", "EMERGENT_MARSH", "FORESTED_WETLAND", "SCRUB_SHRUB",
                 "OPEN_WATER")
STANDARD_CODES = ("HYDROPERIOD_DAYS", "INVASIVE_COVER_PCT", "NATIVE_COVER_PCT",
                  "STEM_DENSITY_PER_ACRE")
MILESTONE_CODES = ("INSTRUMENT_EXECUTION", "CONSTRUCTION_COMPLETE", "PERF_YEAR_3",
                   "PERF_YEAR_5", "PERF_YEAR_10")
CONSTRUCTION_MILESTONE_CODES = ("INSTRUMENT_EXECUTION", "CONSTRUCTION_COMPLETE")


# ------------------------------------------------------- work plan credit yield
def work_plan_credit_yield(strata):
    """Round PER STRATUM, then sum (pinned order); strata iterated by code ASC."""
    total = Decimal("0.00")
    for stratum in sorted(strata, key=lambda s: s["stratum_code"]):
        total += rhu(dec(stratum["acres"]) * dec(stratum["lift_factor"]), 2)
    return rhu(total, 2)


# ----------------------------------------------- stewardship endowment (cents)
def stewardship_endowment_requirement(annual_stewardship_cost_cents):
    """Pinned single-pass capitalisation: no fixed-point iteration."""
    base = ceil_cents(dec(annual_stewardship_cost_cents) / STEWARDSHIP_PAYOUT_RATE)
    fee = rhu(base * STEWARDSHIP_ADMIN_FEE_PCT, 0)
    return int(base + fee)


def stewardship_interim_gate(required_cents):
    return int(rhu(dec(required_cents) * STEWARDSHIP_INTERIM_GATE_PCT, 0))


def stewardship_gate_for_milestone(milestone_code, required_cents):
    if milestone_code == "PERF_YEAR_10":
        return int(required_cents)
    return stewardship_interim_gate(required_cents)


# ----------------------------------------------------- milestone credit release
def provisional_release_credits(total_authorized_credits, release_pct):
    return rhu(dec(total_authorized_credits) * dec(release_pct), 2)


def final_release_credits(provisional, attainment_factor):
    """The FINAL variant rounds the ALREADY-ROUNDED provisional value."""
    return rhu(dec(provisional) * dec(attainment_factor), 2)


# ----------------------------------------------------- service area demand index
def _quarter_bounds(now):
    bounds = []
    for index in range(4):
        start = now - days(QUARTER_DAYS * (4 - index))
        end = now - days(QUARTER_DAYS * (3 - index))
        bounds.append((start, end))
    return bounds


def service_area_demand_index(sales, now):
    """Four consecutive half-open 90-day quarters ending at now; round per quarter."""
    pressure = Decimal("0.00")
    for index, (start, end) in enumerate(_quarter_bounds(now)):
        quarter_credits = Decimal("0.00")
        for sale in sales:
            if sale["status"] not in ("EXECUTED", "ASSIGNED"):
                continue
            executed_at = sale.get("executed_at")
            if executed_at is None:
                continue
            if start <= executed_at < end:
                quarter_credits += dec(sale["credits_requested"])
        pressure += rhu(quarter_credits * QUARTER_WEIGHTS[index], 2)
    capped = min(DEMAND_INDEX_CEILING, pressure / DEMAND_NORMALIZER_CREDITS)
    return rhu(capped, 4)


def trailing_window_credits(sales, now):
    """Total requested credits settled inside the trailing 360-day window."""
    total = Decimal("0.00")
    start = now - days(QUARTER_DAYS * 4)
    for sale in sales:
        if sale["status"] not in ("EXECUTED", "ASSIGNED"):
            continue
        executed_at = sale.get("executed_at")
        if executed_at is None:
            continue
        if start <= executed_at < now:
            total += dec(sale["credits_requested"])
    return total


# -------------------------------------------------------------- credit pricing
def credit_sale_price(hgm_class, credits_requested, service_area_tier, stewardship_underfunded,
                      demand_index):
    base = BASE_PRICE_CENTS_PER_CREDIT[hgm_class]
    credits = dec(credits_requested)
    tier1 = min(credits, TIER1_MAX_CREDITS)
    tier2 = min(max(credits - TIER1_MAX_CREDITS, Decimal("0")), TIER2_MAX_CREDITS)
    tier3 = max(credits - (TIER1_MAX_CREDITS + TIER2_MAX_CREDITS), Decimal("0"))
    subtotal = Decimal("0")
    for amount, multiplier in ((tier1, TIER1_MULTIPLIER), (tier2, TIER2_MULTIPLIER),
                               (tier3, TIER3_MULTIPLIER)):
        if amount > 0:
            subtotal += rhu(amount * base * multiplier, 0)
    secondary_pct = (SECONDARY_SERVICE_AREA_PREMIUM_PCT
                     if service_area_tier == "SECONDARY" else Decimal("0.00"))
    stewardship_pct = (STEWARDSHIP_SURCHARGE_PCT
                       if stewardship_underfunded else Decimal("0.00"))
    premium = rhu(subtotal * (secondary_pct + stewardship_pct), 0)
    demand_multiplier = min(DEMAND_ADJUSTMENT_CAP_PCT, DEMAND_SENSITIVITY * dec(demand_index))
    demand = rhu(subtotal * demand_multiplier, 0)
    gross = subtotal + premium + demand
    cap = rhu(subtotal * PRICE_CAP_MULTIPLIER, 0)
    return int(min(gross, cap))


def execution_reprice_cap(quoted_price_cents):
    return int(rhu(dec(quoted_price_cents) * EXECUTION_REPRICE_CAP_MULTIPLIER, 0))


# ----------------------------------------------------- performance attainment
def performance_attainment(standards, measurements):
    """Returns (attainment_score, failed_standard_codes, compliance_status).

    `standards` must already be filtered to the effective ones and is iterated by
    standard_code ASC. `measurements` maps standard_code -> measured_value.
    Raises KeyError-free: the caller validates measurement presence first.
    """
    ordered_standards = sorted(standards, key=lambda s: s["standard_code"])
    contribution_total = Decimal("0.0000")
    weight_total = Decimal("0")
    failed = []
    for standard in ordered_standards:
        measured = dec(measurements[standard["standard_code"]])
        threshold = dec(standard["threshold_value"])
        weight = dec(standard["weight"])
        weight_total += weight
        if standard["comparator"] == "GTE":
            ratio = min(Decimal("1.0"), measured / threshold)
            met = measured >= threshold
        else:
            if measured <= threshold:
                ratio = Decimal("1.0")
            else:
                ratio = max(Decimal("0.0"), Decimal("1.0") - (measured - threshold) / threshold)
            met = measured <= threshold
        contribution_total += rhu(ratio * weight, 4)
        if not met:
            failed.append(standard["standard_code"])
    score = rhu(contribution_total / weight_total, 4)
    failed.sort()
    if not failed:
        compliance = "PASS"
    elif score >= COMPLIANCE_PARTIAL_MIN:
        compliance = "PARTIAL"
    else:
        compliance = "FAIL"
    return score, failed, compliance


# ---------------------------------------------------------- demand forecasting
def credit_demand_forecast(sales, now, credits_available):
    demand_index = service_area_demand_index(sales, now)
    trailing_total = trailing_window_credits(sales, now)
    trailing_average = rhu(trailing_total / Decimal("4"), 2)
    horizon = rhu(trailing_average * Decimal("4"), 2)
    if dec(credits_available) == 0:
        projected = 0
    else:
        divisor = max(Decimal("0.01"), trailing_average)
        projected = min(FORECAST_HORIZON_QUARTERS,
                        ceil_int(dec(credits_available) / divisor))
    return demand_index, trailing_average, horizon, projected
