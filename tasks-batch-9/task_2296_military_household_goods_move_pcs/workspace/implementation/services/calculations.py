"""Pure calculation rules (SCAFFOLD §1.3, PRD §2.6 and §3)."""

import math
from datetime import timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

# --------------------------------------------------------------------- constants

RANK_TIER_MAP = {
    "E1": "E1_E4",
    "E2": "E1_E4",
    "E3": "E1_E4",
    "E4": "E1_E4",
    "E5": "E5",
    "E6": "E6",
    "E7": "E7",
    "E8": "E8",
    "E9": "E9",
    "W1": "W1_O1",
    "O1": "W1_O1",
    "W2": "W2_O2",
    "O2": "W2_O2",
    "W3": "W3_O3",
    "O3": "W3_O3",
    "W4": "W4_O4",
    "O4": "W4_O4",
    "W5": "W5_O5",
    "O5": "W5_O5",
    "O6": "O6",
}

RANK_WEIGHT_TABLE = {
    "E1_E4": {"without": 5000, "with": 8000},
    "E5": {"without": 7000, "with": 9000},
    "E6": {"without": 8000, "with": 11000},
    "E7": {"without": 11000, "with": 13000},
    "E8": {"without": 12000, "with": 14000},
    "E9": {"without": 13000, "with": 15000},
    "W1_O1": {"without": 10000, "with": 12000},
    "W2_O2": {"without": 12500, "with": 13500},
    "W3_O3": {"without": 13000, "with": 14500},
    "W4_O4": {"without": 14000, "with": 17000},
    "W5_O5": {"without": 16000, "with": 17500},
    "O6": {"without": 18000, "with": 18000},
}

RANK_CODES = tuple(RANK_TIER_MAP.keys())
BRANCHES = ("ARMY", "NAVY", "AIR_FORCE", "MARINE_CORPS", "SPACE_FORCE", "COAST_GUARD")
MOVE_TYPES = ("PCS_CONUS", "PCS_OCONUS", "SEPARATION", "RETIREMENT", "LOCAL")
SESSION_TYPES = ("SELF_SERVICE", "VIRTUAL", "IN_PERSON")
SHIPMENT_METHODS = ("HHG", "UB", "NTS", "PPM")
ESTIMATE_METHODS = ("CUBE_X7", "INVENTORY_TABLE")
PRO_GEAR_OWNERS = ("MEMBER", "SPOUSE")
DOCUMENTATION_TYPES = ("ITEMIZED_INVENTORY", "EMPLOYER_LETTER", "ORDERS_EXTRACT", "NONE")
SIT_TYPES = ("ORIGIN", "DESTINATION")
CLAIM_TYPES = ("LOSS", "DAMAGE", "BOTH")
ITEM_CATEGORIES = ("ELECTRONICS", "FURNITURE", "APPLIANCE", "CLOTHING", "OTHER")
ITEM_DISPOSITIONS = ("ALLOWED", "DENIED")
PPM_ELECTED_BASES = ("AUTO", "INCENTIVE_BASIS", "ACTUAL_EXPENSE_BASIS")
NOTIFICATION_CHANNELS = ("EMAIL", "SMS", "PORTAL")

LOCAL_MOVE_FACTOR = Decimal("0.50")
SEPARATION_CAP_LBS = 13000
PRO_GEAR_MEMBER_CAP_LBS = 2000
PRO_GEAR_SPOUSE_CAP_LBS = 500

LBS_PER_CUBIC_FOOT = Decimal("7")
ACCESSORIAL_UPLIFT_PCT = Decimal("0.05")
REWEIGH_TRIGGER_RATIO = Decimal("1.10")

EXCESS_TIER_1_MAX_PCT = Decimal("0.10")
EXCESS_TIER_2_MAX_PCT = Decimal("0.25")
EXCESS_RATE_TIER_1 = Decimal("62.50")
EXCESS_RATE_TIER_2 = Decimal("78.00")
EXCESS_RATE_TIER_3 = Decimal("94.50")
ADMIN_FEE_THRESHOLD_USD = Decimal("500.00")
ADMIN_FEE_PCT = Decimal("0.06")
EXCESS_SUSPEND_THRESHOLD_USD = Decimal("2500.00")

PEAK_MIN_RESERVE_PCT = Decimal("0.25")
RESTRICT_UTILISATION_PCT = Decimal("0.90")

SHORT_NOTICE_DAYS = 5
SPREAD_SHORT_NOTICE = (0, 2)
SPREAD_PEAK = (2, 7)
SPREAD_STANDARD = (1, 4)
MILES_PER_TRANSIT_DAY = 300
PEAK_TRANSIT_ADD_DAYS = 2
MIN_TRANSIT_DAYS = 5

SIT_TIER_1_DAYS = 30
SIT_HANDLING_RATE_PER_CWT = Decimal("68.40")
SIT_DAILY_RATE_FIRST_30 = Decimal("1.05")
SIT_DAILY_RATE_AFTER_30 = Decimal("1.62")
FUEL_TIER_1_MAX_USD = Decimal("1000.00")
FUEL_TIER_2_MAX_USD = Decimal("5000.00")
FUEL_PCT_TIER_1 = 0.045
FUEL_PCT_TIER_2 = 0.062
FUEL_PCT_TIER_3 = 0.071
SIT_MAX_TOTAL_DAYS = 90

CATEGORY_DEPRECIATION_PCT = {
    "ELECTRONICS": 0.10,
    "FURNITURE": 0.05,
    "APPLIANCE": 0.07,
    "CLOTHING": 0.20,
    "OTHER": 0.06,
}
MIN_RESIDUAL_FACTOR = Decimal("0.20")
HIGH_VALUE_THRESHOLD_USD = Decimal("5000.00")
HIGH_VALUE_UNDOCUMENTED_CAP_USD = Decimal("5000.00")
MAX_CLAIM_PAYOUT_USD = Decimal("100000.00")
FRV_WINDOW_DAYS = 270
CLAIM_WINDOW_DAYS = 730
LOSS_NOTICE_WINDOW_DAYS = 180
WEIGHT_DISPUTE_WINDOW_DAYS = 45

GCC_BASE_RATE_PER_CWT = Decimal("42.75")
GCC_RATE_PER_CWT_PER_100MI = Decimal("3.85")
PPM_INCENTIVE_PCT = Decimal("0.95")

NOTIFICATION_SLA_HOURS = {
    "PACK_DATE_CONFIRMED": 72,
    "PICKUP_CONFIRMED": 24,
    "SIT_ENTRY": 24,
    "WEIGHT_RECON_COMPLETE": 168,
    "CLAIM_ACK": 120,
}
NOTIFICATION_TYPES = tuple(NOTIFICATION_SLA_HOURS.keys())

CLAIM_COUNT_PENALTY = Decimal("5.00")
SETTLEMENT_PENALTY_DIVISOR = Decimal("500.00")
TSP_PROBATION_SCORE = Decimal("70.00")
TSP_SUSPENSION_SCORE = Decimal("50.00")

COUNSELING_LEAD_DAYS = 14
CLAIM_INFO_REQUEST_LIMIT = 3
ORDER_AMENDMENT_LIMIT = 3
PRO_GEAR_RESUBMISSION_LIMIT = 2

ZERO = Decimal("0.00")

# ----------------------------------------------------------- rounding primitives


def money(value):
    """Round half up to cents."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def lbs_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def lbs_floor(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def cwt(pounds):
    """Freight is quoted per hundredweight; the divide is never rounded."""
    return Decimal(pounds) / Decimal(100)


def whole_days(start, end):
    """Count of complete 24-hour days between two instants, discarding partials."""
    return int(math.floor((end - start).total_seconds() / 86400.0))


def in_peak_window(instant):
    """True when the instant falls inside [May 15, Sep 30] of its own year."""
    return (5, 15) <= (instant.month, instant.day) <= (9, 30)


# ------------------------------------------------- entitlement weight allowance


def dependent_status_effective(dependents_count_at_issue, is_dependent_restricted):
    with_dependents = (dependents_count_at_issue or 0) >= 1 and not is_dependent_restricted
    return "WITH_DEPENDENTS" if with_dependents else "WITHOUT_DEPENDENTS"


def base_weight_allowance(rank_code, dep_status, move_type):
    tier = RANK_TIER_MAP[rank_code]
    key = "with" if dep_status == "WITH_DEPENDENTS" else "without"
    raw = RANK_WEIGHT_TABLE[tier][key]
    if move_type == "LOCAL":
        raw = lbs_floor(Decimal(raw) * LOCAL_MOVE_FACTOR)
    elif move_type in ("SEPARATION", "RETIREMENT"):
        raw = min(raw, SEPARATION_CAP_LBS)
    return raw


def spouse_allowance(dep_status, spouse_present):
    if dep_status == "WITH_DEPENDENTS" and spouse_present:
        return PRO_GEAR_SPOUSE_CAP_LBS
    return 0


# ------------------------------------------------------------ survey estimate


def survey_estimated_gross(room_estimates, estimate_method):
    raw_sum = 0
    for element in room_estimates:
        raw_sum += lbs_half_up(Decimal(str(element["cube_feet"])) * LBS_PER_CUBIC_FOOT)
    if estimate_method == "CUBE_X7":
        uplift = lbs_half_up(Decimal(raw_sum) * ACCESSORIAL_UPLIFT_PCT)
    else:
        uplift = 0
    return raw_sum + uplift


# ----------------------------------------------------------- excess weight cost


def excess_cost_breakdown(charged_lbs, cap_lbs, waived_usd):
    """Steps two to five of PRD §3.3."""
    excess_lbs = max(0, charged_lbs - cap_lbs)
    if cap_lbs > 0:
        pct_over = Decimal(excess_lbs) / Decimal(cap_lbs)
    else:
        pct_over = Decimal(0)
    if pct_over <= EXCESS_TIER_1_MAX_PCT:
        rate = EXCESS_RATE_TIER_1
    elif pct_over <= EXCESS_TIER_2_MAX_PCT:
        rate = EXCESS_RATE_TIER_2
    else:
        rate = EXCESS_RATE_TIER_3
    transport = money(cwt(excess_lbs) * rate)
    if transport < ADMIN_FEE_THRESHOLD_USD:
        admin_fee = ZERO
    else:
        admin_fee = money(transport * ADMIN_FEE_PCT)
    gross = money(transport + admin_fee)
    waived = money(waived_usd)
    if waived > gross:
        waived = gross
    due = money(gross - waived)
    if due < ZERO:
        due = ZERO
    return {
        "excess_weight_lbs": excess_lbs,
        "excess_pct_over": float(pct_over),
        "excess_rate_per_cwt": rate,
        "gross_transport_usd": transport,
        "admin_fee_usd": admin_fee,
        "gross_excess_cost_usd": gross,
        "excess_cost_waived_usd": waived,
        "excess_cost_due_usd": due,
    }


# --------------------------------------------------------------- capacity pools


def capacity_pools(total_capacity_lbs, short_notice_reserve_pct, peak_season):
    reserve = Decimal(str(short_notice_reserve_pct))
    if peak_season and reserve < PEAK_MIN_RESERVE_PCT:
        reserve = PEAK_MIN_RESERVE_PCT
    general = lbs_floor(Decimal(total_capacity_lbs) * (Decimal(1) - reserve))
    return float(reserve), general, total_capacity_lbs - general


def restrict_threshold(total_capacity_lbs):
    return lbs_floor(Decimal(total_capacity_lbs) * RESTRICT_UTILISATION_PCT)


# ------------------------------------------------------- spread window / transit


def spread_window(requested_pickup_date, booked_at, distance_miles):
    days_to_pickup = whole_days(booked_at, requested_pickup_date)
    is_short_notice = days_to_pickup < SHORT_NOTICE_DAYS
    peak_season = in_peak_window(requested_pickup_date)
    if is_short_notice:
        before_days, after_days = SPREAD_SHORT_NOTICE
    elif peak_season:
        before_days, after_days = SPREAD_PEAK
    else:
        before_days, after_days = SPREAD_STANDARD
    transit = int(math.ceil(distance_miles / float(MILES_PER_TRANSIT_DAY)))
    if peak_season:
        transit += PEAK_TRANSIT_ADD_DAYS
    transit = max(MIN_TRANSIT_DAYS, transit)
    return {
        "is_short_notice": is_short_notice,
        "peak_season": peak_season,
        "spread_start_date": requested_pickup_date - timedelta(days=before_days),
        "spread_end_date": requested_pickup_date + timedelta(days=after_days),
        "transit_days_allowed": transit,
    }


# ------------------------------------------------------------------ SIT pricing


def sit_costs(entry_date, release_date, total_authorized_days, billable_weight_lbs):
    days_used = max(1, whole_days(entry_date, release_date))
    excess_days = max(0, days_used - total_authorized_days)
    first_tier_days = min(days_used, SIT_TIER_1_DAYS)
    extra_days = max(0, days_used - SIT_TIER_1_DAYS)
    hundredweight = cwt(billable_weight_lbs)
    handling = money(hundredweight * SIT_HANDLING_RATE_PER_CWT)
    daily_first = money(hundredweight * SIT_DAILY_RATE_FIRST_30 * Decimal(first_tier_days))
    daily_extra = money(hundredweight * SIT_DAILY_RATE_AFTER_30 * Decimal(extra_days))
    base = money(handling + daily_first + daily_extra)
    if base < FUEL_TIER_1_MAX_USD:
        pct = FUEL_PCT_TIER_1
    elif base < FUEL_TIER_2_MAX_USD:
        pct = FUEL_PCT_TIER_2
    else:
        pct = FUEL_PCT_TIER_3
    surcharge = money(base * Decimal(str(pct)))
    total = money(base + surcharge)
    if excess_days == 0:
        liability = ZERO
    else:
        liability = money(total * Decimal(excess_days) / Decimal(days_used))
    return {
        "days_used": days_used,
        "excess_days": excess_days,
        "sit_base_cost_usd": base,
        "fuel_surcharge_pct": pct,
        "fuel_surcharge_usd": surcharge,
        "sit_total_cost_usd": total,
        "member_liability_usd": liability,
    }


# ------------------------------------------------------------ claim settlement


def item_settlement(item, settlement_basis):
    if item["disposition"] == "DENIED":
        return ZERO
    effective = Decimal(item["replacement_cost_usd"])
    if effective >= HIGH_VALUE_THRESHOLD_USD and not item["high_value_inventory_documented"]:
        effective = HIGH_VALUE_UNDOCUMENTED_CAP_USD
    if settlement_basis == "FULL_REPLACEMENT_VALUE":
        return money(effective)
    rate = Decimal(str(item["depreciation_rate_pct_per_year"]))
    age = Decimal(str(item["age_years"]))
    factor = Decimal(1) - rate * age
    if factor < MIN_RESIDUAL_FACTOR:
        factor = MIN_RESIDUAL_FACTOR
    return money(effective * factor)


def settlement_total(per_item_amounts):
    total = money(sum(per_item_amounts, ZERO))
    if total > MAX_CLAIM_PAYOUT_USD:
        total = MAX_CLAIM_PAYOUT_USD
    return total


# ------------------------------------------------------------------------- PPM


def gcc_amount(allowable_weight_lbs, distance_miles):
    rate = GCC_BASE_RATE_PER_CWT + GCC_RATE_PER_CWT_PER_100MI * (
        Decimal(distance_miles) / Decimal(100)
    )
    return money(cwt(allowable_weight_lbs) * rate)


# --------------------------------------------------------------- TSP performance


def performance_score(settled_claim_count, claim_settlement_total_usd):
    raw = (
        Decimal("100.00")
        - Decimal(settled_claim_count) * CLAIM_COUNT_PENALTY
        - Decimal(claim_settlement_total_usd) / SETTLEMENT_PENALTY_DIVISOR
    )
    score = money(raw)
    if score < ZERO:
        score = ZERO
    return score


def standing_for_score(score):
    if score < TSP_SUSPENSION_SCORE:
        return "SUSPENDED"
    if score < TSP_PROBATION_SCORE:
        return "PROBATION"
    return "ACTIVE"
