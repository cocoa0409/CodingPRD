"""Domain vocabulary, constant tables and row lookups."""
from decimal import Decimal

from db import db, ordered
from errors import ApiError

# ------------------------------------------------------------------ enums ---

PERMIT_LEVELS = ("MINIMAL_SEDATION", "MODERATE_SEDATION", "DEEP_SEDATION_GENERAL")
PERMIT_STATUSES = ("APPLIED", "INSPECTION_PENDING", "ACTIVE", "PROBATION",
                   "SUSPENDED", "EXPIRED", "REVOKED")
ENFORCEMENT_REASONS = ("CRITICAL_DEFICIENCY", "DEFICIENCY_SCORE", "SENTINEL_EVENT",
                       "DRILL_LAPSE", "PERMIT_EXPIRY")
INSPECTION_STATUSES = ("SCHEDULED", "PASSED", "FAILED_CORRECTABLE", "FAILED_CRITICAL")
DRILL_TYPES = ("AIRWAY_OBSTRUCTION", "LARYNGOSPASM", "MALIGNANT_HYPERTHERMIA",
               "CARDIAC_ARREST", "LOCAL_ANESTHETIC_TOXICITY")
STAFF_ROLE_TYPES = ("SURGEON", "ANESTHESIA_MONITOR", "RECOVERY_NURSE", "INVENTORY_TECH")
BLOCK_STATUSES = ("RESERVED", "PARTIALLY_RELEASED", "RELEASED")
PROCEDURE_CATEGORIES = ("THIRD_MOLAR", "ORTHOGNATHIC", "PATHOLOGY", "TRAUMA", "IMPLANT", "TMJ")
ANESTHESIA_LEVELS = ("LOCAL_ONLY", "MINIMAL_SEDATION", "MODERATE_SEDATION", "DEEP_SEDATION_GENERAL")
SCHEDULING_STATUSES = ("DRAFT", "BLOCK_HELD", "CONFIRMED", "IN_RECOVERY", "COMPLETED", "CANCELLED")
CLEARANCE_STATUSES = ("NOT_EVALUATED", "EVALUATED", "CLEARED", "DEFERRED")
REFERRAL_STATUSES = ("NOT_REQUIRED", "PENDING", "ACKNOWLEDGED")
CANCELLATION_REASONS = ("PATIENT_REQUEST", "CLINICAL", "PRIVILEGE_SUSPENDED")
EVALUATION_STATUSES = ("DRAFT", "SIGNED", "VERIFIED", "SUPERSEDED", "VOIDED")
RISK_BANDS = ("LOW", "ELEVATED", "HIGH", "PROHIBITIVE")
BENEFIT_ROUTES = ("MEDICAL_PRIMARY", "DENTAL_PRIMARY", "SPLIT", "SELF_PAY")
BENEFIT_CLASSES = ("MEDICAL", "DENTAL")
DETERMINATION_STATUSES = ("DRAFT", "SUBMITTED", "PENDED", "APPROVED", "DENIED")
PEND_REASONS = ("MISSING_OP_REPORT", "MEDICAL_NECESSITY_REVIEW", "COORDINATION_OF_BENEFITS")
DENIAL_REASONS = ("NOT_COVERED_BENEFIT", "EXCEEDS_ANNUAL_MAX", "NO_MEDICAL_NECESSITY")
LOT_STATUSES = ("AVAILABLE", "QUARANTINED")
SELECTION_MODES = ("EXPLICIT", "AUTO_SIZED")
RESERVATION_STATUSES = ("HELD", "CONSUMED", "RELEASED", "SHORTED")
EVENT_TYPES = ("AIRWAY_OBSTRUCTION", "HYPOXEMIA", "PROLONGED_RECOVERY",
               "UNPLANNED_INTUBATION", "NERVE_INJURY", "DEATH")
SEVERITIES = ("MINOR", "MODERATE", "SEVERE", "SENTINEL")
EVENT_STATUSES = ("REPORTED", "UNDER_MORBIDITY_REVIEW", "REVIEW_SIGNED_OFF", "CLOSED")
MODALITIES = ("PANORAMIC", "CEPHALOMETRIC", "CBCT_SMALL_FOV", "CBCT_LARGE_FOV")
JUSTIFICATION_CODES = ("IMPLANT_PLANNING", "THIRD_MOLAR_ASSESSMENT", "PATHOLOGY_STAGING",
                       "TRAUMA_SURVEY", "ORTHOGNATHIC_PLANNING")
DOSE_FLAGS = ("WITHIN_PROTOCOL", "ABOVE_REFERENCE_LEVEL")
PRIVILEGE_STATES = ("UNPERMITTED", "PERMITTED", "RESTRICTED", "SUSPENDED")

# -------------------------------------------------------------- constants ---

LEVEL_RANK = {
    "LOCAL_ONLY": 0,
    "MINIMAL_SEDATION": 1,
    "MODERATE_SEDATION": 2,
    "DEEP_SEDATION_GENERAL": 3,
}

REQUIRED_DRILL_TYPES = {
    "MINIMAL_SEDATION": ["AIRWAY_OBSTRUCTION", "LOCAL_ANESTHETIC_TOXICITY"],
    "MODERATE_SEDATION": ["AIRWAY_OBSTRUCTION", "LOCAL_ANESTHETIC_TOXICITY",
                          "LARYNGOSPASM", "CARDIAC_ARREST"],
    "DEEP_SEDATION_GENERAL": ["AIRWAY_OBSTRUCTION", "LOCAL_ANESTHETIC_TOXICITY",
                              "LARYNGOSPASM", "CARDIAC_ARREST", "MALIGNANT_HYPERTHERMIA"],
}

DRILL_WINDOW_DAYS = 365
DRILL_COMPLIANCE_FLOOR = Decimal("0.75")

PRIVILEGE_BY_PERMIT_STATUS = {
    "APPLIED": "UNPERMITTED",
    "INSPECTION_PENDING": "UNPERMITTED",
    "ACTIVE": "PERMITTED",
    "PROBATION": "RESTRICTED",
    "SUSPENDED": "SUSPENDED",
    "EXPIRED": "UNPERMITTED",
    "REVOKED": "UNPERMITTED",
}

# Which planned anesthesia levels a privilege state admits.
PRIVILEGE_ADMITS = {
    "UNPERMITTED": ("LOCAL_ONLY",),
    "SUSPENDED": ("LOCAL_ONLY",),
    "RESTRICTED": ("LOCAL_ONLY", "MINIMAL_SEDATION", "MODERATE_SEDATION"),
    "PERMITTED": ("LOCAL_ONLY", "MINIMAL_SEDATION", "MODERATE_SEDATION", "DEEP_SEDATION_GENERAL"),
}

RECOVERY_MINUTES_BY_LEVEL = {
    "LOCAL_ONLY": 0,
    "MINIMAL_SEDATION": 20,
    "MODERATE_SEDATION": 45,
    "DEEP_SEDATION_GENERAL": 90,
}

LEVEL_MULTIPLIER = {
    "LOCAL_ONLY": Decimal("0.5"),
    "MINIMAL_SEDATION": Decimal("0.8"),
    "MODERATE_SEDATION": Decimal("1.0"),
    "DEEP_SEDATION_GENERAL": Decimal("1.3"),
}

COMORBIDITY_POINT_CAP = 12
HEAVY_WEIGHT_KG = Decimal("120")
NPO_SOLIDS_MINUTES_MIN = 480
NPO_CLEARS_MINUTES_MIN = 120
BAND_ELEVATED_FLOOR = Decimal("25")
BAND_HIGH_FLOOR = Decimal("40")
BAND_PROHIBITIVE_FLOOR = Decimal("55")

REFERRAL_CATEGORIES = ("THIRD_MOLAR", "ORTHOGNATHIC")
MEDICAL_LEANING_CATEGORIES = ("PATHOLOGY", "TRAUMA", "TMJ", "ORTHOGNATHIC")

MEDICAL_RATE = Decimal("0.80")
DENTAL_RATE = Decimal("0.50")
SERVICE_LINE_MAX = 8

RESTOCKING_TIERS = ((50000, Decimal("0.15")), (150000, Decimal("0.10")), (None, Decimal("0.05")))
CONSIGNMENT_CREDIT_RATE = Decimal("0.20")
DIAMETER_TOLERANCE_MM = Decimal("0.5")
LENGTH_TOLERANCE_MM = Decimal("2.0")

REPORTING_WINDOW_HOURS = {
    "SENTINEL": 24,
    "SEVERE": 72,
    "MODERATE": 24 * 7,
    "MINOR": 24 * 30,
}

DOSE_REFERENCE_LEVELS = {
    "PANORAMIC": Decimal("100.0"),
    "CEPHALOMETRIC": Decimal("60.0"),
    "CBCT_SMALL_FOV": Decimal("250.0"),
    "CBCT_LARGE_FOV": Decimal("900.0"),
}

JUSTIFICATION_BY_MODALITY = {
    "PANORAMIC": list(JUSTIFICATION_CODES),
    "CEPHALOMETRIC": list(JUSTIFICATION_CODES),
    "CBCT_SMALL_FOV": ["IMPLANT_PLANNING", "THIRD_MOLAR_ASSESSMENT",
                       "PATHOLOGY_STAGING", "TRAUMA_SURVEY"],
    "CBCT_LARGE_FOV": ["ORTHOGNATHIC_PLANNING", "PATHOLOGY_STAGING", "TRAUMA_SURVEY"],
}

IMAGING_RETENTION_YEARS = 7
ADULT_AGE_YEARS = 18
PERMIT_TERM_MONTHS = 24
REMEDIATION_WINDOW_DAYS = 30
INSPECTION_PASS_SCORE = 70
UTILIZATION_SWEEP_FLOOR = Decimal("60.00")

COMMITTING_CASE_STATUSES = ("BLOCK_HELD", "CONFIRMED", "IN_RECOVERY", "COMPLETED")
TERMINAL_CASE_STATUSES = ("COMPLETED", "CANCELLED")
NON_TERMINAL_CASE_STATUSES = ("DRAFT", "BLOCK_HELD", "CONFIRMED", "IN_RECOVERY")
VOIDABLE_EVALUATION_STATUSES = ("DRAFT", "SIGNED", "VERIFIED")

# --------------------------------------------------------------- lookups ---


def _find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return collection.get(row_id)


def get_practice(row_id):
    return _find(db.practices, row_id)


def get_permit(row_id):
    return _find(db.permits, row_id)


def get_inspection(row_id):
    return _find(db.inspections, row_id)


def get_drill(row_id):
    return _find(db.drills, row_id)


def get_staff(row_id):
    return _find(db.staff, row_id)


def get_patient(row_id):
    return _find(db.patients, row_id)


def get_block(row_id):
    return _find(db.blocks, row_id)


def get_case(row_id):
    return _find(db.cases, row_id)


def get_evaluation(row_id):
    return _find(db.evaluations, row_id)


def get_determination(row_id):
    return _find(db.determinations, row_id)


def get_lot(row_id):
    return _find(db.lots, row_id)


def get_reservation(row_id):
    return _find(db.reservations, row_id)


def get_event(row_id):
    return _find(db.events, row_id)


def get_study(row_id):
    return _find(db.studies, row_id)


def path_row(collection, row_id):
    row = _find(collection, row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return row


def referenced_row(collection, row_id):
    row = _find(collection, row_id)
    if row is None:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return row


def rows_of_practice(collection, practice_id):
    return ordered([r for r in collection.values() if r.get("practice_id") == practice_id])


def open_permit(practice_id):
    """The practice's single non-terminal permit, if any (PRD 3.1)."""
    candidates = [p for p in db.permits.values()
                  if p["practice_id"] == practice_id
                  and p["status"] not in ("EXPIRED", "REVOKED")]
    if not candidates:
        return None
    return ordered(candidates)[-1]


def cases_of_practice(practice_id):
    return ordered([c for c in db.cases.values() if c["practice_id"] == practice_id])


def evaluations_of_case(case_id):
    return ordered([e for e in db.evaluations.values() if e["case_id"] == case_id])


def reservations_of_case(case_id):
    return ordered([r for r in db.reservations.values() if r["case_id"] == case_id])


def reservations_of_lot(lot_id):
    return ordered([r for r in db.reservations.values() if r["lot_id"] == lot_id])


def determinations_of_case(case_id):
    return ordered([d for d in db.determinations.values() if d["case_id"] == case_id])


def reservation_practice_id(reservation):
    lot = get_lot(reservation["lot_id"])
    return lot["practice_id"] if lot else None
