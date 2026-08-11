"""Every derived number in the specification, in one place.

Named constants are PRD section 2.10 verbatim.
"""

from decimal import Decimal

from core import (
    ApiError, add_days, cents, d, db, floor_div, hours_between,
    round_half_up, whole_days_between,
)

# ---- named constants (PRD 2.10) ------------------------------------------
TAX_RATE_PCT = d("7.25")
LOYALTY_DISCOUNT_PCT = d("5.00")
LOYALTY_DISCOUNT_MIN_PRETAX_CENTS = 200000
LOYALTY_DISCOUNT_ELIGIBLE_TIERS = ("SELECT", "PREMIER")
CREDIT_HOLD_THRESHOLD_CENTS = 500000
QUOTE_VALIDITY_DAYS = 30
INSPECTION_VALIDITY_DAYS = 365
PART_WARRANTY_DAYS = 365
LABOR_WARRANTY_DAYS = 90
CALLBACK_MAX_PER_COVERAGE = 2
TRAVEL_BUFFER_MINUTES = 45
WELL_DAILY_WORK_ORDER_CAP = 1
MAX_WORK_ORDER_DURATION_MINUTES = 720
BILLING_INCREMENT_MINUTES = 15
MIN_BILLABLE_MINUTES = 60
NON_WELL_CAUSE_LABOR_CAP_MINUTES = 60
PART_MAX_LINE_QUANTITY = 50
SHARED_WELL_MAX_PARTIES = 4
POST_HOC_PERMIT_WINDOW_DAYS = 10
RETEST_WINDOW_DAYS = 21
RECOMMENDATION_VALIDITY_DAYS = 180
SALT_TANK_CAPACITY_LBS = d("300")
SALT_REORDER_THRESHOLD_LBS = d("40")
SALT_DELIVERY_MIN_LBS = d("40")
FILTER_MIN_DAYS_BETWEEN_CHANGES = 30
MIN_MAINTENANCE_INTERVAL_DAYS = 120
YIELD_SAFETY_FACTOR = d("0.80")
MIN_PUMP_GPM = d("5.0")
PEAK_DEMAND_GAL_PER_HOUR = d("30")
MIN_DRAWDOWN_GALLONS = d("1.0")
SALT_LBS_PER_CONSUMABLE_UNIT = d("40.0")
HARDNESS_TREATMENT_TRIGGER_GPG = d("7.0")
NITRATE_MCL_MG_L = d("10.0")
ARSENIC_MCL_MG_L = d("0.010")
LEAD_MCL_MG_L = d("0.015")
IRON_MCL_MG_L = d("0.30")
HOLD_TIME_HOURS_BACTERIOLOGICAL = d("30")
HOLD_TIME_HOURS_CHEMICAL = d("336")
WATER_USE_GAL_PER_PERSON_PER_DAY = d("75")
REGEN_INTERVAL_DAYS = d("7")
EXPEDITE_FEE_CENTS = 15000
SEVERITY_MAX = 100


# ---- trip fee zones (PRD 3.1) --------------------------------------------

def service_zone(distance_miles):
    miles = d(distance_miles)
    if miles <= d("15.0"):
        return "ZONE_1"
    if miles <= d("35.0"):
        return "ZONE_2"
    if miles <= d("60.0"):
        return "ZONE_3"
    return "OUT_OF_AREA"


TRIP_FEE_CENTS = {"ZONE_1": 8500, "ZONE_2": 12500, "ZONE_3": 18000, "OUT_OF_AREA": 0}


def trip_fee_cents(prop):
    return TRIP_FEE_CENTS[service_zone(prop["distance_miles"])]


# ---- duty cycle (PRD 3.1) -------------------------------------------------

def duty_cycle_ratio(drawdown_gallons):
    divisor = max(d(drawdown_gallons), MIN_DRAWDOWN_GALLONS)
    return round_half_up(PEAK_DEMAND_GAL_PER_HOUR / divisor, 2)


def duty_cycle_class(ratio):
    ratio = d(ratio)
    if ratio <= d("3.00"):
        return "LOW"
    if ratio <= d("6.00"):
        return "MODERATE"
    return "HIGH"


def apply_duty_cycle(well):
    ratio = duty_cycle_ratio(well["pressure_tank_drawdown_gallons"])
    well["duty_cycle_ratio"] = float(ratio)
    well["duty_cycle_class"] = duty_cycle_class(ratio)


# ---- labour ladder (PRD 3.5) ---------------------------------------------

BASE_RATE_CENTS = {"APPRENTICE": 6500, "JOURNEYMAN": 9500, "MASTER": 13500}
BAND_MULTIPLIER = {
    "STANDARD": d("1.00"),
    "EVENING": d("1.35"),
    "NIGHT": d("1.75"),
    "WEEKEND": d("1.50"),
}


def labor_time_band(instant):
    if instant.isoweekday() in (6, 7):
        return "WEEKEND"
    hour = instant.hour
    if 8 <= hour < 17:
        return "STANDARD"
    if 17 <= hour < 22:
        return "EVENING"
    return "NIGHT"


def labor_rate_cents_per_hour(tier, band):
    return cents(d(BASE_RATE_CENTS[tier]) * BAND_MULTIPLIER[band])


def billable_minutes(raw_minutes, non_well_cause=False):
    raw = int(raw_minutes)
    increments = -(-raw // BILLING_INCREMENT_MINUTES)
    rounded = increments * BILLING_INCREMENT_MINUTES
    result = max(rounded, MIN_BILLABLE_MINUTES)
    if non_well_cause:
        result = min(result, NON_WELL_CAUSE_LABOR_CAP_MINUTES)
    return result


def labor_charge_cents(rate_cents, minutes):
    return cents(d(rate_cents) * d(minutes) / d(60))


# ---- parts ladder (PRD 3.5) ----------------------------------------------

def parts_markup_pct(unit_cost_cents):
    cost = d(unit_cost_cents)
    if cost <= 5000:
        return d("0.60")
    if cost <= 25000:
        return d("0.40")
    if cost <= 100000:
        return d("0.28")
    return d("0.18")


def parts_unit_price_cents(unit_cost_cents):
    markup = parts_markup_pct(unit_cost_cents)
    return markup, cents(d(unit_cost_cents) * (d(1) + markup))


def price_line(row, unit_cost):
    markup, unit_price = parts_unit_price_cents(unit_cost)
    row["markup_pct_applied"] = float(markup)
    row["unit_price_cents"] = unit_price
    row["extended_price_cents"] = unit_price * int(row["quantity"])
    return row


# ---- emergency severity chain (PRD 3.8) ----------------------------------

CAUSE_POINTS = {
    "WELL_DRY": 45,
    "PUMP_FAILURE": 40,
    "PRESSURE_TANK_FAILURE": 30,
    "CONTROL_FAILURE": 25,
    "TREATMENT_FAILURE": 20,
    "NON_WELL_CAUSE": 5,
}


def severity_score(cause_class, reported_outage_hours, household_size, vulnerable):
    cause = CAUSE_POINTS[cause_class]
    outage = min(int(d(reported_outage_hours)) * 3, 30)
    household = min(int(household_size) * 3, 15)
    vuln = 10 if vulnerable else 0
    return min(cause + outage + household + vuln, SEVERITY_MAX)


def dispatch_surcharge_cents(score):
    if score <= 29:
        return 7000
    if score <= 59:
        return 14000
    return 24000


def membership_credit_cents(tier, surcharge, score):
    if tier == "PREMIER":
        if score >= 60:
            return min(surcharge, 20000)
        return 0
    if tier == "SELECT":
        return min(surcharge, 5000)
    return 0


def net_dispatch_charge_cents(surcharge, credit, cause_class):
    if cause_class == "NON_WELL_CAUSE":
        return 0
    return max(surcharge - credit, 0)


PREAUTH_CAP_CENTS = {"NONE": 75000, "SELECT": 100000, "PREMIER": 150000}


# ---- maintenance interval (PRD 3.10) -------------------------------------

BASE_INTERVAL_DAYS = {"LOW": 365, "MODERATE": 270, "HIGH": 180}
MEDIA_REDUCTION_DAYS = {"NONE": 0, "SEDIMENT": 30, "CARBON": 90, "SOFTENER_RESIN": 0}
FILTER_INTERVAL_DAYS = {"SEDIMENT": 90, "CARBON": 180, "SOFTENER_RESIN": 1825}


def maintenance_interval_days(duty_class, media):
    base = BASE_INTERVAL_DAYS[duty_class]
    reduction = MEDIA_REDUCTION_DAYS[media]
    return max(base - reduction, MIN_MAINTENANCE_INTERVAL_DAYS)


def next_due_at(plan):
    return add_days(plan["last_service_date"], plan["interval_days_as_operated"])


def filter_next_due_date(plan):
    if plan["filter_media"] == "NONE":
        return None
    if plan["last_filter_change_date"] is None:
        return None
    return add_days(plan["last_filter_change_date"],
                    FILTER_INTERVAL_DAYS[plan["filter_media"]])


def salt_next_due_date(plan):
    monthly = d(plan["monthly_salt_lbs"])
    if monthly <= 0:
        return None
    if plan["last_salt_delivery_date"] is None:
        return None
    surplus = d(plan["salt_remaining_lbs"]) - SALT_REORDER_THRESHOLD_LBS
    if surplus <= 0:
        days = 0
    else:
        days = floor_div(surplus * d(30) / monthly)
    return add_days(plan["last_salt_delivery_date"], days)


def recompute_operated_interval(plan, well):
    plan["interval_days_as_operated"] = maintenance_interval_days(
        well["duty_cycle_class"], plan["filter_media"])
    plan["next_due_at"] = next_due_at(plan)


# ---- water quality (PRD 3.3) ---------------------------------------------

HOLD_TIME_HOURS = {
    "BACTERIOLOGICAL": HOLD_TIME_HOURS_BACTERIOLOGICAL,
    "CHEMICAL": HOLD_TIME_HOURS_CHEMICAL,
}


def hold_time_valid(panel_type, sample_datetime, analyzed_at):
    return hours_between(sample_datetime, analyzed_at) <= HOLD_TIME_HOURS[panel_type]


def chemical_exceedance(test):
    checks = (
        (test.get("nitrate_mg_l"), NITRATE_MCL_MG_L),
        (test.get("arsenic_mg_l"), ARSENIC_MCL_MG_L),
        (test.get("lead_mg_l"), LEAD_MCL_MG_L),
        (test.get("iron_mg_l"), IRON_MCL_MG_L),
    )
    for value, limit in checks:
        if value is not None and d(value) > limit:
            return True
    return False


# ---- treatment recommendation (PRD 3.4) ----------------------------------

def recommended_media_selection(test):
    hardness = test.get("hardness_gpg")
    if hardness is not None and d(hardness) >= HARDNESS_TREATMENT_TRIGGER_GPG:
        return "SOFTENER_RESIN"
    iron = test.get("iron_mg_l")
    if iron is not None and d(iron) > IRON_MCL_MG_L:
        return "SEDIMENT"
    nitrate = test.get("nitrate_mg_l")
    arsenic = test.get("arsenic_mg_l")
    lead = test.get("lead_mg_l")
    if (nitrate is not None and d(nitrate) > NITRATE_MCL_MG_L) \
            or (arsenic is not None and d(arsenic) > ARSENIC_MCL_MG_L) \
            or (lead is not None and d(lead) > LEAD_MCL_MG_L):
        return "CARBON"
    return None


def softener_design_grains(hardness_gpg, household_size):
    total = (d(hardness_gpg) * d(household_size)
             * WATER_USE_GAL_PER_PERSON_PER_DAY * REGEN_INTERVAL_DAYS)
    return int(round_half_up(total, 0))


CAPACITY_BANDS = [
    (24000, "CAP_24000", 6),
    (32000, "CAP_32000", 9),
    (48000, "CAP_48000", 12),
    (64000, "CAP_64000", 15),
    (80000, "CAP_80000", 18),
]


def softener_capacity_selection(design_grains):
    for ceiling, name, salt in CAPACITY_BANDS:
        if design_grains <= ceiling:
            return name, salt
    return "DUAL_TANK_64000", 15


def softener_monthly_salt_lbs(salt_lbs_per_regen):
    return float(round_half_up(d(salt_lbs_per_regen) * d(30) / REGEN_INTERVAL_DAYS, 1))


def recommendation_expires_at(sample_datetime):
    return add_days(sample_datetime, RECOMMENDATION_VALIDITY_DAYS)


def recommendation_status_effective(rec):
    if rec["status"] == "PROPOSED" and db.clock >= rec["expires_at"]:
        return "EXPIRED"
    return rec["status"]


# ---- warranty (PRD 3.12) -------------------------------------------------

WARRANTY_WINDOW_DAYS = {"PART": PART_WARRANTY_DAYS, "LABOR": LABOR_WARRANTY_DAYS}


def coverage_expires_at(starts_at, coverage_class):
    return add_days(starts_at, WARRANTY_WINDOW_DAYS[coverage_class])


def coverage_state(coverage):
    if coverage["status"] == "ACTIVE" and db.clock > coverage["expires_at"]:
        return "EXPIRED"
    return coverage["status"]


# ---- permits (PRD 3.7) ---------------------------------------------------

PERMIT_REQUIRED_SCOPES = ("NEW_WELL", "PUMP_REPLACEMENT", "PRESSURE_TANK",
                          "TREATMENT_INSTALL")
JURISDICTION_TIER = {
    "JUR_ALPHA": "TIER_A",
    "JUR_BRAVO": "TIER_B",
    "JUR_CHARLIE": "TIER_C",
    "JUR_DELTA": "TIER_B",
}
TIER_BASE_FEE_CENTS = {"TIER_A": 35000, "TIER_B": 22000, "TIER_C": 12000}
SCOPE_MULTIPLIER = {
    "NEW_WELL": d("3.0"),
    "PUMP_REPLACEMENT": d("1.0"),
    "PRESSURE_TANK": d("0.5"),
    "TREATMENT_INSTALL": d("0.75"),
    "REPAIR": d("0.0"),
}


def permit_fee_cents(jurisdiction_code, scope, expedited):
    tier = JURISDICTION_TIER[jurisdiction_code]
    base = d(TIER_BASE_FEE_CENTS[tier])
    fee = cents(base * SCOPE_MULTIPLIER[scope])
    if expedited:
        fee += EXPEDITE_FEE_CENTS
    return tier, fee


# ---- scheduling gates (PRD 3.9) ------------------------------------------

TIER_RANK = {"APPRENTICE": 1, "JOURNEYMAN": 2, "MASTER": 3}
SCOPE_TIERS = {
    "NEW_WELL": ("MASTER",),
    "PUMP_REPLACEMENT": ("MASTER",),
    "TREATMENT_INSTALL": ("JOURNEYMAN", "MASTER"),
    "PRESSURE_TANK": ("APPRENTICE", "JOURNEYMAN", "MASTER"),
    "REPAIR": ("APPRENTICE", "JOURNEYMAN", "MASTER"),
    "MAINTENANCE": ("APPRENTICE", "JOURNEYMAN", "MASTER"),
}


# ---- account ledger (PRD 2.12) -------------------------------------------

def rederive_credit_hold(account):
    account["credit_hold"] = account["balance_cents"] > CREDIT_HOLD_THRESHOLD_CENTS
