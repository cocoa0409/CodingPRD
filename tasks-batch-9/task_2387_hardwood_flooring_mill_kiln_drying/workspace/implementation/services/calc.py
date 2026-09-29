"""Every calculation in the specification, with the rounding pinned exactly.

All rounding is half up (PRD 2.6): a value exactly on the midpoint rounds away
from zero. Rounding happens at the points named, in the order named, and no
step is algebraically collapsed into another.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal(0)


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    """ROUND_HALF_UP to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(rhu(value, 0))


# --------------------------------------------------------------------------
# Species / schedule constants
# --------------------------------------------------------------------------
SPECIES_BASE_HOURS = {"DENSE": D(96), "MEDIUM": D(72), "SOFT": D(54)}
MC_HOURS_PER_POINT = {"DENSE": D("3.5"), "MEDIUM": D("2.5"), "SOFT": D("1.8")}
GREEN_TO_DRY_SHRINK_PCT = {"DENSE": D("7.5"), "MEDIUM": D("6.0"), "SOFT": D("5.0")}
MIN_SCHEDULE_HOURS = D("48")
MAX_SCHEDULE_HOURS = D("360")

COOLDOWN_BUFFER_HOURS = D(6)
REDRY_EXTENSION_HOURS = D(48)
MAX_REDRY_CYCLES = 2

MC_PLAN_TOLERANCE_PP = D("3.0")
TARGET_MC_BAND_PP = D("1.0")

INSERVICE_MC_PCT = D("7.5")
MILL_KERF_ALLOWANCE_IN = D("0.0625")
PROFILE_TOLERANCE_IN = D("0.006")

CORE_SF_PER_BF = D("1.10")

BF_PER_TON = D(285)
MAX_WASTE_PCT = D(12)

YIELD_FLOOR_PCT = D("55.00")

GRADE_CREDIT = {
    "CLEAR": D("1.00"),
    "SELECT": D("0.95"),
    "NO1_COMMON": D("0.85"),
    "NO2_COMMON": D("0.70"),
    "CHARACTER": D("0.60"),
    "CABIN": D("0.40"),
}
GRADE_PRICE_CENTS_PER_BF = {
    "CLEAR": D(640),
    "SELECT": D(520),
    "NO1_COMMON": D(395),
    "NO2_COMMON": D(280),
    "CHARACTER": D(240),
    "CABIN": D(150),
}

COAT_L_PER_SQFT = D("0.012")
MAX_PREFINISH_WINDOW_HOURS = 24

HAUL_BASE_CENTS = 2500
HAUL_CENTS_PER_MI = 180

REMEDIATION_LABOR_CENTS_PER_SF = D(475)
DEPRECIATION_PP_PER_MONTH = D("0.5")
MAX_DEPRECIATION_PCT = D(40)

RH_MIN_PCT = D(30)
RH_MAX_PCT = D(50)
RH_PENALTY_PP = D(10)

WARRANTY_RESTRICT_FLOOR_CENTS = 500000
WARRANTY_MONTHS = 60
MAX_OPEN_CLAIMS = 3


# --------------------------------------------------------------------------
# kiln_schedule_duration
# --------------------------------------------------------------------------
def thickness_tier_factor(thickness_in):
    thickness = D(thickness_in)
    if thickness <= D("1.00"):
        return D("1.00")
    if thickness <= D("1.25"):
        return D("1.45")
    if thickness <= D("1.50"):
        return D("1.95")
    return D("2.60")


def kiln_schedule_duration(density_class, thickness_in, initial_moisture_pct,
                           final_moisture_pct, conditioning_hours, stress_relief_hours):
    base = SPECIES_BASE_HOURS[density_class]
    per_point = MC_HOURS_PER_POINT[density_class]
    tier = thickness_tier_factor(thickness_in)
    drying_leg = (base + per_point * (D(initial_moisture_pct) - D(final_moisture_pct))) * tier
    raw = drying_leg + D(conditioning_hours) + D(stress_relief_hours)
    hours = rhu(raw, 1)
    if hours < MIN_SCHEDULE_HOURS:
        hours = rhu(MIN_SCHEDULE_HOURS, 1)
    elif hours > MAX_SCHEDULE_HOURS:
        hours = rhu(MAX_SCHEDULE_HOURS, 1)
    return hours


# --------------------------------------------------------------------------
# charge_occupancy_window
# --------------------------------------------------------------------------
def add_hours(instant, hours):
    seconds = int(rhu(D(hours) * 3600, 0))
    return instant + timedelta(seconds=seconds)


def occupancy_window(planned_start_utc, planned_dry_hours):
    planned_end = add_hours(planned_start_utc, planned_dry_hours)
    blocked_until = add_hours(planned_end, COOLDOWN_BUFFER_HOURS)
    return planned_end, blocked_until


def cooldown_from_end(planned_end_utc):
    return add_hours(planned_end_utc, COOLDOWN_BUFFER_HOURS)


# --------------------------------------------------------------------------
# chamber_window_conflict_detection -- CLOSED interval on both ends
# --------------------------------------------------------------------------
CHAMBER_OCCUPYING_STATUSES = ("SCHEDULED", "LOADED", "DRYING", "CONDITIONING", "REDRY", "RELEASED")


def windows_conflict(candidate_start, candidate_blocked_until, other_start, other_blocked_until):
    return candidate_start <= other_blocked_until and candidate_blocked_until >= other_start


# --------------------------------------------------------------------------
# weighted_initial_moisture
# --------------------------------------------------------------------------
def weighted_initial_moisture(receipts):
    total_bf = sum(int(r["accepted_board_feet"]) for r in receipts)
    if not receipts or total_bf == 0:
        return total_bf, None
    numerator = ZERO
    for receipt in receipts:
        numerator += D(receipt["accepted_board_feet"]) * D(receipt["moisture_pct_at_receipt"])
    return total_bf, rhu(numerator / D(total_bf), 1)


# --------------------------------------------------------------------------
# moisture_plan_deviation_check
# --------------------------------------------------------------------------
def moisture_plan_deviation(weighted_initial_moisture_pct, schedule_initial_moisture_pct):
    return abs(rhu(weighted_initial_moisture_pct, 1) - rhu(schedule_initial_moisture_pct, 1))


# --------------------------------------------------------------------------
# moisture_gradient_assessment
# --------------------------------------------------------------------------
def moisture_gradient_assessment(shell_moisture_pct, core_moisture_pct,
                                 max_moisture_gradient_pp, target_moisture_pct):
    shell = D(shell_moisture_pct)
    core = D(core_moisture_pct)
    gradient = rhu(abs(core - shell), 1)
    average = rhu((core + shell) / D(2), 1)
    released = gradient <= D(max_moisture_gradient_pp) and \
        abs(average - D(target_moisture_pct)) <= TARGET_MC_BAND_PP
    return gradient, average, released


# --------------------------------------------------------------------------
# dry_yield_conversion
# --------------------------------------------------------------------------
def dry_yield_conversion(charged_green_bf, density_class):
    shrink = GREEN_TO_DRY_SHRINK_PCT[density_class]
    return rhu(D(charged_green_bf) * (D(1) - shrink / D(100)), 2)


# --------------------------------------------------------------------------
# dimensional_shrinkage_plan
# --------------------------------------------------------------------------
def dimensional_shrinkage_plan(nominal_width_in, tangential_shrinkage_coefficient, lot_mc):
    nominal = D(nominal_width_in)
    coefficient = D(tangential_shrinkage_coefficient)
    reference = D(lot_mc)
    movement = rhu(nominal * coefficient * abs(reference - INSERVICE_MC_PCT) / D(100), 4)
    if reference < INSERVICE_MC_PCT:
        planned = rhu(nominal - MILL_KERF_ALLOWANCE_IN + movement, 3)
    else:
        planned = rhu(nominal - MILL_KERF_ALLOWANCE_IN - movement, 3)
    return movement, planned


# --------------------------------------------------------------------------
# core_reservation
# --------------------------------------------------------------------------
def core_reservation(input_dry_bf):
    return rhu(D(input_dry_bf) * CORE_SF_PER_BF, 2)


# --------------------------------------------------------------------------
# mill_mass_balance
# --------------------------------------------------------------------------
def mill_mass_balance(input_dry_bf, net_flooring_bf, shorts_bf, sawdust_tons, shavings_tons):
    residue_bf = rhu((D(sawdust_tons) + D(shavings_tons)) * BF_PER_TON, 2)
    waste_bf = rhu(D(input_dry_bf) - D(net_flooring_bf) - D(shorts_bf) - residue_bf, 2)
    waste_limit_bf = rhu(D(input_dry_bf) * MAX_WASTE_PCT / D(100), 2)
    return residue_bf, waste_bf, waste_limit_bf


def shorts_tons(shorts_bf):
    return rhu(D(shorts_bf) / BF_PER_TON, 2)


# --------------------------------------------------------------------------
# lot_yield_dual_variant
# --------------------------------------------------------------------------
def yield_pct(numerator_bf, input_dry_bf):
    denominator = D(input_dry_bf)
    if denominator == 0:
        return rhu(ZERO, 2)
    return rhu(D(numerator_bf) / denominator * D(100), 2)


# --------------------------------------------------------------------------
# grade_tally_valuation
# --------------------------------------------------------------------------
def length_factor(average_length_in):
    length = D(average_length_in)
    if length < D(24):
        return D("0.83")
    if length < D(48):
        return D("1.00")
    return D("1.07")


def bundle_valuation(grade_class, bundle_board_feet, average_length_in):
    factor = length_factor(average_length_in)
    credit = GRADE_CREDIT[grade_class]
    price = GRADE_PRICE_CENTS_PER_BF[grade_class]
    value_cents = rhu_cents(D(bundle_board_feet) * price * factor)
    return factor, credit, value_cents


def run_tally(bundles):
    tally_board_feet = rhu(sum((D(b["bundle_board_feet"]) for b in bundles), ZERO), 2)
    credited = rhu(sum((D(b["bundle_board_feet"]) * D(b["credit_factor"]) for b in bundles), ZERO), 4)
    tally_value_cents = sum(int(b["tally_value_cents"]) for b in bundles)
    return tally_board_feet, credited, tally_value_cents


# --------------------------------------------------------------------------
# prefinish_coating_consumption
# --------------------------------------------------------------------------
def coating_liters(scheduled_linear_feet, actual_milled_width_in, coating_passes):
    square_feet = D(scheduled_linear_feet) * D(actual_milled_width_in) / D(12)
    return rhu(square_feet * COAT_L_PER_SQFT * D(coating_passes), 2)


# --------------------------------------------------------------------------
# prefinish_line_load_check -- HALF-OPEN interval
# --------------------------------------------------------------------------
PREFINISH_LOADING_STATUSES = ("SCHEDULED", "HELD", "RUNNING")


def prefinish_windows_overlap(existing_start, existing_end, candidate_start, candidate_end):
    return existing_start < candidate_end and candidate_start < existing_end


# --------------------------------------------------------------------------
# byproduct_settlement
# --------------------------------------------------------------------------
def byproduct_discount_pct(quantity_tons):
    quantity = D(quantity_tons)
    if quantity < D(5):
        return D(0)
    if quantity < D(20):
        return D(3)
    return D(6)


def byproduct_settlement(quantity_tons, unit_price_cents_per_ton, haul_distance_miles):
    gross_cents = rhu_cents(D(quantity_tons) * D(unit_price_cents_per_ton))
    discount_pct = byproduct_discount_pct(quantity_tons)
    discount_cents = rhu_cents(D(gross_cents) * discount_pct / D(100))
    haul_cents = HAUL_BASE_CENTS + HAUL_CENTS_PER_MI * int(haul_distance_miles)
    net_cents = gross_cents - discount_cents + haul_cents
    return gross_cents, discount_cents, haul_cents, net_cents


# --------------------------------------------------------------------------
# warranty_liability_dual_variant
# --------------------------------------------------------------------------
def admin_pct_tier(base_cents):
    base = D(base_cents)
    if base < D(500000):
        return D("0.08")
    if base <= D(1500000):
        return D("0.06")
    return D("0.045")


def estimated_liability(affected_square_feet, material_value_cents_per_sf):
    base_cents = rhu_cents(D(affected_square_feet) *
                           (D(material_value_cents_per_sf) + REMEDIATION_LABOR_CENTS_PER_SF))
    admin_pct = admin_pct_tier(base_cents)
    admin_cents = rhu_cents(D(base_cents) * admin_pct)
    return base_cents + admin_cents


def whole_months_between(start_date, end_date):
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if end_date.day < start_date.day:
        months -= 1
    return months


def adjudicated_liability(adjudicated_affected_sf, material_value_cents_per_sf,
                          service_months, mill_share_pct):
    base_cents = rhu_cents(D(adjudicated_affected_sf) *
                           (D(material_value_cents_per_sf) + REMEDIATION_LABOR_CENTS_PER_SF))
    admin_pct = admin_pct_tier(base_cents)
    admin_cents = rhu_cents(D(base_cents) * admin_pct)
    gross_cents = base_cents + admin_cents
    depreciation_pct = DEPRECIATION_PP_PER_MONTH * D(service_months)
    if depreciation_pct > MAX_DEPRECIATION_PCT:
        depreciation_pct = MAX_DEPRECIATION_PCT
    depreciated_cents = rhu_cents(D(gross_cents) * (D(1) - depreciation_pct / D(100)))
    liability_cents = rhu_cents(D(depreciated_cents) * D(mill_share_pct) / D(100))
    return depreciation_pct, liability_cents


# --------------------------------------------------------------------------
# responsibility_split
# --------------------------------------------------------------------------
def installer_share_tier(mc_delta):
    delta = D(mc_delta)
    if delta <= D("2.0"):
        return D(0)
    if delta <= D("4.0"):
        return D(40)
    if delta <= D("6.0"):
        return D(70)
    return D(100)


def responsibility_split(adjudicated_subfloor_moisture_pct, reference_mc, adjudicated_ambient_rh_pct):
    mc_delta = rhu(abs(D(adjudicated_subfloor_moisture_pct) - D(reference_mc)), 1)
    installer = installer_share_tier(mc_delta)
    ambient = D(adjudicated_ambient_rh_pct)
    if ambient < RH_MIN_PCT or ambient > RH_MAX_PCT:
        installer = min(installer + RH_PENALTY_PP, D(100))
    mill = D(100) - installer
    return mc_delta, installer, mill


# --------------------------------------------------------------------------
# product_line_posture
# --------------------------------------------------------------------------
def derive_posture(warranty_balance_cents, freeze_override):
    if freeze_override:
        return "FROZEN"
    if int(warranty_balance_cents) < WARRANTY_RESTRICT_FLOOR_CENTS:
        return "RESTRICTED"
    return "OPEN"
