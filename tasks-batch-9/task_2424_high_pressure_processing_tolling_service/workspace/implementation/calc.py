"""Calculation rules (PRD 2.7, 3.2, 3.5, 3.6, 3.8, 3.9).

Every monetary figure is a whole-cent integer computed with decimal.Decimal;
float arithmetic is never used for money, scores or percentages.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# ---- constants -------------------------------------------------------------
W_PRESSURE = Decimal("0.50")
W_FILM = Decimal("0.30")
W_FORMAT = Decimal("0.20")
BURST_MARGIN_FULL_CREDIT_MPA = Decimal("50.0")
FILM_FULL_CREDIT_MICRON = Decimal("80.0")
FORMAT_FACTOR = {
    "POUCH": Decimal("1.0"),
    "TRAY_SEALED": Decimal("0.85"),
    "RIGID_BOTTLE": Decimal("0.60"),
    "GLASS": Decimal("0.0"),
}
MIN_PACKAGE_SUITABILITY_SCORE = Decimal("70.00")
MIN_ACCEPTABLE_VALIDATION_RUNS = 2
MAX_REVISION_ROUNDS = 3
QUALIFICATION_VALID_DAYS = 365

LOAD_UNLOAD_SECONDS = 180
RATE_PER_MINUTE_CENTS = 1250
UNDERUTIL_TIER_1_PCT = Decimal("60.00")
UNDERUTIL_TIER_1_RATE = Decimal("0.20")
UNDERUTIL_TIER_2_PCT = Decimal("85.00")
UNDERUTIL_TIER_2_RATE = Decimal("0.08")
CREDIT_TIER_HIGH_CENTS = 12000
CREDIT_TIER_HIGH_RATE = Decimal("0.05")
CREDIT_TIER_LOW_CENTS = 8000
CREDIT_TIER_LOW_RATE = Decimal("0.03")

LEAKER_CHARGEBACK_PPM = 3000
LEAKER_WATCH_PPM = 1500
TRAILING_WATCH_PPM = 2000
TRAILING_WINDOW_DAYS = 90
PER_LEAKER_HANDLING_CENTS = 125
LEAKER_FEE_SHARE = Decimal("0.50")
REPROCESS_FEE_SHARE = Decimal("0.50")

MIN_TAKE_FRACTION = Decimal("0.80")
CRITICAL_SHORTFALL_PCT = Decimal("5.00")

PACKAGE_FORMATS = ("POUCH", "TRAY_SEALED", "RIGID_BOTTLE", "GLASS")
CONTAMINATION_GROUPS = ("RTE_PRODUCE", "RAW_PROTEIN", "DAIRY", "JUICE", "PET_FOOD")


# ---- primitives ------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(round_half_up(value, 0))


def rhu2(value):
    """Two decimal places, round half up — percentages and scores."""
    return round_half_up(value, 2)


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


# ---- qualification package suitability score (PRD 3.2) ---------------------
def package_suitability_score(pressure_mpa, burst_pressure_mpa,
                             film_thickness_micron, package_format):
    pressure_margin = (D(burst_pressure_mpa) - D(pressure_mpa)) / BURST_MARGIN_FULL_CREDIT_MPA
    if pressure_margin < 0:
        pressure_margin = Decimal(0)
    if pressure_margin > 1:
        pressure_margin = Decimal(1)
    film_margin = D(film_thickness_micron) / FILM_FULL_CREDIT_MICRON
    if film_margin > 1:
        film_margin = Decimal(1)
    format_factor = FORMAT_FACTOR[package_format]
    total = (W_PRESSURE * pressure_margin * 100
             + W_FILM * film_margin * 100
             + W_FORMAT * format_factor * 100)
    # exactly ONE rounding step, applied to the sum
    return rhu2(total)


# ---- cycle time and tolling fee (PRD 3.5 / 3.8) ---------------------------
def estimated_come_up_seconds(target_pressure_mpa, pump_ramp_rate_mpa_per_sec):
    return ceil_int(D(target_pressure_mpa) / D(pump_ramp_rate_mpa_per_sec))


def cycle_seconds(come_up_seconds, hold_seconds, decompression_seconds):
    return (LOAD_UNLOAD_SECONDS + int(come_up_seconds) + int(hold_seconds)
            + int(decompression_seconds))


def utilization_pct(baskets_used_total, basket_count):
    if not basket_count:
        return Decimal("0.00")
    return rhu2(D(100) * D(baskets_used_total) / D(basket_count))


def tolling_fee_cents(total_cycle_seconds, util_pct):
    """Steps 2-6 of the tolling fee.  Returns the net fee in whole cents."""
    billable_minutes = ceil_int(D(total_cycle_seconds) / D(60))
    base_cents = billable_minutes * RATE_PER_MINUTE_CENTS

    util = D(util_pct)
    if util < UNDERUTIL_TIER_1_PCT:
        surcharge_rate = UNDERUTIL_TIER_1_RATE
    elif util < UNDERUTIL_TIER_2_PCT:
        surcharge_rate = UNDERUTIL_TIER_2_RATE
    else:
        surcharge_rate = Decimal("0.00")
    surcharge_cents = rhu_cents(D(base_cents) * surcharge_rate)

    gross_cents = base_cents + surcharge_cents

    # the credit tier is keyed on GROSS (base + surcharge), never on base alone
    if gross_cents >= CREDIT_TIER_HIGH_CENTS:
        credit_rate = CREDIT_TIER_HIGH_RATE
    elif gross_cents >= CREDIT_TIER_LOW_CENTS:
        credit_rate = CREDIT_TIER_LOW_RATE
    else:
        credit_rate = Decimal("0.00")
    credit_cents = rhu_cents(D(gross_cents) * credit_rate)

    return gross_cents - credit_cents


# ---- fee allocation across loads (PRD 3.8) --------------------------------
def allocate_fee(total_cents, loads, peak_factor_for):
    """Waterfall allocation.

    ``loads`` must already be ordered by created_at ascending.  Each share is
    truncated downward, the leftover cents are handed out one at a time to the
    queue ordered by baskets_used DESC then created_at ASC, and the seasonal
    peak uplift is applied per load AFTER the remainder pass.
    Returns {load_id: allocated_fee_cents}.
    """
    result = {}
    if not loads:
        return result
    divisor = sum(int(load["baskets_used"]) for load in loads)
    if divisor <= 0:
        for load in loads:
            result[load["id"]] = 0
        return result
    for load in loads:
        result[load["id"]] = floor_int(
            D(total_cents) * D(load["baskets_used"]) / D(divisor))
    remainder = int(total_cents) - sum(result.values())
    if remainder > 0:
        queue = sorted(loads,
                       key=lambda l: (-int(l["baskets_used"]), l["created_at"], l["_seq"]))
        for load in queue[:remainder]:
            result[load["id"]] += 1
    for load in loads:
        factor = peak_factor_for(load)
        if factor is not None:
            result[load["id"]] = rhu_cents(D(result[load["id"]]) * D(factor))
    return result


# ---- package failure risk (PRD 3.8 / 3.9) ---------------------------------
def leaker_ppm(leaker_units, units_inspected):
    if not units_inspected:
        return 0
    return int(round_half_up(D(1000000) * D(leaker_units) / D(units_inspected), 0))


def decide_chargeback_party(load_ppm, customer_trailing_ppm):
    if load_ppm >= LEAKER_CHARGEBACK_PPM:
        return "CUSTOMER"
    if load_ppm >= LEAKER_WATCH_PPM and customer_trailing_ppm >= TRAILING_WATCH_PPM:
        return "CUSTOMER"
    return "FACILITY"


def leaker_chargeback_cents(load_ppm, leaker_units, allocated_fee_cents):
    handling = int(leaker_units) * PER_LEAKER_HANDLING_CENTS
    rework = 0
    if load_ppm >= LEAKER_CHARGEBACK_PPM:
        rework = rhu_cents(D(allocated_fee_cents or 0) * LEAKER_FEE_SHARE)
    return handling + rework


def reprocess_chargeback_cents(allocated_fee_cents):
    return rhu_cents(D(allocated_fee_cents or 0) * REPROCESS_FEE_SHARE)


def pooled_ppm(total_leakers, total_inspected):
    if not total_inspected:
        return 0
    return int(round_half_up(D(1000000) * D(total_leakers) / D(total_inspected), 0))


# ---- take-or-pay (PRD 3.3) ------------------------------------------------
def take_or_pay(committed_slots, consumed_slots, slot_take_or_pay_cents):
    min_take_slots = ceil_int(D(committed_slots) * MIN_TAKE_FRACTION)
    shortfall = min_take_slots - int(consumed_slots)
    if shortfall < 0:
        shortfall = 0
    return shortfall, shortfall * int(slot_take_or_pay_cents)


# ---- CCP verdict and deviation severity (PRD 3.6) ------------------------
def ccp_evaluation(actual_pressure_mpa, actual_hold_seconds, water_temp_c,
                   required_pressure, required_hold, water_temp_limit):
    flags = []
    if required_pressure is not None and D(actual_pressure_mpa) < D(required_pressure):
        flags.append("UNDER_PRESSURE")
    if required_hold is not None and int(actual_hold_seconds) < int(required_hold):
        flags.append("SHORT_HOLD")
    if water_temp_limit is not None and D(water_temp_c) > D(water_temp_limit):
        flags.append("TEMP_EXCURSION")

    verdict = "WITHIN_LIMITS" if not flags else "DEVIATION"

    pressure_pct = Decimal("0.00")
    if required_pressure is not None and D(actual_pressure_mpa) < D(required_pressure):
        pressure_pct = rhu2(D(100) * (D(required_pressure) - D(actual_pressure_mpa))
                            / D(required_pressure))
    hold_pct = Decimal("0.00")
    if required_hold is not None and int(actual_hold_seconds) < int(required_hold):
        hold_pct = rhu2(D(100) * (D(required_hold) - D(actual_hold_seconds))
                        / D(required_hold))
    temp_pct = Decimal("0.00")
    if water_temp_limit is not None and D(water_temp_c) > D(water_temp_limit):
        temp_pct = rhu2(D(100) * (D(water_temp_c) - D(water_temp_limit))
                        / D(water_temp_limit))

    worst = max(pressure_pct, hold_pct, temp_pct)
    severity = "CRITICAL" if worst >= CRITICAL_SHORTFALL_PCT else "MAJOR"
    return {
        "flags": flags,
        "ccp_verdict": verdict,
        "worst_shortfall_pct": worst,
        "severity": severity,
    }
