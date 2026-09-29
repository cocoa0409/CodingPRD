"""Reference tables (PRD §2.7) and every calculation routine (PRD §3.1/§3.3/§3.4/§3.6/§3.9).

All arithmetic is exact decimal arithmetic — no binary floating point (PRD §2.6).
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# --- Reference tables (PRD §2.7) ------------------------------------------
CZ_FACTOR = {
    "CZ2": Decimal("0.90"),
    "CZ3": Decimal("0.95"),
    "CZ4": Decimal("1.00"),
    "CZ5": Decimal("1.10"),
    "CZ6": Decimal("1.20"),
}

ACH50_MAX = {
    "IECC_2015": {"CZ2": Decimal("5.0"), "CZ3": Decimal("3.0"), "CZ4": Decimal("3.0"),
                  "CZ5": Decimal("3.0"), "CZ6": Decimal("3.0")},
    "IECC_2021": {"CZ2": Decimal("5.0"), "CZ3": Decimal("5.0"), "CZ4": Decimal("3.0"),
                  "CZ5": Decimal("3.0"), "CZ6": Decimal("3.0")},
}

ERI_TARGET = {
    "IECC_2015": {"CZ2": 65, "CZ3": 65, "CZ4": 65, "CZ5": 69, "CZ6": 69},
    "IECC_2021": {"CZ2": 52, "CZ3": 53, "CZ4": 55, "CZ5": 55, "CZ6": 54},
}

PV_INDEX_CAP = {"IECC_2021": Decimal("5.0"), "IECC_2015": Decimal("100.0")}

DUCT_MAX_FINAL = Decimal("4.0")
DUCT_MAX_ROUGH_IN_WITH_AHU = Decimal("4.0")
DUCT_MAX_ROUGH_IN_NO_AHU = Decimal("3.0")

EQUIP_MULT_FLOOR = Decimal("0.62")
EQUIP_MULT_CEILING = Decimal("1.05")

PERFORMANCE_INDEX_TOLERANCE = 5
PRESCRIPTIVE_UA_RATIO = Decimal("0.12")
PERFORMANCE_UA_RATIO = Decimal("0.14")

INSPECTOR_TRAVEL_BUFFER_MINUTES = 45

SAMPLE_SET_MIN_MEMBERS = 2
SAMPLE_SET_MAX_MEMBERS = 7

QA_RATE_STANDARD = Decimal("0.10")
QA_RATE_PROBATION = Decimal("1.00")

TAX_TIER_1_MAX_INDEX = 45
TAX_TIER_1_CENTS = 250000
TAX_TIER_2_MAX_INDEX = 55
TAX_TIER_2_CENTS = 100000
ENVELOPE_RATE_CENTS_PER_SQFT = Decimal("37.5")
DUCT_RATE_CENTS = Decimal("1250")
AIR_RATE_CENTS = Decimal("1500")
AIR_BASELINE_ACH50 = Decimal("5.0")
INDEX_RATE_CENTS = Decimal("2250")
INDEX_BASELINE = Decimal("60")
UTILITY_PACKAGE_CAP_CENTS = 150000
TAX_CREDIT_MAX_INDEX = 55
UTILITY_PROGRAM_MAX_INDEX = 50


def dec(value):
    """Convert an incoming JSON number into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def to_number(value):
    """Render a Decimal as a JSON-friendly number."""
    return float(value)


# --- hers_index -----------------------------------------------------------
def hers_index(plan, subdivision, ach50, duct):
    """Single index routine; the caller supplies the variant's ach50/duct inputs."""
    cz = CZ_FACTOR[subdivision["climate_zone"]]
    ua = dec(plan["envelope_ua_btu_per_hr_f"])
    volume = dec(plan["conditioned_volume_cuft"])
    cfa = dec(plan["conditioned_floor_area_sqft"])
    bedrooms = dec(plan["bedrooms"])
    hvac = dec(plan["hvac_efficiency_index"])
    pv = dec(plan["pv_capacity_kw_dc"])
    ach50 = dec(ach50)
    duct = dec(duct)

    base_load = (
        ua * cz
        + Decimal("0.60") * ach50 * volume / Decimal(1000)
        + Decimal("0.90") * duct * cfa / Decimal(100)
    )
    equip_mult = max(
        EQUIP_MULT_FLOOR,
        min(EQUIP_MULT_CEILING, Decimal("1.35") - Decimal("0.05") * hvac),
    )
    ref_load = Decimal("0.30") * cfa + Decimal("40.0") * bedrooms
    raw_index = base_load * equip_mult / ref_load * Decimal(100)
    pv_points = min(PV_INDEX_CAP[subdivision["code_edition"]], Decimal("4.0") * pv)
    index = round_half_up(raw_index - pv_points, 0)
    if index < 0:
        index = Decimal(0)
    return int(index)


def projected_index(plan, subdivision):
    return hers_index(
        plan,
        subdivision,
        plan["design_ach50"],
        plan["design_duct_leakage_cfm25_per_100sqft"],
    )


def confirmed_index(plan, subdivision, ach50, duct):
    return hers_index(plan, subdivision, ach50, duct)


# --- compliance_path_selection -------------------------------------------
def compliance_path_selection(rating, plan, subdivision):
    edition = subdivision["code_edition"]
    zone = subdivision["climate_zone"]
    ach50 = dec(rating["confirmed_ach50"])
    duct = dec(rating["confirmed_duct_leakage_cfm25_per_100sqft"])
    index = rating["confirmed_index"]
    ua = dec(plan["envelope_ua_btu_per_hr_f"])
    cfa = dec(plan["conditioned_floor_area_sqft"])
    target = ERI_TARGET[edition][zone]

    ach50_pass = ach50 <= ACH50_MAX[edition][zone]
    duct_pass = duct <= DUCT_MAX_FINAL

    # Step 0 — binding election; never falls through to steps 1-3.
    if subdivision["compliance_path_preference"] == "PRESCRIPTIVE_PATH":
        if ach50_pass and duct_pass and ua <= PRESCRIPTIVE_UA_RATIO * cfa:
            return "PRESCRIPTIVE", "PASSING"
        return "NONE", "FAILING"

    # Step 1 — ERI path.
    if index <= target and ach50_pass and duct_pass:
        return "ERI", "PASSING"
    # Step 2 — total-UA performance path.
    if (
        index <= target + PERFORMANCE_INDEX_TOLERANCE
        and ach50_pass
        and duct_pass
        and ua <= PERFORMANCE_UA_RATIO * cfa
    ):
        return "PERFORMANCE", "PASSING"
    # Step 3 — nothing qualifies.
    return "NONE", "FAILING"


# --- diagnostic test normalizations --------------------------------------
def blower_door_normalization(measured_value, plan, subdivision):
    normalized = round_half_up(
        dec(measured_value) * Decimal(60) / dec(plan["conditioned_volume_cuft"]), 2
    )
    threshold = ACH50_MAX[subdivision["code_edition"]][subdivision["climate_zone"]]
    result = "PASS" if normalized <= threshold else "FAIL"
    return normalized, threshold, result


def duct_leakage_normalization(measured_value, plan, inspection):
    normalized = round_half_up(
        dec(measured_value) * Decimal(100) / dec(plan["conditioned_floor_area_sqft"]), 2
    )
    if inspection["checkpoint"] == "FINAL":
        threshold = DUCT_MAX_FINAL
    elif inspection["air_handler_installed"]:
        threshold = DUCT_MAX_ROUGH_IN_WITH_AHU
    else:
        threshold = DUCT_MAX_ROUGH_IN_NO_AHU
    result = "PASS" if normalized <= threshold else "FAIL"
    return normalized, threshold, result


# --- qa_sampling_quota ---------------------------------------------------
def qa_sampling_quota(certification_status, confirmed_rating_count, qa_completed_count):
    rate = QA_RATE_PROBATION if certification_status == "PROBATION" else QA_RATE_STANDARD
    required = int(
        (rate * Decimal(confirmed_rating_count)).to_integral_value(rounding=ROUND_FLOOR)
    )
    owed = required - qa_completed_count
    if owed < 0:
        owed = 0
    return owed, owed > 0


# --- incentive_amount ----------------------------------------------------
def incentive_amount(package_type, index, ach50, duct, plan):
    """Returns (amount_cents, line_items)."""
    if package_type == "TAX_CREDIT_45L":
        if index <= TAX_TIER_1_MAX_INDEX:
            amount = TAX_TIER_1_CENTS
        elif index <= TAX_TIER_2_MAX_INDEX:
            amount = TAX_TIER_2_CENTS
        else:
            amount = 0
        return amount, []

    cfa = dec(plan["conditioned_floor_area_sqft"])
    duct_d = dec(duct)
    ach_d = dec(ach50)
    index_d = dec(index)

    line_envelope = int(round_half_up(ENVELOPE_RATE_CENTS_PER_SQFT * cfa, 0))
    line_ducts = int(
        round_half_up(DUCT_RATE_CENTS * max(Decimal(0), DUCT_MAX_FINAL - duct_d), 0)
    )
    line_air = int(
        round_half_up(AIR_RATE_CENTS * max(Decimal(0), AIR_BASELINE_ACH50 - ach_d), 0)
    )
    line_index = int(
        round_half_up(INDEX_RATE_CENTS * max(Decimal(0), INDEX_BASELINE - index_d), 0)
    )
    line_items = [
        {"code": "ENVELOPE", "amount_cents": line_envelope},
        {"code": "DUCTS", "amount_cents": line_ducts},
        {"code": "AIR", "amount_cents": line_air},
        {"code": "INDEX", "amount_cents": line_index},
    ]
    subtotal = line_envelope + line_ducts + line_air + line_index
    return min(subtotal, UTILITY_PACKAGE_CAP_CENTS), line_items
