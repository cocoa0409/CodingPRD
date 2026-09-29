"""Every derived quantity in the program (SCAFFOLD 1.3 calculations / PRD 2.6).

All arithmetic runs on Decimal with a high working precision so that division is
effectively exact before the single pinned round_half_up at the end of each
formula.  Rounding order is pinned exactly as specified.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext

getcontext().prec = 50

D = Decimal
ZERO = D("0")
HUNDRED = D("100")

Q0 = D("1")
Q1 = D("0.1")
Q2 = D("0.01")
Q3 = D("0.001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    if isinstance(value, float):
        return D(str(value))
    return D(value)


def rhu(value, places=0):
    """round_half_up to `places` decimal places."""
    if value is None:
        return None
    quantum = D(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


# --------------------------------------------------------------------------- #
# enumerations shared across the domain
# --------------------------------------------------------------------------- #
ELEMENT_KEYS = (
    "DECK",
    "GIRDER",
    "BEARING",
    "PIER_CAP",
    "COLUMN",
    "ABUTMENT",
    "JOINT",
    "RAILING",
)

ELEMENT_GROUPS = ("DECK_GROUP", "SUPERSTRUCTURE", "SUBSTRUCTURE")

GROUP_MEMBERS = {
    "DECK_GROUP": ["DECK", "JOINT", "RAILING"],
    "SUPERSTRUCTURE": ["GIRDER", "BEARING"],
    "SUBSTRUCTURE": ["PIER_CAP", "COLUMN", "ABUTMENT"],
}

GROUP_OF_ELEMENT = {}
for _group, _members in GROUP_MEMBERS.items():
    for _member in _members:
        GROUP_OF_ELEMENT[_member] = _group

CS_WEIGHT = {
    "CS1": D("1.00"),
    "CS2": D("0.80"),
    "CS3": D("0.40"),
    "CS4": D("0.00"),
}

ELEMENT_WEIGHT = {
    "DECK": D("0.30"),
    "GIRDER": D("0.25"),
    "BEARING": D("0.10"),
    "PIER_CAP": D("0.10"),
    "COLUMN": D("0.10"),
    "ABUTMENT": D("0.10"),
    "JOINT": D("0.05"),
    "RAILING": D("0.05"),
}

RATING_THRESHOLDS = (
    (D("97"), 9),
    (D("90"), 8),
    (D("80"), 7),
    (D("70"), 6),
    (D("60"), 5),
    (D("45"), 4),
    (D("30"), 3),
    (D("15"), 2),
    (D("5"), 1),
)


# --------------------------------------------------------------------------- #
# personnel qualification
# --------------------------------------------------------------------------- #
def qualification_status(expiry_date, current_date):
    """Whole calendar days, UTC; expiry == today is still CURRENT."""
    if expiry_date is None:
        return "EXPIRED"
    if expiry_date >= current_date:
        return "CURRENT"
    return "EXPIRED"


# --------------------------------------------------------------------------- #
# element / bridge condition
# --------------------------------------------------------------------------- #
def element_health_index(cs1, cs2, cs3, cs4, total_quantity):
    total = dec(total_quantity)
    weighted = (
        CS_WEIGHT["CS1"] * dec(cs1)
        + CS_WEIGHT["CS2"] * dec(cs2)
        + CS_WEIGHT["CS3"] * dec(cs3)
        + CS_WEIGHT["CS4"] * dec(cs4)
    )
    raw = HUNDRED * weighted / total
    return rhu(raw, 2)


def weighted_group_index(pairs):
    """pairs: iterable of (element_key, rounded element_health_index)."""
    weight_sum = ZERO
    score_sum = ZERO
    seen = False
    for element_key, index in pairs:
        weight = ELEMENT_WEIGHT[element_key]
        weight_sum += weight
        score_sum += weight * dec(index)
        seen = True
    if not seen or weight_sum == 0:
        return None
    return rhu(score_sum / weight_sum, 2)


def rating_from_index(index):
    if index is None:
        return None
    value = dec(index)
    for threshold, rating in RATING_THRESHOLDS:
        if value >= threshold:
            return rating
    return 0


def deficiency_pct(inventoried_total, deficient_total):
    inventoried = dec(inventoried_total)
    if inventoried == 0:
        return D("0.00")
    return rhu(HUNDRED * dec(deficient_total) / inventoried, 2)


# --------------------------------------------------------------------------- #
# scour
# --------------------------------------------------------------------------- #
SCOUR_CRITICAL_MAX_CODE = 3
LOW_RISK_MAX_CODE = 6


def derived_scour_status(scour_code):
    code = int(scour_code)
    if code <= SCOUR_CRITICAL_MAX_CODE:
        return "SCOUR_CRITICAL"
    if code <= LOW_RISK_MAX_CODE:
        return "LOW_RISK"
    return "STABILIZED"


# --------------------------------------------------------------------------- #
# inspection frequency
# --------------------------------------------------------------------------- #
STANDARD_INTERVAL_MONTHS = 24
SHORT_INTERVAL_MONTHS = 12
EXTENDED_INTERVAL_MONTHS = 48
POOR_RATING_MAX = 4
EXTENDED_RATING_MIN = 7
EXTENDED_YEAR_BUILT_MIN = 1990
EXTENDED_ADT_MAX = 5000
FRACTURE_CRITICAL_CAP = 12
SCOUR_CRITICAL_CAP = 12
RESTRICTED_CAP = 6
UNDERWATER_BASE_MONTHS = 60
UNDERWATER_SCOUR_CAP = 24


def inspection_interval_months(
    min_nbi_rating, year_built, adt, fracture_critical, scour_status, service_posture
):
    rating = int(min_nbi_rating)
    if rating <= POOR_RATING_MAX:
        interval = SHORT_INTERVAL_MONTHS
    elif (
        rating >= EXTENDED_RATING_MIN
        and int(year_built) >= EXTENDED_YEAR_BUILT_MIN
        and int(adt) <= EXTENDED_ADT_MAX
    ):
        interval = EXTENDED_INTERVAL_MONTHS
    else:
        interval = STANDARD_INTERVAL_MONTHS
    if fracture_critical:
        interval = min(interval, FRACTURE_CRITICAL_CAP)
    if scour_status == "SCOUR_CRITICAL":
        interval = min(interval, SCOUR_CRITICAL_CAP)
    if service_posture in ("RESTRICTED", "CLOSED"):
        interval = min(interval, RESTRICTED_CAP)
    return interval


def underwater_interval_months(underwater_elements, scour_status):
    if not underwater_elements:
        return None
    if scour_status == "SCOUR_CRITICAL":
        return UNDERWATER_SCOUR_CAP
    return UNDERWATER_BASE_MONTHS


def add_months(base, months):
    if base is None or months is None:
        return None
    year = base.year
    month = base.month + int(months)
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# --------------------------------------------------------------------------- #
# load rating
# --------------------------------------------------------------------------- #
PHI_C_BY_STATE = {
    "CS1": D("1.00"),
    "CS2": D("1.00"),
    "CS3": D("0.95"),
    "CS4": D("0.85"),
}

_STATE_ORDER = {"CS1": 1, "CS2": 2, "CS3": 3, "CS4": 4}

GAMMA_DC = D("1.25")
GAMMA_DW = D("1.50")
GAMMA_LL_OPERATING = D("1.35")
GAMMA_LL_INVENTORY = D("1.75")
RATING_VEHICLE_TONS = D("36.0")
POSTING_RF_THRESHOLD = D("1.000")
POSTED_LIMIT_STEP_TONS = D("0.5")
CRAWL_IMPACT_FACTOR = D("1.00")
PERMIT_ADEQUATE_RF = D("1.000")
PERMIT_MARGINAL_RF = D("0.900")


def worst_condition_state(element_rows):
    """Per-element elif ladder; bridge-level worst is the max over elements."""
    worst = "CS1"
    for row in element_rows:
        if dec(row["cs4_qty"]) > 0:
            state = "CS4"
        elif dec(row["cs3_qty"]) > 0:
            state = "CS3"
        elif dec(row["cs2_qty"]) > 0:
            state = "CS2"
        else:
            state = "CS1"
        if _STATE_ORDER[state] > _STATE_ORDER[worst]:
            worst = state
    return worst


def condition_factor_phi_c(element_rows):
    return PHI_C_BY_STATE[worst_condition_state(element_rows)]


def rating_numerator(phi_c, phi_s, phi, capacity, dead_dc, dead_dw):
    return (
        dec(phi_c) * dec(phi_s) * dec(phi) * dec(capacity)
        - GAMMA_DC * dec(dead_dc)
        - GAMMA_DW * dec(dead_dw)
    )


def rating_factor(numerator, gamma_ll, live_load, impact):
    denominator = dec(gamma_ll) * dec(live_load) * dec(impact)
    return rhu(numerator / denominator, 3)


def rating_tons(factor):
    """Tons are computed from the ALREADY-ROUNDED rating factor."""
    return rhu(dec(factor) * RATING_VEHICLE_TONS, 1)


def posted_limit_tons(inventory_tons):
    """Round DOWN to the nearest 0.5 ton."""
    steps = (dec(inventory_tons) * D("2")).to_integral_value(rounding=ROUND_FLOOR)
    return rhu(steps / D("2"), 1)


def load_rating_outputs(phi_c, phi_s, phi, capacity, dead_dc, dead_dw, live_load, impact):
    numerator = rating_numerator(phi_c, phi_s, phi, capacity, dead_dc, dead_dw)
    rf_operating = rating_factor(numerator, GAMMA_LL_OPERATING, live_load, impact)
    rf_inventory = rating_factor(numerator, GAMMA_LL_INVENTORY, live_load, impact)
    operating_tons = rating_tons(rf_operating)
    inventory_tons = rating_tons(rf_inventory)
    posting_required = rf_operating < POSTING_RF_THRESHOLD
    posted = posted_limit_tons(inventory_tons) if posting_required else None
    return {
        "rating_factor_operating": rf_operating,
        "rating_factor_inventory": rf_inventory,
        "operating_rating_tons": operating_tons,
        "inventory_rating_tons": inventory_tons,
        "posting_required": posting_required,
        "posted_limit_tons": posted,
    }


# --------------------------------------------------------------------------- #
# permits
# --------------------------------------------------------------------------- #
def permit_gross_weight_tons(axle_loads):
    """Each axle rounded to 1dp FIRST, then the sum rounded to 1dp."""
    rounded = [rhu(load, 1) for load in axle_loads]
    total = ZERO
    for value in rounded:
        total += value
    return rhu(total, 1)


def permit_rating_factor(governing, gross_weight_tons, speed_category):
    permit_live_load = dec(governing["live_load_ll_kn_m"]) * (
        dec(gross_weight_tons) / RATING_VEHICLE_TONS
    )
    if speed_category == "NORMAL":
        impact = dec(governing["impact_im_factor"])
    else:
        impact = CRAWL_IMPACT_FACTOR
    numerator = rating_numerator(
        governing["condition_factor_phi_c"],
        governing["system_factor_phi_s"],
        governing["resistance_factor_phi"],
        governing["capacity_c_kn_m"],
        governing["dead_load_dc_kn_m"],
        governing["dead_load_dw_kn_m"],
    )
    denominator = GAMMA_LL_OPERATING * permit_live_load * impact
    return rhu(numerator / denominator, 3)


def permit_analysis_outcome(rating_factor_permit):
    if rating_factor_permit >= PERMIT_ADEQUATE_RF:
        return "ALLOWED", "RF_ADEQUATE"
    if rating_factor_permit >= PERMIT_MARGINAL_RF:
        return "ALLOWED_WITH_CONDITIONS", "RF_MARGINAL"
    return "DENIED", "RF_INSUFFICIENT"


def permit_recommended_decision(results):
    if "DENIED" in results:
        return "DENY"
    if "ALLOWED_WITH_CONDITIONS" in results:
        return "APPROVE_WITH_CONDITIONS"
    return "APPROVE"


# --------------------------------------------------------------------------- #
# project candidates
# --------------------------------------------------------------------------- #
UNIT_REPAIR_COST_CENTS = {
    "DECK": D("18000"),
    "GIRDER": D("95000"),
    "BEARING": D("260000"),
    "PIER_CAP": D("140000"),
    "COLUMN": D("210000"),
    "ABUTMENT": D("175000"),
    "JOINT": D("55000"),
    "RAILING": D("40000"),
}
MOBILIZATION_FACTOR = D("1.15")


def estimated_repair_cost_cents(element_rows):
    subtotal = 0
    for row in element_rows:
        qty = dec(row["cs3_qty"]) + dec(row["cs4_qty"])
        line = rhu_int(UNIT_REPAIR_COST_CENTS[row["element_key"]] * qty)
        subtotal += line
    return rhu_int(D(subtotal) * MOBILIZATION_FACTOR)


def candidate_work_type(min_nbi_rating):
    rating = int(min_nbi_rating)
    if rating <= 3:
        return "REPLACEMENT"
    if rating == 4:
        return "REHABILITATION"
    if rating == 5:
        return "REPAIR"
    return "PRESERVATION"


SCOUR_POINTS = {
    "SCOUR_CRITICAL": D("100"),
    "NOT_EVALUATED": D("70"),
    "LOW_RISK": D("40"),
    "STABILIZED": D("20"),
}

POSTING_POINTS = {
    "CLOSED": D("100"),
    "RESTRICTED": D("80"),
    "POSTED": D("60"),
    "OPEN": D("0"),
}

EXPOSURE_ADT_DIVISOR = D("250")
EXPOSURE_CAP = D("100.00")


def exposure_points(adt, detour_length_km):
    raw = rhu(dec(adt) / EXPOSURE_ADT_DIVISOR + dec(detour_length_km), 2)
    return raw if raw < EXPOSURE_CAP else EXPOSURE_CAP


def candidate_priority_score(bridge, ranking_policy):
    condition_gap = HUNDRED - dec(bridge["bridge_health_index"])
    if ranking_policy == "CONDITION_BASED":
        rating_gap = (D("9") - dec(bridge["min_nbi_rating"])) * (HUNDRED / D("9"))
        score = (
            D("0.50") * condition_gap
            + D("0.30") * rating_gap
            + D("0.20") * dec(bridge["deficiency_pct"])
        )
    else:
        score = (
            D("0.35") * condition_gap
            + D("0.25") * SCOUR_POINTS[bridge["scour_status"]]
            + D("0.25") * exposure_points(bridge["adt"], bridge["detour_length_km"])
            + D("0.15") * POSTING_POINTS[bridge["service_posture"]]
        )
    return rhu(score, 2)


def outranks(a, b):
    if dec(a["priority_score"]) > dec(b["priority_score"]):
        return True
    if dec(a["priority_score"]) == dec(b["priority_score"]):
        return a["created_at"] < b["created_at"]
    return False


# --------------------------------------------------------------------------- #
# program budget
# --------------------------------------------------------------------------- #
DEFAULT_RESERVE_PCT = D("0.05")


def reserve_cents(reserve_pct, authorized_budget_cents):
    return rhu_int(dec(reserve_pct) * D(int(authorized_budget_cents)))


# --------------------------------------------------------------------------- #
# federal compliance
# --------------------------------------------------------------------------- #
ACCEPTANCE_COMPLIANCE_THRESHOLD_PCT = D("90.00")


def inspection_compliance_pct(total_bridge_count, overdue_inspection_count):
    if total_bridge_count == 0:
        return D("100.00")
    compliant = D(total_bridge_count - overdue_inspection_count)
    return rhu(HUNDRED * compliant / D(total_bridge_count), 2)


# --------------------------------------------------------------------------- #
# notifications and window conflicts
# --------------------------------------------------------------------------- #
NOTIFICATION_WINDOW_HOURS = 24
BRIDGE_ACCESS_BUFFER_HOURS = 72


def notification_due_at(created_at):
    return created_at + timedelta(hours=NOTIFICATION_WINDOW_HOURS)


def is_late(clock, due_at):
    return bool(due_at is not None and clock > due_at)


def half_open_overlap(new_start, new_end, other_start, other_end):
    return new_start < other_end and other_start < new_end


def buffered_overlap(new_start, new_end, other_start, other_end):
    buffer = timedelta(hours=BRIDGE_ACCESS_BUFFER_HOURS)
    return new_start < other_end + buffer and other_start < new_end + buffer
