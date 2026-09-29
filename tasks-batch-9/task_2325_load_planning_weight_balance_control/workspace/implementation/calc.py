"""Pinned arithmetic: masses, index units and percent-MAC (PRD §2.5, §2.6, §3).

Every figure is Decimal-based; round-half-up to 2 decimals unless a rule names a
different discipline. Two deliberate exceptions: the performance-limited takeoff
weight is floored to a multiple of 10 kg, and the allowed payload is floored at 0.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

CENT = Decimal("0.01")
ZERO = Decimal("0")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def r2(value):
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def out(value):
    """Serialise a Decimal figure as a JSON number."""
    return float(r2(value))


# --------------------------------------------------------------- constants
ALTITUDE_PENALTY_PER_1000FT = D("220")
TEMP_PENALTY_PER_C = D("130")
WIND_CREDIT_PER_KT = D("90")
MAX_WIND_CREDIT_KG = D("900")
PERF_ROUNDING_STEP = D("10")
CONTAMINATION_FACTOR = {"DRY": D("1.00"), "WET": D("0.93"), "CONTAMINATED": D("0.85")}
LMC_HARD_CAP_KG = D("500")
MINOR_MAX_KG = D("500")
MAJOR_MAX_KG = D("1000")


# ------------------------------------------------------------ index system
def raw_index(weight, arm, ref_arm_m, index_c):
    """mass * (arm - ref_arm) / index_c, at full precision (PRD §2.6)."""
    return D(weight) * (D(arm) - D(ref_arm_m)) / D(index_c)


def index_delta(weight, arm, ref_arm_m, index_c):
    return r2(raw_index(weight, arm, ref_arm_m, index_c))


def pct_mac(index, weight, aircraft):
    """Back-convert an index to a percent-MAC figure (PRD §3.6 step three)."""
    weight = D(weight)
    mac_length = D(aircraft["mac_length_m"])
    if weight == 0 or mac_length == 0:
        return ZERO
    arm = D(aircraft["ref_arm_m"]) + (D(index) - D(aircraft["index_k"])) * D(aircraft["index_c"]) / weight
    return r2((arm - D(aircraft["lemac_m"])) / mac_length * D(100))


# -------------------------------------------- calculate_dry_operating_weight
def dry_operating(aircraft, crew_weight_kg, crew_arm_m):
    dow = r2(D(aircraft["basic_empty_weight_kg"]) + D(crew_weight_kg))
    crew_delta = index_delta(crew_weight_kg, crew_arm_m, aircraft["ref_arm_m"], aircraft["index_c"])
    doi = r2(D(aircraft["basic_index"]) + crew_delta)
    return dow, doi


# --------------------- calculate_performance_limited_takeoff_weight
def performance_limited_takeoff_weight(band, runway, outside_air_temp_c, headwind_component_kt, runway_condition):
    altitude_penalty = r2(ALTITUDE_PENALTY_PER_1000FT * D(runway["elevation_ft"]) / D("1000"))
    excess_temp = D(outside_air_temp_c) - D(band["temp_lo_c"])
    if excess_temp < 0:
        excess_temp = ZERO
    temperature_penalty = r2(TEMP_PENALTY_PER_C * excess_temp)
    headwind = D(headwind_component_kt)
    if headwind < 0:
        headwind = ZERO
    wind_credit = r2(min(MAX_WIND_CREDIT_KG, headwind * WIND_CREDIT_PER_KT))
    bracket = D(band["base_limit_weight_kg"]) - altitude_penalty - temperature_penalty + wind_credit
    raw = bracket * CONTAMINATION_FACTOR[runway_condition]
    return (raw / PERF_ROUNDING_STEP).to_integral_value(rounding=ROUND_FLOOR) * PERF_ROUNDING_STEP


# -------------------------------------------------- calculate_allowed_payload
LIMIT_ORDER = ("PERFORMANCE", "MTOW", "MZFW", "MLW", "MAX_TAXI")


def allowed_payload(aircraft, dry_operating_weight_kg, perf_limited_kg, ramp_fuel_kg, taxi_fuel_kg, trip_fuel_kg):
    dow = D(dry_operating_weight_kg)
    takeoff_fuel = D(ramp_fuel_kg) - D(taxi_fuel_kg)
    landing_fuel = takeoff_fuel - D(trip_fuel_kg)
    candidates = {
        "PERFORMANCE": D(perf_limited_kg) - dow - takeoff_fuel,
        "MTOW": D(aircraft["max_takeoff_weight_kg"]) - dow - takeoff_fuel,
        "MZFW": D(aircraft["max_zero_fuel_weight_kg"]) - dow,
        "MLW": D(aircraft["max_landing_weight_kg"]) - dow - landing_fuel,
        "MAX_TAXI": D(aircraft["max_taxi_weight_kg"]) - dow - D(ramp_fuel_kg),
    }
    minimum = min(candidates[name] for name in LIMIT_ORDER)
    limiting_factor = next(name for name in LIMIT_ORDER if candidates[name] == minimum)
    payload = r2(minimum)
    if payload < 0:
        payload = ZERO
    return payload, limiting_factor


# ------------------------------------------------ calculate_pax_line_weight
def pax_line_weight(line, program):
    if program["program_kind"] == "ACTUAL":
        return r2(D(line.get("actual_weight_kg") or 0))
    total = (
        D(line.get("male_count") or 0) * D(program["male_kg"])
        + D(line.get("female_count") or 0) * D(program["female_kg"])
        + D(line.get("child_count") or 0) * D(program["child_kg"])
        + D(line.get("infant_count") or 0) * D(program["infant_kg"])
    )
    return r2(total)


# ------------------------------------------ calculate_bag_allocation_weight
def bag_effective_weight(allocation, program):
    if allocation.get("bag_weight_kg") is not None:
        return r2(D(allocation["bag_weight_kg"]))
    return r2(D(allocation.get("bag_count") or 0) * D(program["checked_bag_kg"]))


# --------------------------------------------------- calculate_lmc_allowance
def lmc_allowance(underload_kg):
    live = D(underload_kg)
    if live < 0:
        live = ZERO
    return r2(min(LMC_HARD_CAP_KG, live))


def lmc_signed_mass(change_kind, male_count, female_count, mass_kg, program):
    if change_kind in ("PAX_ADD", "PAX_REMOVE"):
        magnitude = D(male_count or 0) * D(program["male_kg"]) + D(female_count or 0) * D(program["female_kg"])
        return magnitude if change_kind == "PAX_ADD" else -magnitude
    magnitude = D(mass_kg or 0)
    return magnitude if change_kind == "BAG_ADD" else -magnitude


# ---------------------------------------------- calculate_audit_discrepancy
def audit_severity(total_absolute_discrepancy_kg):
    total = D(total_absolute_discrepancy_kg)
    if total == 0:
        return "NONE"
    if total <= MINOR_MAX_KG:
        return "MINOR"
    if total <= MAJOR_MAX_KG:
        return "MAJOR"
    return "CRITICAL"
