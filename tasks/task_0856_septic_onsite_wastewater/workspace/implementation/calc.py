"""Every calculation rule in the register, with its constants (PRD 2.8 / 3.x)."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from util import add_days, add_months, dec, round_half_up, whole_days_between

# ------------------------------------------------------------------ constants
LOT_SQFT_PER_GPD = 20
PARCEL_FLOW_CAP_GPD = 1500

NITRATE_MCL_MG_L = Decimal("10.0")

TIER_1_MAX_MIN_PER_IN = Decimal("5")
TIER_2_MAX_MIN_PER_IN = Decimal("15")
TIER_3_MAX_MIN_PER_IN = Decimal("30")
TIER_4_MAX_MIN_PER_IN = Decimal("60")
MAX_PERCOLATION_RATE_MIN_PER_IN = Decimal("120")
MIN_LIMITING_LAYER_DEPTH_IN = 18
SITE_EVAL_VALIDITY_YEARS = 5

FLOW_PER_BEDROOM_GPD = 120
MIN_BILLABLE_BEDROOMS = 2

SYSTEM_TYPE_AREA_MULTIPLIER = {
    "CONVENTIONAL": Decimal("1.00"),
    "MOUND": Decimal("1.25"),
    "ATU": Decimal("0.75"),
    "DRIP": Decimal("0.85"),
}
SHALLOW_SOIL_THRESHOLD_IN = 36
SHALLOW_SOIL_MULTIPLIER = Decimal("1.20")
MIN_DRAINFIELD_SQFT = 150
MAX_DRAINFIELD_SQFT = 4000

SETBACK_BASE_FT = {
    "CONVENTIONAL": Decimal("100"),
    "MOUND": Decimal("100"),
    "ATU": Decimal("75"),
    "DRIP": Decimal("75"),
}
SANDY_SETBACK_SURCHARGE_FT = Decimal("25")

PERMIT_BASE_REVIEW_CENTS = 45000
PERMIT_FLOW_RATE_CENTS_PER_GPD = 65
SYSTEM_TYPE_SURCHARGE_CENTS = {
    "CONVENTIONAL": 0,
    "MOUND": 30000,
    "ATU": 42500,
    "DRIP": 27500,
}
PERMIT_VARIANCE_CENTS = 15000
STATE_SURCHARGE_RATE = Decimal("0.045")
COUNTY_TECH_FEE_RATE = Decimal("0.0225")

TRAVEL_BUFFER_MINUTES = 45

TANK_GAL_PER_PERSON_TIER_1 = Decimal("500")
TANK_GAL_PER_PERSON_TIER_2 = Decimal("300")
TANK_GAL_PER_PERSON_TIER_3 = Decimal("200")
TANK_GAL_PER_PERSON_TIER_4 = Decimal("125")
PUMPING_DUE_SOON_DAYS = 90
OPERATING_PERMIT_TERM_YEARS = 5

WATER_FLAG_POINTS = 40
REPAIR_ORDER_POINTS = 25
REPAIR_ORDER_POINT_CAP = 2
DELINQUENT_POINTS = 20
REVOKED_POINTS = 35
ELEVATED_RISK_POINTS = 25
HIGH_RISK_POINTS = 60

REPAIR_DEADLINE_DAYS = {"IMMINENT_HAZARD": 10, "URGENT": 30, "ROUTINE": 90}
REPAIR_EXTENSION_DAYS = 30
MAX_REPAIR_EXTENSIONS = 2

TRANSFER_BASE_FEE_CENTS = 18500
FIELD_VERIFICATION_FEE_CENTS = 9500
RECORDS_RESEARCH_FEE_CENTS = 4000
EXPEDITE_TIER_1_CENTS = 20000
EXPEDITE_TIER_2_CENTS = 30000
EXPEDITE_RATE_LOW = Decimal("0.30")
EXPEDITE_RATE_MID = Decimal("0.20")
EXPEDITE_RATE_HIGH = Decimal("0.15")
TRANSFER_CERT_VALIDITY_DAYS = 180

LIVE_PERMIT_STATES = ("ISSUED", "UNDER_CONSTRUCTION", "COVER_PASSED", "COMPLETED")
PARCEL_OCCUPYING_PERMIT_STATES = ("ISSUED", "UNDER_CONSTRUCTION", "COVER_PASSED")
OPEN_REPAIR_STATES = ("ISSUED", "EXTENDED")


# --------------------------------------------------------------- parcel: flow
def parcel_max_design_flow(lot_size_sqft):
    return min(int(lot_size_sqft // LOT_SQFT_PER_GPD), PARCEL_FLOW_CAP_GPD)


# ------------------------------------------------------------ water chemistry
def water_sample_result(nitrate_mg_l, coliform_present):
    over_mcl = dec(nitrate_mg_l) >= NITRATE_MCL_MG_L
    if coliform_present:
        result = "UNSAFE"
    elif over_mcl:
        result = "EXCEEDANCE"
    else:
        result = "PASS"
    reasons = []
    if coliform_present:
        reasons.append("COLIFORM_DETECTED")
    if over_mcl:
        reasons.append("NITRATE_MCL_EXCEEDED")
    return result, sorted(reasons)


# ------------------------------------------------------- percolation and soil
def perc_hole_derivation(drop_inches, elapsed_minutes, presoak_ok):
    valid = bool(presoak_ok) and dec(drop_inches) > 0 and dec(elapsed_minutes) > 0
    rate = None
    if valid:
        rate = round_half_up(dec(elapsed_minutes) / dec(drop_inches), 2)
    return valid, rate


def perc_rate_evaluation(perc_holes):
    rates = [dec(h["rate_min_per_in"]) for h in perc_holes
             if h.get("valid") and h.get("rate_min_per_in") is not None]
    if not rates:
        return None, None
    preliminary = round_half_up(sum(rates) / Decimal(len(rates)), 2)
    certified = max(rates)
    return preliminary, certified


def soil_loading_rate(certified):
    if certified is None:
        return None
    rate = dec(certified)
    if rate <= TIER_1_MAX_MIN_PER_IN:
        return Decimal("1.20")
    if rate <= TIER_2_MAX_MIN_PER_IN:
        return Decimal("0.80")
    if rate <= TIER_3_MAX_MIN_PER_IN:
        return Decimal("0.60")
    if rate <= TIER_4_MAX_MIN_PER_IN:
        return Decimal("0.40")
    if rate <= MAX_PERCOLATION_RATE_MIN_PER_IN:
        return Decimal("0.20")
    return None


# ------------------------------------------------------------ design sizing
def design_flow(bedrooms):
    return max(int(bedrooms), MIN_BILLABLE_BEDROOMS) * FLOW_PER_BEDROOM_GPD


def required_drainfield_area(flow_gpd, system_type, loading_rate,
                             depth_to_limiting_layer_in):
    if loading_rate is None:
        return None
    multiplier = SYSTEM_TYPE_AREA_MULTIPLIER[system_type]
    shallow = (SHALLOW_SOIL_MULTIPLIER
               if depth_to_limiting_layer_in < SHALLOW_SOIL_THRESHOLD_IN
               else Decimal("1.00"))
    raw = (dec(flow_gpd) / dec(loading_rate)) * multiplier * shallow
    ceiled = int(raw.to_integral_value(rounding=ROUND_CEILING))
    return min(max(ceiled, MIN_DRAINFIELD_SQFT), MAX_DRAINFIELD_SQFT)


def distance_ft(ax, ay, bx, by):
    dx = dec(ax) - dec(bx)
    dy = dec(ay) - dec(by)
    return round_half_up((dx * dx + dy * dy).sqrt(), 2)


def required_setback(system_type, soil_group):
    base = SETBACK_BASE_FT[system_type]
    if soil_group == "SANDY":
        base = base + SANDY_SETBACK_SURCHARGE_FT
    return base


def well_setback_evaluation(qualifying_wells, drainfield_x, drainfield_y,
                            system_type, soil_group):
    """Returns (nearest_well_distance_ft, required_setback_ft, setback_status)."""
    setback = required_setback(system_type, soil_group)
    if not qualifying_wells:
        return None, setback, "NOT_APPLICABLE"
    nearest = min(distance_ft(w["location_x_ft"], w["location_y_ft"],
                              drainfield_x, drainfield_y)
                  for w in qualifying_wells)
    status = "COMPLIANT" if nearest >= setback else "VARIANCE_REQUIRED"
    return nearest, setback, status


# ----------------------------------------------------------------- permit fee
def construction_permit_fee(flow_gpd, system_type, setback_status):
    line_items = [
        Decimal(PERMIT_BASE_REVIEW_CENTS),
        Decimal(flow_gpd) * Decimal(PERMIT_FLOW_RATE_CENTS_PER_GPD),
        Decimal(SYSTEM_TYPE_SURCHARGE_CENTS[system_type]),
        Decimal(PERMIT_VARIANCE_CENTS if setback_status == "VARIANCE_GRANTED" else 0),
    ]
    combined = Decimal(1) + STATE_SURCHARGE_RATE + COUNTY_TECH_FEE_RATE
    total = 0
    for item in line_items:
        total += int(round_half_up(item * combined, 0))
    return total


# ------------------------------------------------------------------ licensing
def contractor_effective_status(status, license_expires_on, clock):
    if status == "REVOKED":
        return "REVOKED"
    if status == "SUSPENDED":
        return "SUSPENDED"
    if clock > license_expires_on:
        return "EXPIRED"
    return "ACTIVE"


# ------------------------------------------------------------------ intervals
def contractor_slot_conflict(new_start, new_end, existing_start, existing_end):
    """Half-open windows with a one-sided 45-minute trailing travel buffer."""
    buffer_delta = TRAVEL_BUFFER_MINUTES * 60
    e_end = existing_end.timestamp() + buffer_delta
    n_end = new_end.timestamp() + buffer_delta
    return (new_start.timestamp() < e_end) and (existing_start.timestamp() < n_end)


def parcel_window_conflict(new_from, new_until, existing_from, existing_until):
    """Closed, unbuffered intervals."""
    return (new_from <= existing_until) and (existing_from <= new_until)


# -------------------------------------------------------------------- pumping
def pumping_interval(tank_capacity_gal, household_size, monitoring_required,
                     anchor):
    gpp = dec(tank_capacity_gal) / dec(household_size)
    if gpp >= TANK_GAL_PER_PERSON_TIER_1:
        base_months = 60
    elif gpp >= TANK_GAL_PER_PERSON_TIER_2:
        base_months = 48
    elif gpp >= TANK_GAL_PER_PERSON_TIER_3:
        base_months = 36
    elif gpp >= TANK_GAL_PER_PERSON_TIER_4:
        base_months = 24
    else:
        base_months = 12
    months = base_months // 2 if monitoring_required else base_months
    return months, add_months(anchor, months)


def pumping_compliance_status(clock, next_pumping_due_on):
    if next_pumping_due_on is None:
        return "COMPLIANT"
    days_until_due = whole_days_between(clock, next_pumping_due_on)
    if days_until_due < 0:
        return "DELINQUENT"
    if days_until_due <= PUMPING_DUE_SOON_DAYS:
        return "DUE_SOON"
    return "COMPLIANT"


# ----------------------------------------------------------------- risk tier
def parcel_risk_tier(water_quality_flag, open_repair_order_count,
                     any_delinquent, any_revoked):
    points = 0
    if water_quality_flag:
        points += WATER_FLAG_POINTS
    points += REPAIR_ORDER_POINTS * min(open_repair_order_count,
                                        REPAIR_ORDER_POINT_CAP)
    if any_delinquent:
        points += DELINQUENT_POINTS
    if any_revoked:
        points += REVOKED_POINTS
    if points >= HIGH_RISK_POINTS:
        return "HIGH"
    if points >= ELEVATED_RISK_POINTS:
        return "ELEVATED"
    return "LOW"


# --------------------------------------------------------------- repair order
def repair_order_severity_and_deadline(failure_type, water_quality_flag, clock):
    if failure_type == "GROUNDWATER_CONTAMINATION" or water_quality_flag:
        severity = "IMMINENT_HAZARD"
    elif failure_type in ("SURFACING_EFFLUENT", "BACKUP"):
        severity = "URGENT"
    else:
        severity = "ROUTINE"
    return severity, add_days(clock, REPAIR_DEADLINE_DAYS[severity])


# ------------------------------------------------------- transfer inspection
def transfer_inspection_charges(inspection_mode, expedited,
                                open_repair_order_count):
    subtotal = TRANSFER_BASE_FEE_CENTS
    if inspection_mode == "FIELD_VERIFIED":
        subtotal += FIELD_VERIFICATION_FEE_CENTS
    if open_repair_order_count > 0:
        subtotal += RECORDS_RESEARCH_FEE_CENTS
    if not expedited:
        expedite = 0
    else:
        if subtotal < EXPEDITE_TIER_1_CENTS:
            rate = EXPEDITE_RATE_LOW
        elif subtotal < EXPEDITE_TIER_2_CENTS:
            rate = EXPEDITE_RATE_MID
        else:
            rate = EXPEDITE_RATE_HIGH
        expedite = int(round_half_up(Decimal(subtotal) * rate, 0))
    return subtotal, expedite, subtotal + expedite


def transfer_certificate_grade(inspection_mode, open_repair_order_count,
                               permit_status, compliance_status,
                               water_quality_flag, tank_condition,
                               drainfield_condition):
    if open_repair_order_count > 0 or permit_status in ("SUSPENDED", "REVOKED",
                                                        "EXPIRED"):
        base = "UNSATISFACTORY"
    elif compliance_status in ("DUE_SOON", "DELINQUENT") or water_quality_flag:
        base = "CONDITIONAL"
    else:
        base = "SATISFACTORY"
    if inspection_mode == "DESK_REVIEW":
        return base
    if tank_condition == "POOR" or drainfield_condition == "POOR":
        return "UNSATISFACTORY"
    if tank_condition == "FAIR" or drainfield_condition == "FAIR":
        return "CONDITIONAL" if base == "SATISFACTORY" else base
    if (base == "CONDITIONAL" and compliance_status == "DUE_SOON"
            and not water_quality_flag):
        return "SATISFACTORY"
    return base
