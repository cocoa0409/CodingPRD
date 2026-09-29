"""The fourteen pinned calculations (PRD sections 2.8, 2.9, 3.x)."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- enums / constants ------------------------------------------------------

INGREDIENT_CLASSES = (
    "VITAMIN",
    "MINERAL",
    "BOTANICAL",
    "AMINO_ACID",
    "PROBIOTIC",
    "EXCLUDED_SUBSTANCE",
)
ALLERGEN_CODES = (
    "MILK",
    "EGG",
    "FISH",
    "CRUSTACEAN_SHELLFISH",
    "TREE_NUT",
    "PEANUT",
    "WHEAT",
    "SOYBEAN",
    "SESAME",
)
CONTRAINDICATION_CODES = ("ANTICOAGULANT", "PREGNANCY", "PEDIATRIC", "IMMUNOSUPPRESSANT")
ELIGIBILITY_STATUSES = (
    "DRAFT_ASSESSMENT",
    "GRANDFATHERED",
    "NDI_REQUIRED",
    "NDI_PENDING",
    "NDI_ACKNOWLEDGED",
    "NDI_OBJECTED",
    "INELIGIBLE",
)
NDI_REQUIRED_STATES = ("NDI_REQUIRED", "NDI_PENDING", "NDI_ACKNOWLEDGED", "NDI_OBJECTED")
LABEL_CLEARED_STATES = ("GRANDFATHERED", "NDI_ACKNOWLEDGED")

CLAIM_TYPES = ("STRUCTURE_FUNCTION", "NUTRIENT_CONTENT", "GENERAL_WELLBEING")
DISCLAIMER_CLAIM_TYPES = ("STRUCTURE_FUNCTION", "GENERAL_WELLBEING")
PANEL_FORMATS = ("STANDARD", "SIMPLIFIED", "LINEAR")
REPORTER_TYPES = ("CONSUMER", "HEALTHCARE_PROVIDER", "DISTRIBUTOR")
OUTCOME_CODES = (
    "DEATH",
    "LIFE_THREATENING",
    "HOSPITALIZATION",
    "DISABILITY",
    "CONGENITAL_ANOMALY",
    "INTERVENTION_REQUIRED",
    "OTHER",
)
SERIOUS_OUTCOME_CODES = (
    "DEATH",
    "LIFE_THREATENING",
    "HOSPITALIZATION",
    "DISABILITY",
    "CONGENITAL_ANOMALY",
)
STUDY_TYPES = ("RCT_HUMAN", "OBSERVATIONAL_HUMAN", "ANIMAL", "IN_VITRO")
IDENTITY_METHODS = ("HPTLC", "HPLC", "MASS_SPEC", "DNA_BARCODE", "MICROSCOPY", "ORGANOLEPTIC")
SUPPLIER_DECISIONS = ("QUALIFY", "PROBATION", "REINSTATE", "DISQUALIFY")
REVIEW_DECISIONS = ("ACCEPT", "REJECT")
AGENCY_RESPONSES = ("ACKNOWLEDGE", "OBJECT")

STUDY_BASE_WEIGHT = {"RCT_HUMAN": 30, "OBSERVATIONAL_HUMAN": 18, "ANIMAL": 8, "IN_VITRO": 4}
NON_HUMAN_STUDY_TYPES = ("ANIMAL", "IN_VITRO")
ACCEPTANCE_THRESHOLD = Decimal("65.00")
SCORE_CEILING = Decimal("100.00")
SCREENING_SUBJECT_DENOM = 50
FINAL_SUBJECT_DENOM = 100

NOTIFICATION_WINDOW_DAYS = 30
WAITING_PERIOD_DAYS = 75
CHANGEOVER_BUFFER_DAYS = 7
SERIOUS_SUBMISSION_BUSINESS_DAYS = 15
RETENTION_YEARS = 6

HEADER_BLOCK_LINES = 4
LINEAR_FIXED_ALLOWANCE = 8
ALWAYS_REQUIRED_CODE = "PEDIATRIC_KEEP_OUT_OF_REACH"

BASE_FLOOR = 10
SERIOUS_AE_WEIGHT = 20
NONSERIOUS_AE_WEIGHT = 6
LATE_NOTICE_WEIGHT = 15
REJECTED_COA_WEIGHT = 8
INDEX_CEILING = 100
RESTRICTED_THRESHOLD = 70
FROZEN_THRESHOLD = 90

GRANDFATHER_INTAKE_LIMIT = Decimal("5000")
AUDIT_SCORE_FLOOR = 70
MAX_REVISION_ROUNDS = 3

ASSAY_MIN_PCT = Decimal("95.0")
ASSAY_MAX_PCT = Decimal("120.0")
APPROVED_METHODS = {
    "VITAMIN": ("HPLC", "MASS_SPEC"),
    "MINERAL": ("MASS_SPEC",),
    "BOTANICAL": ("HPTLC", "DNA_BARCODE", "MASS_SPEC"),
    "AMINO_ACID": ("HPLC", "MASS_SPEC"),
    "PROBIOTIC": ("DNA_BARCODE",),
    "EXCLUDED_SUBSTANCE": (),
}

SERVING_SIZE_PATTERN = r"^[0-9]+(\.[0-9]+)? (capsule|capsules|tablet|tablets|scoop|scoops|mL|g)$"

FDA_DISCLAIMER = (
    "This statement has not been evaluated by the Food and Drug Administration. "
    "This product is not intended to diagnose, treat, cure, or prevent any disease."
)


# --- numeric helpers --------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def d2(value):
    """Round half up to two decimal places."""
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def whole(value):
    """Round half up to a whole number (12.5 -> 13)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num2(value):
    """JSON representation of a 2-decimal quantity."""
    return float(d2(value))


# --- substantiation scoring -------------------------------------------------

def _study_points(study, denom, peer_enforced):
    base_weight = dec(STUDY_BASE_WEIGHT[study["study_type"]])
    if study["study_type"] in NON_HUMAN_STUDY_TYPES:
        subject_factor = Decimal("1.0")
    else:
        subject_factor = dec(study["subject_count"]) / dec(denom)
        if subject_factor > Decimal("1.0"):
            subject_factor = Decimal("1.0")
    dose_factor = Decimal("1.0") if study["dose_match"] else Decimal("0.60")
    if not peer_enforced:
        peer_factor = Decimal("1.0")
    else:
        peer_factor = Decimal("1.0") if study["peer_reviewed"] else Decimal("0.50")
    # PINNED: each study is rounded to two decimals BEFORE it is added to anything.
    return d2(base_weight * subject_factor * dose_factor * peer_factor)


def _score(studies, denom, peer_enforced):
    total = Decimal("0.00")
    for study in studies:
        total += _study_points(study, denom, peer_enforced)
    total = d2(total)
    if total > SCORE_CEILING:
        total = SCORE_CEILING
    return total


def screening_score(studies):
    """Provisional screening variant: every study, denominator 50, peer review not enforced."""
    return _score(studies, SCREENING_SUBJECT_DENOM, False)


def final_score(studies):
    """Competent-and-reliable variant: peer-reviewed studies only, denominator 100, peer enforced."""
    included = [s for s in studies if s.get("peer_reviewed") is True]
    return _score(included, FINAL_SUBJECT_DENOM, True)


# --- panel and line arithmetic ----------------------------------------------

def percent_dv(amount_per_serving_mg, rdi_mg):
    """(dv_established, percent_dv_declared) for one supplement-facts line."""
    if rdi_mg is None:
        return False, None
    raw = dec(amount_per_serving_mg) / dec(rdi_mg) * dec(100)
    if raw > 0 and raw < Decimal("0.5"):
        return True, 1
    return True, whole(raw)


def panel_lines_allowed(panel_format, net_quantity_g):
    if panel_format == "LINEAR":
        return LINEAR_FIXED_ALLOWANCE
    if panel_format == "STANDARD":
        # floor division first, then the upper cap, then the lower floor.
        value = int(dec(net_quantity_g) / dec(10)) + 12
        return max(20, min(40, value))
    value = int(dec(net_quantity_g) / dec(20)) + 8
    return max(12, min(24, value))


def servings_from_weight(net_quantity_g, serving_weight_g):
    return whole(dec(net_quantity_g) / dec(serving_weight_g))


# --- compliance risk index --------------------------------------------------

def risk_base(product):
    return (
        BASE_FLOOR
        + SERIOUS_AE_WEIGHT * product["serious_ae_count"]
        + NONSERIOUS_AE_WEIGHT * product["nonserious_ae_count"]
        + LATE_NOTICE_WEIGHT * product["late_notification_count"]
        + REJECTED_COA_WEIGHT * product["rejected_coa_count"]
    )


def escalation_surcharge(base):
    """PINNED: the tier is selected from the pre-surcharge base alone."""
    if base < 30:
        return 0
    if base < 60:
        return 5
    return 12


def risk_index(product):
    base = risk_base(product)
    return min(INDEX_CEILING, base + escalation_surcharge(base))


# --- calendar arithmetic ----------------------------------------------------

def add_days(value, days):
    return value + timedelta(days=days)


def business_day_due_date(received_date, business_days=SERIOUS_SUBMISSION_BUSINESS_DAYS):
    """`received_date` is day zero and is never counted; Saturdays and Sundays are skipped."""
    counted = 0
    cursor = received_date
    while counted < business_days:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:
            counted += 1
    return cursor


def retention_date(received_date, years=RETENTION_YEARS):
    """Same month and day `years` later; a February 29 anniversary maps to February 28."""
    year = received_date.year + years
    month = received_date.month
    day = received_date.day
    if month == 2 and day == 29:
        day = 28
    return date(year, month, day)


# --- certificate of analysis ------------------------------------------------

def coa_acceptable(identity_match, assay_percent_of_label, heavy_metals_pass, microbial_pass):
    assay = dec(assay_percent_of_label)
    return bool(
        identity_match is True
        and assay >= ASSAY_MIN_PCT
        and assay <= ASSAY_MAX_PCT
        and heavy_metals_pass is True
        and microbial_pass is True
    )
