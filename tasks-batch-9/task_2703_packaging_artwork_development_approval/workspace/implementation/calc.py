"""Controlled vocabularies (PRD 2.10) and every derived quantity (PRD 2.8, 3.4, 3.6-3.9)."""
from decimal import Decimal

from core import add_days, date_str, dec, round_half_up

# ---------------------------------------------------------------- vocabularies
REGULATORY_SCHEMES = ("FDA_FOOD", "EU_FIC", "HEALTH_CANADA")
BRIEF_STATUSES = ("DRAFT", "APPROVED", "REJECTED")
ELEMENT_CODES = (
    "NET_CONTENTS",
    "INGREDIENT_STATEMENT",
    "ALLERGEN_STATEMENT",
    "DATE_CODE_ZONE",
    "BARCODE",
    "RECYCLING_MARK",
    "ADDRESS_BLOCK",
)
COMPONENT_TYPES = ("CARTON", "LABEL", "FILM", "SHIPPER")
PRINT_PROCESSES = ("OFFSET", "FLEXO", "GRAVURE", "DIGITAL")
SUBSTRATE_CLASSES = ("COATED_PAPER", "UNCOATED_PAPER", "FILM", "METALLIZED")
METRIC_UOMS = ("G", "KG", "ML", "L")
US_UOMS = ("OZ", "LB", "FLOZ")

CLAIM_TYPES = ("NUTRIENT_CONTENT", "STRUCTURE_FUNCTION", "ORGANIC", "FREE_FROM", "SUSTAINABILITY")
CLAIM_LEGAL_STATUSES = ("DRAFT", "CLEARED", "REJECTED")

OBSOLESCENCE_STATES = ("ACTIVE", "SUPERSEDE_PENDING", "SUPERSEDED")
VERSION_STATES = (
    "DRAFT",
    "ELEMENTS_VERIFIED",
    "IN_REVIEW",
    "REVISION_REQUESTED",
    "APPROVED",
    "RELEASED_TO_PRINT",
    "OBSOLETE_PENDING",
    "OBSOLETE",
)
REASON_FOR_CHANGE_CODES = (
    "NEW_LAUNCH",
    "REGULATORY_UPDATE",
    "CLAIM_CHANGE",
    "MARKETING_REFRESH",
    "PRINTER_CHANGE",
    "ERROR_CORRECTION",
)

SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
ELEMENT_RESULTS = ("PASS", "FAIL", "WAIVED")
ROUTE_STATUSES = ("PENDING", "IN_PROGRESS", "COMPLETE_APPROVED", "COMPLETE_REJECTED")
DISCIPLINES = ("BRAND", "LEGAL", "REGULATORY", "QUALITY")
TASK_MODES = ("PARALLEL", "SEQUENTIAL")
TASK_DECISIONS = ("PENDING", "APPROVED", "REJECTED", "CONDITIONAL", "SKIPPED")

COLOR_STANDARDS = ("G7_MASTER", "ISO12647")
CERTIFICATION_STATUSES = ("CERTIFIED", "PROBATION")
COLOR_STATUSES = ("COLOR_PENDING", "COLOR_PASS", "COLOR_FAIL")
SUBSTRATE_STATUSES = ("SUBSTRATE_PENDING", "SUBSTRATE_APPROVED", "SUBSTRATE_REJECTED")
PRESS_CHECK_STATUSES = (
    "NOT_REQUIRED",
    "PRESS_CHECK_REQUIRED",
    "PRESS_CHECK_SCHEDULED",
    "PRESS_CHECK_ATTENDED",
)
PROOF_STATES = ("PROOF_IN_REVIEW", "PROOF_APPROVED", "PROOF_REJECTED")
PLATE_ORDER_STATUSES = ("ORDERED", "CANCELLED")

RUNOUT_STATES = ("PLANNED", "MONITORING", "RUNOUT_COMPLETE", "SCRAPPED")
DISPOSITIONS = ("RUNOUT", "SCRAP")
DEFECT_CODES = (
    "WRONG_ALLERGEN",
    "MISSING_NET_CONTENTS",
    "WRONG_LANGUAGE_VARIANT",
    "COLOR_OUT_OF_TOLERANCE",
    "WRONG_DATE_CODE",
    "OLD_ARTWORK_USED",
)
DISCOVERED_STAGES = ("PRESS", "PACKING", "DISTRIBUTION", "MARKET")
ESCAPE_STATES = (
    "OPEN",
    "ROOT_CAUSE_ASSIGNED",
    "RECOVERY_CLAIMED",
    "DISPUTED",
    "SETTLED",
    "WRITTEN_OFF",
)
ROOT_CAUSE_PARTIES = ("PRINTER", "BRAND", "AGENCY", "SHARED")
RESOLUTIONS = ("SETTLED", "WRITTEN_OFF")

MARKET_CODE_PATTERN = r"^[A-Z]{2}$"
LANGUAGE_CODE_PATTERN = r"^[a-z]{2,3}$"
CLAIM_CODE_PATTERN = r"^[A-Z0-9-]{3,40}$"

# ---------------------------------------------------------------- element rules
ELEMENT_ORDER = ELEMENT_CODES
ELEMENT_INDEX = dict((code, i) for i, code in enumerate(ELEMENT_ORDER))
ELEMENT_PAYLOAD_KEY = {
    "NET_CONTENTS": "net_contents",
    "INGREDIENT_STATEMENT": "ingredient_statement",
    "ALLERGEN_STATEMENT": "allergen_statement",
    "DATE_CODE_ZONE": "date_code_zone",
    "BARCODE": "barcode",
    "RECYCLING_MARK": "recycling_mark",
    "ADDRESS_BLOCK": "address_block",
}
ELEMENT_SEVERITY = {
    "NET_CONTENTS": "CRITICAL",
    "INGREDIENT_STATEMENT": "CRITICAL",
    "ALLERGEN_STATEMENT": "CRITICAL",
    "DATE_CODE_ZONE": "MAJOR",
    "BARCODE": "MAJOR",
    "RECYCLING_MARK": "MINOR",
    "ADDRESS_BLOCK": "MINOR",
}
SEVERITY_WEIGHT = {"CRITICAL": Decimal("25"), "MAJOR": Decimal("10"), "MINOR": Decimal("4")}
WAIVED_WEIGHT_FACTOR = Decimal("0.5")

SCHEME_FACTOR = {
    "FDA_FOOD": Decimal("1.00"),
    "EU_FIC": Decimal("1.10"),
    "HEALTH_CANADA": Decimal("1.05"),
}
MARKET_PENALTY_POINTS = Decimal("2.5")
LANGUAGE_PENALTY_POINTS = Decimal("1.5")
LANGUAGE_PENALTY_FREE_COUNT = 2
COMPLIANCE_SCORE_FLOOR = Decimal("70.0")
REVISION_CYCLE_CAP = 3

# ---------------------------------------------------------------- proofs
DELTA_E_TOLERANCE = {
    "G7_MASTER": {
        "COATED_PAPER": Decimal("2.0"),
        "UNCOATED_PAPER": Decimal("3.0"),
        "FILM": Decimal("3.5"),
        "METALLIZED": Decimal("4.0"),
    },
    "ISO12647": {
        "COATED_PAPER": Decimal("2.5"),
        "UNCOATED_PAPER": Decimal("3.5"),
        "FILM": Decimal("4.0"),
        "METALLIZED": Decimal("4.5"),
    },
}
BRAND_CRITICAL_TIGHTENING = Decimal("0.5")
PRESS_CHECK_BUFFER_MINUTES = 120

# ---------------------------------------------------------------- routing
STAGE_PLAN = [
    {"stage_no": 1, "mode": "PARALLEL", "disciplines": ["BRAND", "REGULATORY"]},
    {"stage_no": 2, "mode": "SEQUENTIAL", "disciplines": ["LEGAL"]},
    {"stage_no": 3, "mode": "SEQUENTIAL", "disciplines": ["QUALITY"]},
]
FINAL_STAGE_NO = 3
APPROVING_DECISIONS = ("APPROVED", "CONDITIONAL")
DISCIPLINE_ROLE = {
    "BRAND": "BrandReviewer",
    "LEGAL": "LegalReviewer",
    "REGULATORY": "RegulatoryReviewer",
    "QUALITY": "QualityReviewer",
}

# ---------------------------------------------------------------- money
PLATE_RATE_1_CENTS = 18000
PLATE_RATE_2_CENTS = 15500
PLATE_RATE_3_CENTS = 13000
PLATE_BAND_1_MAX = 4
PLATE_BAND_2_MAX = 8
PLATE_SETUP_FEE_SMALL_CENTS = 60000
PLATE_SETUP_FEE_LARGE_CENTS = 90000
EXPEDITE_PCT = Decimal("0.25")

STANDARD_UNIT_COST_CENTS = {"CARTON": 42, "LABEL": 9, "FILM": 15, "SHIPPER": 120}
SCRAP_HANDLING_CENTS = 7
INVESTIGATION_FEE_EARLY_CENTS = 60000
INVESTIGATION_FEE_LATE_CENTS = 150000
LATE_DISCOVERY_STAGES = ("DISTRIBUTION", "MARKET")

REWORK_UNIT_CENTS = 18
CHANGEOVER_TIERS = (
    (500000, Decimal("0.05")),
    (2000000, Decimal("0.08")),
    (None, Decimal("0.12")),
)

PENALTY_POINTS_PER_1000_UNITS = Decimal("2.0")
ESCAPE_STAGE_PENALTY = {
    "PRESS": Decimal("2.0"),
    "PACKING": Decimal("4.0"),
    "DISTRIBUTION": Decimal("8.0"),
    "MARKET": Decimal("10.0"),
}
PENALTY_CAP_POINTS = Decimal("40.0")
PRINTER_PROBATION_SCORE = Decimal("70.0")

WEEK_LENGTH_DAYS = 7
TRAILING_WINDOW_RECORDS = 3
MIN_TRAILING_AVG_QTY = 1


# ---------------------------------------------------------------- helpers
def cents(value):
    """Round a monetary expression half up to a whole cent (PRD 2.8)."""
    return int(round_half_up(dec(value), 0))


def number(value):
    """Render a Decimal as an int when integral, else as a float, for JSON."""
    if value is None:
        return None
    value = dec(value)
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def one_dp(value):
    return float(round_half_up(dec(value), 1))


# ---------------------------------------------------------------- 3.4 element verdicts
def _text_len(sub, key):
    value = sub.get(key)
    if not isinstance(value, str):
        return -1
    return len(value)


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _nonempty_str(value):
    return isinstance(value, str) and len(value) > 0


def _element_passes(code, sub, scheme):
    """The seven sub-rules of PRD 3.4."""
    if code == "NET_CONTENTS":
        if not _positive(sub.get("metric_value")):
            return False
        if not _nonempty_str(sub.get("metric_uom")):
            return False
        if scheme == "FDA_FOOD":
            if not _positive(sub.get("us_value")):
                return False
            if not _nonempty_str(sub.get("us_uom")):
                return False
        return True
    if code == "INGREDIENT_STATEMENT":
        return _text_len(sub, "text") >= 10 and sub.get("descending_order") is True
    if code == "ALLERGEN_STATEMENT":
        return _text_len(sub, "text") >= 3 and sub.get("allergen_emphasis") is True
    if code == "DATE_CODE_ZONE":
        zone = sub.get("zone_mm2")
        ok_zone = isinstance(zone, int) and not isinstance(zone, bool) and zone >= 150
        if not ok_zone and isinstance(zone, float):
            ok_zone = zone >= 150
        return bool(ok_zone) and _nonempty_str(sub.get("position"))
    if code == "BARCODE":
        gtin = sub.get("gtin14")
        return isinstance(gtin, str) and len(gtin) == 14 and gtin.isdigit()
    if code == "RECYCLING_MARK":
        return sub.get("present") is True
    if code == "ADDRESS_BLOCK":
        return _text_len(sub, "text") >= 15
    return False


def evaluate_element(code, elements, scheme):
    """Returns (result, detail, deduction_points) for one required element code."""
    severity = ELEMENT_SEVERITY[code]
    weight = SEVERITY_WEIGHT[severity]
    sub = None
    if isinstance(elements, dict):
        sub = elements.get(ELEMENT_PAYLOAD_KEY[code])
    if not isinstance(sub, dict):
        return "FAIL", "ELEMENT_ABSENT", weight
    if _element_passes(code, sub, scheme):
        return "PASS", "OK", Decimal("0")
    return "FAIL", "%s_SUBRULE_FAILED" % code, weight


def deduction_for(severity, result):
    weight = SEVERITY_WEIGHT[severity]
    if result == "FAIL":
        return weight
    if result == "WAIVED":
        return weight * WAIVED_WEIGHT_FACTOR
    return Decimal("0")


def compliance_score(rows, brief, asset):
    """The pinned four-input arithmetic of PRD 3.4."""
    total = Decimal("0")
    for row in rows:
        total += dec(row["deduction_points"])
    scheme = brief.get("regulatory_scheme")
    scaled = round_half_up(total * SCHEME_FACTOR[scheme], 2)
    markets = len(brief.get("market_codes") or [])
    market_penalty = MARKET_PENALTY_POINTS * Decimal(max(0, markets - 1))
    languages = len(asset.get("language_codes") or [])
    language_penalty = LANGUAGE_PENALTY_POINTS * Decimal(
        max(0, languages - LANGUAGE_PENALTY_FREE_COUNT)
    )
    penalty = scaled + market_penalty + language_penalty
    score = round_half_up(Decimal("100") - penalty, 1)
    if score < Decimal("0.0"):
        score = Decimal("0.0")
    if score > Decimal("100.0"):
        score = Decimal("100.0")
    return score


# ---------------------------------------------------------------- 3.6 proofs
def effective_tolerance(color_standard, substrate_code, brand_critical):
    base = DELTA_E_TOLERANCE[color_standard][substrate_code]
    if brand_critical:
        base = base - BRAND_CRITICAL_TIGHTENING
    return round_half_up(base, 1)


def derive_proof_state(proof):
    """PRD 3.6: the rejecting clause is evaluated first."""
    if proof["color_status"] == "COLOR_FAIL" or proof["substrate_status"] == "SUBSTRATE_REJECTED":
        return "PROOF_REJECTED"
    if (
        proof["color_status"] == "COLOR_PASS"
        and proof["substrate_status"] == "SUBSTRATE_APPROVED"
        and proof["press_check_status"] in ("NOT_REQUIRED", "PRESS_CHECK_ATTENDED")
    ):
        return "PROOF_APPROVED"
    return "PROOF_IN_REVIEW"


# ---------------------------------------------------------------- 3.7 plate cost
def plate_cost(plate_set_count, expedite):
    band1 = min(plate_set_count, PLATE_BAND_1_MAX) * PLATE_RATE_1_CENTS
    band2 = max(0, min(plate_set_count, PLATE_BAND_2_MAX) - PLATE_BAND_1_MAX) * PLATE_RATE_2_CENTS
    band3 = max(0, plate_set_count - PLATE_BAND_2_MAX) * PLATE_RATE_3_CENTS
    subtotal = band1 + band2 + band3
    setup = (
        PLATE_SETUP_FEE_SMALL_CENTS
        if plate_set_count <= PLATE_BAND_2_MAX
        else PLATE_SETUP_FEE_LARGE_CENTS
    )
    expedite_fee = cents(dec(subtotal + setup) * EXPEDITE_PCT) if expedite else 0
    return subtotal, setup, expedite_fee, subtotal + setup + expedite_fee


# ---------------------------------------------------------------- 3.8 runout maths
def ceil_div(numerator, denominator):
    if denominator <= 0:
        return 0
    return -((-numerator) // denominator)


def projected_runout_date(start_dt, on_hand_qty, weekly_usage_qty):
    """The forward-looking projection: plan only, never actuals (PRD 3.8)."""
    if on_hand_qty == 0:
        return date_str(start_dt)
    weeks = ceil_div(on_hand_qty, weekly_usage_qty)
    return date_str(add_days(start_dt, WEEK_LENGTH_DAYS * weeks))


def trailing_avg(records):
    if not records:
        return None
    window = records[-TRAILING_WINDOW_RECORDS:]
    total = Decimal(0)
    for record in window:
        total += dec(record["units_consumed"])
    avg = int(round_half_up(total / Decimal(len(window)), 0))
    return max(MIN_TRAILING_AVG_QTY, avg)


def replay_depletion(on_hand_qty, records, parsed_dates):
    """Returns (remaining_qty, actual_runout_date) reading only actuals (PRD 3.8)."""
    remaining = on_hand_qty
    actual = None
    for index, record in enumerate(records):
        remaining -= int(record["units_consumed"])
        if remaining <= 0:
            remaining = 0
            actual = date_str(add_days(parsed_dates[index], WEEK_LENGTH_DAYS))
            break
    if remaining < 0:
        remaining = 0
    if actual is None and records:
        avg = trailing_avg(records)
        extra_weeks = ceil_div(remaining, avg)
        anchor = add_days(parsed_dates[-1], WEEK_LENGTH_DAYS)
        actual = date_str(add_days(anchor, WEEK_LENGTH_DAYS * extra_weeks))
    return remaining, actual


def changeover_tier_pct(base_cents):
    for ceiling, pct in CHANGEOVER_TIERS:
        if ceiling is None or base_cents < ceiling:
            return pct
    return CHANGEOVER_TIERS[-1][1]


def changeover_cost(units_scrapped, units_reworked, standard_unit_cost_cents):
    material = units_scrapped * standard_unit_cost_cents
    relabel = units_reworked * REWORK_UNIT_CENTS
    base = material + relabel
    expedite = cents(dec(base) * changeover_tier_pct(base))
    return material, relabel, base, expedite, base + expedite


# ---------------------------------------------------------------- 3.9 recovery
def investigation_fee(discovered_stage):
    if discovered_stage in LATE_DISCOVERY_STAGES:
        return INVESTIGATION_FEE_LATE_CENTS
    return INVESTIGATION_FEE_EARLY_CENTS


def recovery_sum(lines, share_pct):
    """Each line is scaled and rounded individually, in order, then summed (PRD 3.9)."""
    share = dec(share_pct)
    total = 0
    for line in lines:
        total += cents(dec(line) * share)
    return total


def performance_penalty(units_affected, discovered_stage):
    raw = (dec(units_affected) / Decimal(1000)) * PENALTY_POINTS_PER_1000_UNITS
    raw = raw + ESCAPE_STAGE_PENALTY[discovered_stage]
    penalty = round_half_up(raw, 1)
    if penalty > PENALTY_CAP_POINTS:
        penalty = PENALTY_CAP_POINTS
    return penalty


def apply_penalty(current_score, penalty):
    score = round_half_up(dec(current_score) - dec(penalty), 1)
    if score < Decimal("0.0"):
        score = Decimal("0.0")
    if score > Decimal("100.0"):
        score = Decimal("100.0")
    return score
