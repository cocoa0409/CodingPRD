"""Pinned calculations (PRD 2.6, 3.x / scaffold calculations).

Every rounding is round half up and every step consumes the previous step's
already-rounded value.
"""

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, getcontext

getcontext().prec = 60


# ---------------------------------------------------------------- constants

MIN_COMPLIANCE_MARGIN_PCT = Decimal("5.00")

PPM_PROBATION_THRESHOLD = 25000
PPM_SUSPEND_THRESHOLD = 100000
REDUCED_STREAK = 3
SKIP_LOT_STREAK = 5

REDUCED_FRACTION = Decimal("0.02")
NORMAL_FRACTION = Decimal("0.05")
TIGHTENED_FRACTION = Decimal("0.10")
REDUCED_MIN = 5
NORMAL_MIN = 8
TIGHTENED_MIN = 13
MAJOR_ACCEPTANCE_FRACTION = Decimal("0.10")

MIN_CAPABILITY_SAMPLE = 5
CPK_GATE_CRITICAL = Decimal("1.33")
CPK_GATE_MAJOR = Decimal("1.00")
CPK_CAP = Decimal("9.9999")

MAX_REWORK_CYCLES = 2

STANDARD_EMISSION_MULTIPLIER = Decimal("1.10")
DEVIATION_EMISSION_MULTIPLIER = Decimal("1.00")

CARRY_TIER_1_CEILING = 5000000
CARRY_TIER_2_CEILING = 20000000
CARRY_RATE_SMALL = Decimal("0.0040")
CARRY_RATE_MEDIUM = Decimal("0.0030")
CARRY_RATE_LARGE = Decimal("0.0020")

SEASON_START = {
    "WALK_MOWER": date(2027, 3, 1),
    "RIDING_MOWER": date(2027, 3, 15),
    "SNOW_THROWER": date(2026, 11, 2),
    "GENERATOR": date(2027, 5, 3),
}

MIN_AUDIT_SAMPLE = 2
AUDIT_SAMPLE_FRACTION = Decimal("0.02")
AUDIT_MAX_FAILURE_RATE = Decimal("0.25")
AUDIT_FAILURE_SUSPEND_COUNT = 2

MAX_BLADE_STOP_MS = 3000
MAX_OPC_STOP_MS = 1000

BACKORDER_PROMISE_DAYS = 21
MAX_SUPERSESSION_DEPTH = 5

PRODUCT_LINES = ("WALK_MOWER", "RIDING_MOWER", "SNOW_THROWER", "GENERATOR")

REQUIRED_OPC = {
    "WALK_MOWER": "BAIL",
    "RIDING_MOWER": "SEAT_SWITCH",
    "SNOW_THROWER": "TWO_HAND",
    "GENERATOR": "CO_SHUTOFF",
}

REQUIRED_STANDARD = {
    "WALK_MOWER": "ANSI_B71_1",
    "RIDING_MOWER": "ANSI_B71_1",
    "SNOW_THROWER": "ANSI_B71_3",
    "GENERATOR": "UL_2201",
}

POSTURE_BY_FAMILY_STATUS = {
    "DRAFT": "PENDING",
    "DURABILITY_TESTING": "RESTRICTED",
    "DURABILITY_COMPLETE": "RESTRICTED",
    "SUBMITTED": "RESTRICTED",
    "AUDIT_HOLD": "RESTRICTED",
    "CERTIFIED": "OPEN",
    "SUSPENDED": "FROZEN",
}


# ------------------------------------------------------------------ rounding

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def rhu_int(value):
    return int(rhu(value, 0))


# ----------------------------------------------- deterioration / certification

def deterioration(family, initial_emission, final_emission, accumulated_hours):
    """PRD 3.2 five pinned steps.  Returns (df_method, df, certified, margin,
    extrapolated)."""
    df_method = "MULTIPLICATIVE" if family["emission_standard"] == "EPA_PHASE3" else "ADDITIVE"
    initial = dec(initial_emission)
    final = dec(final_emission)

    # Step 1 / 2 — raw deterioration over the run.
    if df_method == "MULTIPLICATIVE":
        df_raw = final / initial
    else:
        df_raw = final - initial

    # Step 3 — extrapolation to the full durability period.
    durability_hours = family["durability_hours"]
    extrapolated = accumulated_hours < durability_hours
    if extrapolated:
        scale = Decimal(durability_hours) / Decimal(accumulated_hours)
    else:
        scale = Decimal(1)
    if df_method == "MULTIPLICATIVE":
        df = Decimal(1) + (df_raw - Decimal(1)) * scale
    else:
        df = df_raw * scale
    df = rhu(df, 4)

    # Step 4 — age the declared baseline with the ROUNDED factor.
    baseline = dec(family["declared_baseline_emission_g_per_kwh"])
    if df_method == "MULTIPLICATIVE":
        certified = baseline * df
    else:
        certified = baseline + df
    certified = rhu(certified, 2)

    # Step 5 — headroom under the family limit from the ROUNDED certified value.
    limit = dec(family["family_emission_limit_g_per_kwh"])
    margin = rhu((limit - certified) / limit * Decimal(100), 2)

    return df_method, df, certified, margin, extrapolated


def df_method_for(family):
    return "MULTIPLICATIVE" if family["emission_standard"] == "EPA_PHASE3" else "ADDITIVE"


# ------------------------------------------------------------- supplier quality

def lot_sample_plan(lot_quantity, level, criticality):
    if level == "SKIP_LOT":
        sample_size = 0
    elif level == "REDUCED":
        sample_size = max(REDUCED_MIN, ceil_int(Decimal(lot_quantity) * REDUCED_FRACTION))
    elif level == "NORMAL":
        sample_size = max(NORMAL_MIN, ceil_int(Decimal(lot_quantity) * NORMAL_FRACTION))
    else:
        sample_size = max(TIGHTENED_MIN, ceil_int(Decimal(lot_quantity) * TIGHTENED_FRACTION))
    sample_size = min(sample_size, lot_quantity)
    if criticality == "CRITICAL":
        acceptance_number = 0
    else:
        acceptance_number = floor_int(Decimal(sample_size) * MAJOR_ACCEPTANCE_FRACTION)
    return sample_size, acceptance_number


def lot_defect_ppm(defects_found, sample_size):
    if not sample_size:
        return 0
    return rhu_int(Decimal(defects_found) / Decimal(sample_size) * Decimal(1000000))


def pooled_ppm(lots):
    total_defects = 0
    total_sample = 0
    for lot in lots:
        total_defects += lot["defects_found"] or 0
        total_sample += lot["sample_size"] or 0
    if total_sample == 0:
        return 0
    return rhu_int(Decimal(total_defects) / Decimal(total_sample) * Decimal(1000000))


def per_lot_average_ppm(lots):
    rates = [lot_defect_ppm(lot["defects_found"] or 0, lot["sample_size"]) for lot in lots]
    if not rates:
        return 0
    return rhu_int(Decimal(sum(rates)) / Decimal(len(rates)))


def inspection_ladder(rolling_ppm, consecutive_accepted_lots):
    """Returns (approval_status, incoming_inspection_level)."""
    if rolling_ppm > PPM_SUSPEND_THRESHOLD:
        return "SUSPENDED", "TIGHTENED"
    if rolling_ppm > PPM_PROBATION_THRESHOLD:
        return "PROBATION", "TIGHTENED"
    if consecutive_accepted_lots >= SKIP_LOT_STREAK:
        return "APPROVED", "SKIP_LOT"
    if consecutive_accepted_lots >= REDUCED_STREAK:
        return "APPROVED", "REDUCED"
    return "APPROVED", "NORMAL"


# ---------------------------------------------------------------- machining

def capability(measurements, lsl, usl, criticality):
    values = [dec(m) for m in measurements]
    n = len(values)
    total = sum(values, Decimal(0))
    mean = rhu(total / Decimal(n), 5)
    variance = sum(((v - mean) ** 2 for v in values), Decimal(0)) / Decimal(n - 1)
    exact_sigma = variance.sqrt()
    # sigma_mm is *stored* at six decimals, but the capability ratio divides by the
    # full-precision standard deviation: the worked example pinned in the design
    # notes (measurements 65.000/65.002/64.998/65.004/64.996 against 64.980-65.020)
    # yields cpk 2.1082, which only falls out of the unrounded divisor.
    sigma = rhu(exact_sigma, 6)
    if sigma == 0:
        cpk = CPK_CAP
    else:
        distance = min(dec(usl) - mean, mean - dec(lsl))
        cpk = rhu(distance / (Decimal(3) * exact_sigma), 4)
    gate = CPK_GATE_CRITICAL if criticality == "CRITICAL" else CPK_GATE_MAJOR
    status = "CLOSED" if cpk >= gate else "CAPABILITY_HOLD"
    return n, mean, sigma, cpk, status


# ------------------------------------------------------------------ assembly

def torque_band(torque_spec_nm, torque_tolerance_pct):
    spec = dec(torque_spec_nm)
    tol = dec(torque_tolerance_pct)
    lower = rhu(spec * (Decimal(1) - tol), 2)
    upper = rhu(spec * (Decimal(1) + tol), 2)
    return lower, upper


def out_of_spec_count(readings, lower, upper):
    count = 0
    for reading in readings:
        value = dec(reading["torque_nm"])
        if value < lower or value > upper:
            count += 1
    return count


def hot_test_threshold(certified_emission, deviation_sourced):
    multiplier = DEVIATION_EMISSION_MULTIPLIER if deviation_sourced else STANDARD_EMISSION_MULTIPLIER
    return rhu(dec(certified_emission) * multiplier, 2)


# ------------------------------------------------------------------ planning

def carry_rate_for(build_value_cents):
    if build_value_cents < CARRY_TIER_1_CEILING:
        return CARRY_RATE_SMALL
    if build_value_cents < CARRY_TIER_2_CEILING:
        return CARRY_RATE_MEDIUM
    return CARRY_RATE_LARGE


def build_carry_cost(planned_quantity, standard_cost_cents, season, product_line,
                     production_week):
    build_value_cents = planned_quantity * standard_cost_cents
    carry_rate = carry_rate_for(build_value_cents)
    if season == "PRE_SEASON":
        season_start = SEASON_START[product_line]
        carry_weeks = floor_int(Decimal((season_start - production_week).days) / Decimal(7))
    else:
        carry_weeks = 0
    carry_cost_cents = rhu_int(Decimal(build_value_cents) * carry_rate * Decimal(carry_weeks))
    total_committed_cents = build_value_cents + carry_cost_cents
    return build_value_cents, carry_rate, carry_weeks, carry_cost_cents, total_committed_cents


def per_week_load(planned_quantity, week_span):
    return ceil_int(Decimal(planned_quantity) / Decimal(week_span))


def allocation_waterfall(pool, dealer_share_pct, dealer_cap_units, mass_retail_cap_units):
    share = dec(dealer_share_pct)
    raw_dealer = Decimal(pool) * share
    raw_mass = Decimal(pool) * (Decimal(1) - share)
    dealer = floor_int(raw_dealer)
    mass = floor_int(raw_mass)
    remainder = pool - dealer - mass
    if remainder == 1:
        if (raw_dealer - Decimal(dealer)) >= (raw_mass - Decimal(mass)):
            dealer += 1
        else:
            mass += 1
    if mass > mass_retail_cap_units:
        dealer += mass - mass_retail_cap_units
        mass = mass_retail_cap_units
    unallocated = 0
    if dealer > dealer_cap_units:
        unallocated = dealer - dealer_cap_units
        dealer = dealer_cap_units
    return dealer, mass, unallocated


# -------------------------------------------------------------------- audits

def required_sample_size(built_quantity):
    return max(MIN_AUDIT_SAMPLE, ceil_int(Decimal(built_quantity) * AUDIT_SAMPLE_FRACTION))


def audit_outcome(units_tested, units_failed, max_measured_emission, family_limit):
    failure_rate = rhu(Decimal(units_failed) / Decimal(units_tested), 4)
    emission_breach = dec(max_measured_emission) > dec(family_limit)
    rate_breach = failure_rate > AUDIT_MAX_FAILURE_RATE
    if emission_breach:
        return failure_rate, "FAILED", "EMISSION_LIMIT_EXCEEDED"
    if rate_breach:
        return failure_rate, "FAILED", "FAILURE_RATE_EXCEEDED"
    return failure_rate, "PASSED", None


# -------------------------------------------------------------- safety / parts

def safety_result(blade_stop_time_ms, opc_stop_time_ms):
    blade_ok = blade_stop_time_ms is None or blade_stop_time_ms <= MAX_BLADE_STOP_MS
    opc_ok = opc_stop_time_ms <= MAX_OPC_STOP_MS
    return "PASSED" if (blade_ok and opc_ok) else "FAILED"


def fill_rate(filled, substituted, backordered):
    served = filled + substituted
    total = served + backordered
    if total == 0:
        return None
    return rhu(Decimal(served) / Decimal(total) * Decimal(100), 2)
