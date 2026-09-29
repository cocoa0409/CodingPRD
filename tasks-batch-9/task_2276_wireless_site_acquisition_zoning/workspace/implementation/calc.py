"""Calculations (PRD 3.3 - 3.9).  All money and scores use Decimal arithmetic."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

_ONE_DAY = timedelta(days=1)

ZERO = Decimal("0")
HUNDRED = Decimal("100")
CENTS = Decimal("0.01")

# --- rf_qualification_score -------------------------------------------------
RSRP_POINTS_PER_DB = Decimal("5")
W_RSRP = Decimal("0.35")
W_DISTANCE = Decimal("0.25")
W_HEIGHT = Decimal("0.20")
W_CAPACITY = Decimal("0.20")
SITE_TYPE_BONUS = {"TOWER": Decimal("10"), "ROOFTOP": Decimal("5"), "RAW_LAND": Decimal("0")}
AVAILABILITY_PENALTY_PER_MONTH = Decimal("2.5")
AVAILABILITY_GRACE_MONTHS = 6
RF_QUALIFY_MIN_SCORE = Decimal("55.00")

# --- lease ------------------------------------------------------------------
MAX_NEGOTIATION_ROUNDS = 6
MAX_RENT_VARIANCE_PCT = Decimal("15.00")

# --- structural -------------------------------------------------------------
NEW_ANTENNA_LOAD_PCT = Decimal("9.5")
APPURTENANCE_LOAD_PCT_EACH = Decimal("1.8")
BASE_WIND_MPH = Decimal("90")
ICE_FACTOR_PER_INCH = Decimal("0.15")
CODE_FACTOR = {"TIA_222_H": Decimal("1.00"), "TIA_222_G": Decimal("0.95")}
PASS_MAX_PCT = Decimal("85.00")
MOD_MAX_PCT = Decimal("100.00")

# --- zoning fee -------------------------------------------------------------
BASE_FEE = {
    "BY_RIGHT": Decimal("1500.00"),
    "CONDITIONAL_USE": Decimal("3200.00"),
    "VARIANCE": Decimal("4800.00"),
}
VISUAL_SIM_FEE = Decimal("250.00")
HISTORIC_SURCHARGE = Decimal("900.00")

# --- environmental ----------------------------------------------------------
TRIBAL_RESPONSE_DAYS = 30

# --- on-air forecast --------------------------------------------------------
STRUCTURAL_DAYS = 21
ENV_DAYS = 30
PERMIT_DAYS = 25
BACKHAUL_DEFAULT_DAYS = 45
RISK_BASE = Decimal("50")
SLIP_DAY_WEIGHT = Decimal("2.0")
CONTINUANCE_WEIGHT = Decimal("5")
STRUCTURAL_HOLD_PENALTY = Decimal("10")
HIGH_BAND_MIN = Decimal("70.00")
MEDIUM_BAND_MIN = Decimal("40.00")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def round2(value):
    return dec(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def clamp(value, low, high):
    if value < low:
        return dec(low)
    if value > high:
        return dec(high)
    return value


# ---------------------------------------------------------------------------
# RF qualification score
# ---------------------------------------------------------------------------

def rf_qualification_score(candidate, ring):
    measured = dec(candidate["measured_rsrp_dbm"])
    target = dec(ring["target_rsrp_dbm"])
    rsrp_component = clamp(Decimal("50") + (measured - target) * RSRP_POINTS_PER_DB, ZERO, HUNDRED)

    distance = dec(candidate["distance_from_center_m"])
    radius = dec(ring["radius_m"])
    distance_component = clamp(HUNDRED * (Decimal("1") - distance / radius), ZERO, HUNDRED)

    agl = dec(candidate["agl_m"])
    required_agl = dec(ring["required_agl_m"])
    if agl >= required_agl:
        height_component = HUNDRED
    else:
        height_component = clamp(HUNDRED * agl / required_agl, ZERO, HUNDRED)

    if ring["objective_type"] == "COVERAGE":
        capacity_component = HUNDRED
    else:
        offered = dec(candidate["offered_capacity_gbps"])
        target_capacity = dec(ring["target_capacity_gbps"])
        capacity_component = clamp(HUNDRED * offered / target_capacity, ZERO, HUNDRED)

    bonus = SITE_TYPE_BONUS[candidate["site_type"]]
    months_over = candidate["months_to_availability"] - AVAILABILITY_GRACE_MONTHS
    if months_over < 0:
        months_over = 0
    penalty = AVAILABILITY_PENALTY_PER_MONTH * Decimal(months_over)

    raw = (W_RSRP * rsrp_component + W_DISTANCE * distance_component
           + W_HEIGHT * height_component + W_CAPACITY * capacity_component
           + bonus - penalty)
    return round2(clamp(raw, ZERO, HUNDRED))


# ---------------------------------------------------------------------------
# Lease committed rent
# ---------------------------------------------------------------------------

def lease_year_rent(lease, year):
    """Annual rent for 1-based lease year, rounded half up to cents."""
    base = dec(lease["base_monthly_rent_usd"])
    kind = lease["escalation_type"]
    exponent = year - 1
    if kind == "FIXED_PCT":
        rate = dec(lease["escalation_pct"])
        annual = base * Decimal("12") * (Decimal("1") + rate) ** exponent
    elif kind == "CPI_CAPPED":
        rate = min(dec(lease["escalation_pct"]), dec(lease["cpi_cap_pct"]))
        annual = base * Decimal("12") * (Decimal("1") + rate) ** exponent
    else:  # FLAT_STEP
        step = dec(lease["escalation_step_usd"])
        annual = (base + step * Decimal(exponent)) * Decimal("12")
    return round2(annual)


def lease_total_years(lease):
    return int(lease["initial_term_years"]) + int(lease["renewal_option_count"]) * int(lease["renewal_term_years"])


def lease_committed_rent(lease):
    """Both variants of the committed rent plus the supporting figures."""
    initial_years = int(lease["initial_term_years"])
    total_years = lease_total_years(lease)

    per_year = [lease_year_rent(lease, y) for y in range(1, max(total_years, initial_years) + 1)]

    provisional_total = round2(sum(per_year[0:initial_years], ZERO))
    base_total = round2(sum(per_year[0:total_years], ZERO))
    uplift = round2(base_total * dec(lease["revenue_share_pct"]))
    final_total = round2(base_total + uplift)
    delta = round2(final_total - provisional_total)

    return {
        "provisional_total_usd": provisional_total,
        "base_total_usd": base_total,
        "revenue_share_uplift_usd": uplift,
        "final_total_usd": final_total,
        "delta_usd": delta,
        "priced_years": total_years,
        "first_year_rent_usd": per_year[0] if per_year else ZERO,
        "last_year_rent_usd": per_year[total_years - 1] if total_years >= 1 else ZERO,
    }


def lease_rent_variance(last_counter_rent, benchmark):
    return round2(HUNDRED * (dec(last_counter_rent) - dec(benchmark)) / dec(benchmark))


# ---------------------------------------------------------------------------
# Structural capacity utilization
# ---------------------------------------------------------------------------

def structural_capacity_utilization(analysis):
    appurtenance_load = APPURTENANCE_LOAD_PCT_EACH * Decimal(int(analysis["appurtenance_count"]))
    wind_factor = (dec(analysis["wind_speed_mph"]) / BASE_WIND_MPH) ** 2
    ice_factor = Decimal("1") + ICE_FACTOR_PER_INCH * dec(analysis["ice_thickness_in"])
    code_factor = CODE_FACTOR[analysis["analysis_type"]]
    proposed_load = (NEW_ANTENNA_LOAD_PCT + appurtenance_load) * wind_factor * ice_factor
    return round2((dec(analysis["existing_load_pct"]) + proposed_load) * code_factor)


def structural_result(utilization):
    if utilization <= PASS_MAX_PCT:
        return "PASS"
    if utilization <= MOD_MAX_PCT:
        return "PASS_WITH_MOD"
    return "FAIL"


# ---------------------------------------------------------------------------
# Zoning fee and shot clock
# ---------------------------------------------------------------------------

def zoning_fee_total(application, jurisdiction):
    subtotal = (BASE_FEE[application["application_type"]]
                + VISUAL_SIM_FEE * Decimal(int(application["visual_simulation_count"])))
    if jurisdiction["historic_district_flag"]:
        subtotal = subtotal + HISTORIC_SURCHARGE
    if subtotal >= Decimal("6000"):
        rate = Decimal("0.12")
    elif subtotal >= Decimal("4000"):
        rate = Decimal("0.08")
    else:
        rate = Decimal("0.04")
    expedite_fee = round2(subtotal * rate)
    return round2(subtotal + expedite_fee)


def review_days_for(application_type, jurisdiction):
    if application_type == "BY_RIGHT":
        return int(jurisdiction["by_right_review_days"])
    if application_type == "CONDITIONAL_USE":
        return int(jurisdiction["conditional_use_review_days"])
    return int(jurisdiction["variance_review_days"])


# ---------------------------------------------------------------------------
# Crew days
# ---------------------------------------------------------------------------

def crew_days(window_start, window_end):
    return (window_end - window_start).days


def covered_days(window_start, window_end):
    """The UTC day boundaries d with window_start <= d < window_end."""
    days = []
    day = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if day < window_start:
        day = day + _ONE_DAY
    while day < window_end:
        days.append(day)
        day = day + _ONE_DAY
    return days


# ---------------------------------------------------------------------------
# On-air schedule forecast
# ---------------------------------------------------------------------------

def risk_days(remaining_days, historical_delay_factor, continuance_count, hearing_cadence_days):
    inflated = math.ceil(dec(remaining_days) * dec(historical_delay_factor))
    return int(inflated) + int(continuance_count) * int(hearing_cadence_days)


def schedule_risk_score(slip_days, continuance_count, structural_hold):
    raw = (RISK_BASE + SLIP_DAY_WEIGHT * Decimal(int(slip_days))
           + CONTINUANCE_WEIGHT * Decimal(int(continuance_count)))
    if structural_hold:
        raw = raw + STRUCTURAL_HOLD_PENALTY
    return round2(clamp(raw, ZERO, HUNDRED))


def risk_band(score):
    if score >= HIGH_BAND_MIN:
        return "HIGH"
    if score >= MEDIUM_BAND_MIN:
        return "MEDIUM"
    return "LOW"
