"""Calculation rules (scaffold 1.3 / PRD 2.6, 2.10, 3.1, 3.4, 3.5, 3.6, 3.8, 3.9).

All money/engineering arithmetic is Decimal; every rounding is half-up.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# ---------------------------------------------------------------- enums
PRODUCT_TYPES = (
    "STEP_LADDER",
    "EXTENSION_LADDER",
    "PLATFORM_LADDER",
    "ARTICULATED_LADDER",
    "MOBILE_SCAFFOLD_TOWER",
)
MATERIALS = ("ALUMINUM_EXTRUSION", "FIBERGLASS_PULTRUSION", "STEEL")
DUTY_RATINGS = ("TYPE_III", "TYPE_II", "TYPE_I", "TYPE_IA", "TYPE_IAA")
JOINT_TYPES = ("RIVETED", "BONDED", "WELDED")
DOC_KINDS = (
    "DUTY_RATING_LABEL",
    "WARNING_LABEL",
    "INSTRUCTION_LABEL",
    "CERT_MARK_LABEL",
    "RETAIL_CARTON",
    "ASSEMBLY_INSTRUCTION_SHEET",
    "CONSUMER_SAFETY_SHEET",
)
LABEL_DOC_KINDS = (
    "DUTY_RATING_LABEL",
    "WARNING_LABEL",
    "INSTRUCTION_LABEL",
    "CERT_MARK_LABEL",
)
REQUIRED_DOC_KINDS = (
    "DUTY_RATING_LABEL",
    "WARNING_LABEL",
    "INSTRUCTION_LABEL",
    "RETAIL_CARTON",
    "ASSEMBLY_INSTRUCTION_SHEET",
    "CONSUMER_SAFETY_SHEET",
)
PLACEMENT_ZONES = ("SIDE_RAIL_UPPER", "SIDE_RAIL_LOWER", "TOP_CAP", "BACK_RAIL")
TEST_CODES = (
    "STATIC_VERTICAL",
    "RAIL_BENDING",
    "SLIP_RESISTANCE",
    "HINGE_CYCLE",
    "ELECTRICAL_LEAKAGE",
    "RIVET_SHEAR",
)
CAMPAIGN_PURPOSES = (
    "DESIGN_QUALIFICATION",
    "CERTIFICATION_LISTING",
    "PERIODIC_AUDIT",
    "INCIDENT_INVESTIGATION",
)
STANDARD_CODES = ("ANSI_ASC_A14_2", "ANSI_ASC_A14_5", "EN_131_2", "CSA_Z11")
QUARANTINE_REASONS = ("JOINT_INTEGRITY", "LABEL_DEFECT", "AUDIT_FAILURE", "FIELD_INCIDENT")
STOP_SHIP_REASONS = ("LOT_QUARANTINE", "FIELD_INCIDENT_REVIEW", "LISTING_SUSPENDED")
SUSPENSION_REASONS = ("AUDIT_FAILURE", "STOP_SHIP_CASCADE", "BODY_REQUEST")
DISPOSITIONS = ("RELEASE", "SCRAP")
PURCHASE_CHANNELS = ("BIG_BOX_RETAIL", "PRO_DEALER", "ONLINE")
REMEDY_TYPES = ("REPAIR_KIT", "REPLACEMENT", "REFUND")
INCIDENT_TYPES = (
    "RAIL_FRACTURE",
    "RUNG_SEPARATION",
    "HINGE_FAILURE",
    "SLIP_FALL",
    "LABEL_ILLEGIBLE",
)
INJURY_SEVERITIES = ("NONE", "MINOR", "HOSPITALIZATION", "FATALITY")
ROOT_CAUSE_CODES = (
    "RIVET_SHEAR_MARGIN",
    "RAIL_SECTION_MODULUS",
    "LABEL_ADHESION",
    "HINGE_STOP_GEOMETRY",
    "CONSUMER_MISUSE",
)
FINDINGS = ("NOT_SUBSTANTIATED", "ROOT_CAUSE_IDENTIFIED")
REVIEW_DECISIONS = ("APPROVE", "REQUEST_CHANGES")

# ---------------------------------------------------------------- constants
RATED_LOAD_BY_DUTY = {
    "TYPE_III": 200,
    "TYPE_II": 225,
    "TYPE_I": 250,
    "TYPE_IA": 300,
    "TYPE_IAA": 375,
}
BASE_SAFETY_FACTOR = Decimal("4.00")
LENGTH_BASELINE_FT = Decimal("12")
LENGTH_STEP_FT = Decimal("4")
LENGTH_ADDER_PER_STEP = Decimal("0.15")
TYPE_SF_BONUS = {
    "STEP_LADDER": Decimal("0.00"),
    "EXTENSION_LADDER": Decimal("0.00"),
    "PLATFORM_LADDER": Decimal("0.00"),
    "ARTICULATED_LADDER": Decimal("0.10"),
    "MOBILE_SCAFFOLD_TOWER": Decimal("0.25"),
}
FIBERGLASS_SF_BONUS = Decimal("0.05")
SAFETY_FACTOR_CAP = Decimal("4.60")
JOINT_PULL_MULTIPLE = Decimal("1.50")
DEFLECTION_SPAN_DIVISOR = Decimal("180")
MAX_PERMANENT_SET_IN = Decimal("0.020")

MIN_JOINT_SAMPLES = 4
JOINT_SAMPLE_UNITS_PER_SAMPLE = 250
MIN_CONFORMANCE_INDEX = Decimal("2.00")

BASE_AUDIT_SAMPLE = 5
ESCALATION_ADDER_BY_TIER = {"TIER_0": 0, "TIER_1": 3, "TIER_2": 8, "TIER_3": 15}

SEVERITY_WEIGHT = {
    "NONE": Decimal("1"),
    "MINOR": Decimal("4"),
    "HOSPITALIZATION": Decimal("12"),
    "FATALITY": Decimal("30"),
}
TYPE_WEIGHT = {
    "RAIL_FRACTURE": Decimal("3.0"),
    "RUNG_SEPARATION": Decimal("2.5"),
    "HINGE_FAILURE": Decimal("2.0"),
    "SLIP_FALL": Decimal("1.5"),
    "LABEL_ILLEGIBLE": Decimal("1.0"),
}
CAPA_CREDIT_FACTOR = Decimal("0.25")
RISK_SCORE_CEILING = Decimal("100.00")
RISK_CLEAR_THRESHOLD = Decimal("25.00")

MIN_STRUCTURAL_MARGIN_PCT = Decimal("2.00")
MIN_SECTION_MODULUS_IN3 = Decimal("0.180")
MIN_WARNING_PICTOGRAMS = 2

LISTING_TERM_DAYS = 1825
MAX_RECALL_WINDOW_DAYS = 365
RETENTION_YEARS = 7

# PRD 3.4: the required test-code set is determined by the model's product_type,
# extended with RIVET_SHEAR whenever the campaign's pinned revision is RIVETED.
REQUIRED_TEST_CODES_BY_PRODUCT_TYPE = {
    "STEP_LADDER": ("STATIC_VERTICAL", "RAIL_BENDING", "SLIP_RESISTANCE"),
    "EXTENSION_LADDER": ("STATIC_VERTICAL", "RAIL_BENDING", "SLIP_RESISTANCE"),
    "PLATFORM_LADDER": ("STATIC_VERTICAL", "RAIL_BENDING", "SLIP_RESISTANCE"),
    "ARTICULATED_LADDER": (
        "STATIC_VERTICAL",
        "RAIL_BENDING",
        "SLIP_RESISTANCE",
        "HINGE_CYCLE",
    ),
    "MOBILE_SCAFFOLD_TOWER": ("STATIC_VERTICAL", "RAIL_BENDING", "SLIP_RESISTANCE"),
}


# ---------------------------------------------------------------- rounding
def rhu(value, places):
    """Round half up to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    return int(
        (Decimal(numerator) / Decimal(denominator)).to_integral_value(rounding=ROUND_CEILING)
    )


def add_days(instant, days):
    """PRD 2.4: day arithmetic adds exact 24-hour days."""
    return instant + timedelta(days=int(days))


def add_years(instant, years):
    """PRD 2.4/2.10: calendar-year arithmetic; 29 Feb maps to 1 March."""
    year = instant.year + int(years)
    month = instant.month
    day = instant.day
    if month == 2 and day == 29:
        month = 3
        day = 1
    return instant.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------- product derivation
def derive_product_requirements(product_type, material, duty_rating, working_length_ft):
    """scaffold 1.3 required_test_load_derivation."""
    rated_load_lb = RATED_LOAD_BY_DUTY[duty_rating]
    length = Decimal(working_length_ft)

    raw_steps = (length - LENGTH_BASELINE_FT) / LENGTH_STEP_FT
    length_steps = int(raw_steps.to_integral_value(rounding=ROUND_CEILING))
    if length_steps < 0:
        length_steps = 0

    raw_sf = (
        BASE_SAFETY_FACTOR
        + LENGTH_ADDER_PER_STEP * Decimal(length_steps)
        + TYPE_SF_BONUS[product_type]
        + (FIBERGLASS_SF_BONUS if material == "FIBERGLASS_PULTRUSION" else Decimal("0.00"))
    )
    safety_factor = rhu(min(raw_sf, SAFETY_FACTOR_CAP), 2)

    return {
        "rated_load_lb": rated_load_lb,
        "safety_factor": safety_factor,
        "required_test_load_lb": rhu(Decimal(rated_load_lb) * safety_factor, 2),
        "required_pull_force_lbf": rhu(Decimal(rated_load_lb) * JOINT_PULL_MULTIPLE, 2),
        "max_allowed_deflection_in": rhu(
            length * Decimal(12) / DEFLECTION_SPAN_DIVISOR, 3
        ),
    }


# ---------------------------------------------------------------- load test verdict
def load_test_verdict(product, applied_load_lb, measured_deflection_in, permanent_set_in):
    """scaffold 1.3 load_test_outcome; first failing criterion wins."""
    if applied_load_lb < product["required_test_load_lb"]:
        return "FAIL", "LOAD_BELOW_REQUIRED"
    if measured_deflection_in > product["max_allowed_deflection_in"]:
        return "FAIL", "DEFLECTION_EXCEEDED"
    if permanent_set_in > MAX_PERMANENT_SET_IN:
        return "FAIL", "PERMANENT_SET_EXCEEDED"
    return "PASS", None


def sample_margin_pct(pull_force_lbf, required_pull_force_lbf):
    """Per-sample whole-percent margin, rounded half up once per sample."""
    margin = (
        (Decimal(pull_force_lbf) - Decimal(required_pull_force_lbf))
        / Decimal(required_pull_force_lbf)
        * Decimal(100)
    )
    return int(rhu(margin, 0))


def conformance_index(margins):
    """Mean of the already-rounded per-sample integers; null on an empty set."""
    if not margins:
        return None
    total = Decimal(sum(margins))
    return rhu(total / Decimal(len(margins)), 2)


def required_joint_sample_count(produced_units):
    if not produced_units:
        return 0
    return max(
        MIN_JOINT_SAMPLES, ceil_div(produced_units, JOINT_SAMPLE_UNITS_PER_SAMPLE)
    )


# ---------------------------------------------------------------- audit escalation
def audit_escalation(prior_campaign):
    """scaffold 1.3 periodic_audit_sample_size steps 2-4."""
    if prior_campaign is None:
        prior_rate = None
        tier = "TIER_0"
    else:
        prior_rate = rhu(
            Decimal(prior_campaign["failed_test_count"])
            / Decimal(prior_campaign["audit_sample_size"])
            * Decimal(100),
            2,
        )
        if prior_rate == Decimal("0.00"):
            tier = "TIER_0"
        elif prior_rate <= Decimal("20.00"):
            tier = "TIER_1"
        elif prior_rate <= Decimal("40.00"):
            tier = "TIER_2"
        else:
            tier = "TIER_3"
    sample_size = BASE_AUDIT_SAMPLE + ESCALATION_ADDER_BY_TIER[tier]
    return prior_rate, tier, sample_size


# ---------------------------------------------------------------- risk scores
def incident_points(injury_severity, incident_type):
    return rhu(SEVERITY_WEIGHT[injury_severity] * TYPE_WEIGHT[incident_type], 2)
