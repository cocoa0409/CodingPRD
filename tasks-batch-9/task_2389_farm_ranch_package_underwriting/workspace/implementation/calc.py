"""All derived quantities (PRD §3.3 - §3.9).

Money is integer cents; every rounding step is round-half-up.
"""

from decimal import Decimal, ROUND_HALF_UP

ONE = Decimal(1)
CENT = Decimal(1)
TWO_DP = Decimal("0.01")
SIX_DP = Decimal("0.000001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value if value is not None else 0)


def rhu(value):
    """round_half_up to a whole cent, returned as int."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def rhu2(value):
    return dec(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def rhu6(value):
    return dec(value).quantize(SIX_DP, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------- scheduled item

DEP_RATE_PER_YEAR = {
    "DWELLING": Decimal("0.015"),
    "FARM_STRUCTURE": Decimal("0.025"),
    "EQUIPMENT": Decimal("0.070"),
    "STORED_CROP": Decimal("0"),
    "HAY": Decimal("0"),
    "INPUTS": Decimal("0"),
}
MAX_DEP_PCT = Decimal("0.60")
CONDITION_FACTOR = {
    "A": Decimal("1.00"),
    "B": Decimal("0.92"),
    "C": Decimal("0.80"),
    "D": Decimal("0.45"),
}
SALVAGE_FLOOR_PCT = Decimal("0.20")
CLASS_CAP_CENTS = {
    "DWELLING": 120000000,
    "FARM_STRUCTURE": 60000000,
    "EQUIPMENT": 40000000,
    "STORED_CROP": 25000000,
    "HAY": 15000000,
    "INPUTS": 10000000,
}
SEASONAL_CLASSES = ("STORED_CROP", "HAY", "INPUTS")


def in_peak(start_month, end_month, month):
    if start_month is None:
        return False
    if end_month is None:
        return False
    if start_month <= end_month:
        return start_month <= month <= end_month
    return month >= start_month or month <= end_month


def effective_value_cents(item, valuation_dt):
    month = valuation_dt.month
    if in_peak(item.get("peak_season_start_month"), item.get("peak_season_end_month"), month):
        return dec(item.get("peak_season_value_cents"))
    return dec(item.get("stated_value_cents"))


def scheduled_item_insured_value(item, valuation_dt):
    """PRD §3.3: seasonal effective value, RC/ACV branch, class cap, one rounding."""
    effective = effective_value_cents(item, valuation_dt)
    cap = dec(CLASS_CAP_CENTS[item["item_class"]])
    if item["valuation_basis"] == "RC":
        return rhu(min(effective, cap))
    dep_pct = min(MAX_DEP_PCT, DEP_RATE_PER_YEAR[item["item_class"]] * dec(item["age_years"]))
    depreciated = effective * (ONE - dep_pct) * CONDITION_FACTOR[item["condition_grade"]]
    salvage_floor = effective * SALVAGE_FLOOR_PCT
    return rhu(min(max(depreciated, salvage_floor), cap))


# ------------------------------------------------------------- property premium

PROP_RATE = {
    "DWELLING": Decimal("0.0040"),
    "FARM_STRUCTURE": Decimal("0.0065"),
    "EQUIPMENT": Decimal("0.0090"),
    "STORED_CROP": Decimal("0.0110"),
    "HAY": Decimal("0.0135"),
    "INPUTS": Decimal("0.0120"),
}


def deductible_credit(deductible_cents):
    value = dec(deductible_cents)
    if value < 100000:
        return Decimal("1.00")
    if value < 500000:
        return Decimal("0.95")
    if value < 1000000:
        return Decimal("0.90")
    return Decimal("0.85")


def property_line_cents(item_class, insured_value_cents, credit):
    return rhu(dec(insured_value_cents) * PROP_RATE[item_class] * credit)


# ------------------------------------------------------------ livestock premium

PER_HEAD_AGG_CAP_CENTS = 30000000
BLANKET_COINSURANCE_PCT = Decimal("0.80")

LIVE_RATE = {
    "CATTLE": Decimal("0.0125"),
    "SWINE": Decimal("0.0180"),
    "POULTRY": Decimal("0.0240"),
    "SHEEP": Decimal("0.0150"),
    "EQUINE": Decimal("0.0300"),
}
PERIL_RESTRICTION = {
    "FULL_PERIL": Decimal("1.00"),
    "NAMED_PERIL": Decimal("0.85"),
    "CATASTROPHE_ONLY": Decimal("0.60"),
}


def livestock_covered_limit(limit_basis, head_count, per_head_value_cents, blanket_limit_cents):
    if limit_basis == "PER_HEAD":
        return min(int(head_count) * int(per_head_value_cents), PER_HEAD_AGG_CAP_CENTS)
    return rhu(dec(blanket_limit_cents) * BLANKET_COINSURANCE_PCT)


def livestock_line_cents(group, credit):
    return rhu(
        dec(group["covered_limit_cents"])
        * LIVE_RATE[group["species"]]
        * PERIL_RESTRICTION[group["peril_scope"]]
        * credit
    )


# ------------------------------------------------------------ liability premium

LIABILITY_CONSTANTS = {
    "GENERAL_FARM": {"base": 25000, "cap": 500000},
    "CUSTOM_FARMING": {"base": 45000, "rate": Decimal("0.0075"), "cap": 900000},
    "AGRITOURISM": {"base": 60000, "rate": Decimal("0.0040"), "cap": 800000},
    "ROADSIDE_STAND": {"base": 30000, "rate": Decimal("0.0050"), "cap": 300000},
}
GENERAL_FARM_PER_ACRE_CENTS = Decimal("90")
AGRITOURISM_FREE_VISITORS = 500
AGRITOURISM_PER_VISITOR_CENTS = 120


def liability_exposure_premium(exposure_type, annual_receipts_cents, annual_visitor_count, acreage):
    receipts = dec(annual_receipts_cents)
    if exposure_type == "GENERAL_FARM":
        raw = 25000 + rhu(dec(acreage) * GENERAL_FARM_PER_ACRE_CENTS)
    elif exposure_type == "CUSTOM_FARMING":
        raw = 45000 + rhu(receipts * Decimal("0.0075"))
    elif exposure_type == "AGRITOURISM":
        billable = max(int(annual_visitor_count or 0) - AGRITOURISM_FREE_VISITORS, 0)
        raw = 60000 + billable * AGRITOURISM_PER_VISITOR_CENTS + rhu(receipts * Decimal("0.0040"))
    else:
        raw = 30000 + rhu(receipts * Decimal("0.0050"))
    return min(raw, LIABILITY_CONSTANTS[exposure_type]["cap"])


# ------------------------------------------------------- catastrophe allocation

PERIL_ORDER = ("HAIL", "WIND", "WILDFIRE")
CAT_RATE = {
    "HAIL": Decimal("0.0032"),
    "WIND": Decimal("0.0021"),
    "WILDFIRE": Decimal("0.0045"),
}


def cat_amount_cents(exposed_tiv_cents, participation_pct):
    return rhu(dec(exposed_tiv_cents) * dec(participation_pct))


def prospective_utilization(reserved_cents, committed_cents, amount_cents, total_capacity_cents):
    """Exact ratio; never rounded before the tier lookup."""
    total = dec(total_capacity_cents)
    if total == 0:
        return None
    return (dec(reserved_cents) + dec(committed_cents) + dec(amount_cents)) / total


def scarcity_factor(utilization):
    if utilization is None:
        return None
    if utilization <= Decimal("0.50"):
        return Decimal("1.00")
    if utilization <= Decimal("0.75"):
        return Decimal("1.15")
    if utilization <= Decimal("0.90"):
        return Decimal("1.35")
    if utilization <= Decimal("1.00"):
        return Decimal("1.60")
    return None


def cat_load_cents(amount_cents, peril, factor):
    return rhu(dec(amount_cents) * CAT_RATE[peril] * factor)


# ------------------------------------------------------------------ endorsement

ENDORSEMENT_FORMS = (
    "POLLUTION_BUYBACK",
    "CHEMICAL_APPLICATION_BUYBACK",
    "AGRITOURISM_LIABILITY",
    "PEAK_SEASON_INCREASE",
)
INSPECTION_FORMS = ("POLLUTION_BUYBACK", "CHEMICAL_APPLICATION_BUYBACK")
ENDORSEMENT_COMPANION = {
    "CHEMICAL_APPLICATION_BUYBACK": "CUSTOM_FARMING",
    "AGRITOURISM_LIABILITY": "AGRITOURISM",
}


def endorsement_premium(form_code, sublimit_cents):
    sublimit = dec(sublimit_cents)
    if form_code == "POLLUTION_BUYBACK":
        return max(rhu(sublimit * Decimal("0.0150")), 75000)
    if form_code == "CHEMICAL_APPLICATION_BUYBACK":
        return max(rhu(sublimit * Decimal("0.0220")), 90000)
    if form_code == "AGRITOURISM_LIABILITY":
        return rhu(sublimit * Decimal("0.0090")) + 25000
    return rhu(sublimit * Decimal("0.0110"))


# ------------------------------------------------------------------------ labor

WEIGHT_FULL_TIME = Decimal("1.00")
WEIGHT_SEASONAL = Decimal("0.50")
WEIGHT_MIGRANT_H2A = Decimal("0.75")
WC_REQUIRED_THRESHOLD = Decimal("6.00")


def labor_exposure_units(full_time_count, seasonal_count, migrant_h2a_count):
    raw = (
        dec(full_time_count) * WEIGHT_FULL_TIME
        + dec(seasonal_count) * WEIGHT_SEASONAL
        + dec(migrant_h2a_count) * WEIGHT_MIGRANT_H2A
    )
    return rhu2(raw)


# ------------------------------------------------------------------- inspection

BASE_SCORE = {"INITIAL": 10, "RE_INSPECTION": 5, "LOSS_TRIGGERED": 20}
SEVERITY_WEIGHT = {"CRITICAL": 30, "MAJOR": 12, "MINOR": 4}
SCORE_CAP = 100


def hazard_score(inspection_type, findings):
    total = BASE_SCORE[inspection_type]
    for finding in findings:
        total += SEVERITY_WEIGHT[finding["severity"]]
    return min(SCORE_CAP, total)


# -------------------------------------------------------------------- referral

TIV_REFERRAL_LIMIT_CENTS = 250000000
AGRITOURISM_VISITOR_LIMIT = 2000
CAT_UTILIZATION_LIMIT = Decimal("0.90")
HAZARD_SCORE_LIMIT = 40
QUOTE_VALID_DAYS = 30
INSPECTION_TRAVEL_BUFFER_MINUTES = 90
