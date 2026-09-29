"""Domain thresholds and constants stated by the PRD."""

# The logical clock's mandated startup value before any client sets it.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Drill readiness ---------------------------------------------------------
REQUIRED_DRILL_TYPES = {
    "MINIMAL_SEDATION": ["AIRWAY_OBSTRUCTION", "LOCAL_ANESTHETIC_TOXICITY"],
    "MODERATE_SEDATION": [
        "AIRWAY_OBSTRUCTION",
        "LOCAL_ANESTHETIC_TOXICITY",
        "LARYNGOSPASM",
        "CARDIAC_ARREST",
    ],
    "DEEP_SEDATION_GENERAL": [
        "AIRWAY_OBSTRUCTION",
        "LOCAL_ANESTHETIC_TOXICITY",
        "LARYNGOSPASM",
        "CARDIAC_ARREST",
        "MALIGNANT_HYPERTHERMIA",
    ],
}
DRILL_WINDOW_DAYS = 365
DRILL_COMPLIANCE_FLOOR = 0.75

# --- Inspection scoring ------------------------------------------------------
INSPECTION_BASE_SCORE = 100
MINOR_DEFICIENCY_DEDUCTION = 2
MAJOR_DEFICIENCY_DEDUCTION = 7
CRITICAL_DEFICIENCY_DEDUCTION = 25
INSPECTION_PASS_SCORE = 70

# --- Permit term / remediation ----------------------------------------------
PERMIT_TERM_MONTHS = 24
REMEDIATION_WINDOW_DAYS = 30

# --- Sedation privilege ------------------------------------------------------
PRIVILEGE_BY_PERMIT_STATUS = {
    "APPLIED": "UNPERMITTED",
    "INSPECTION_PENDING": "UNPERMITTED",
    "EXPIRED": "UNPERMITTED",
    "REVOKED": "UNPERMITTED",
    "ACTIVE": "PERMITTED",
    "PROBATION": "RESTRICTED",
    "SUSPENDED": "SUSPENDED",
}
ANESTHESIA_LEVEL_RANK = {
    "LOCAL_ONLY": 0,
    "MINIMAL_SEDATION": 1,
    "MODERATE_SEDATION": 2,
    "DEEP_SEDATION_GENERAL": 3,
}

# --- Recovery ----------------------------------------------------------------
RECOVERY_MINUTES_REQUIRED = {
    "LOCAL_ONLY": 0,
    "MINIMAL_SEDATION": 20,
    "MODERATE_SEDATION": 45,
    "DEEP_SEDATION_GENERAL": 90,
}

# --- Risk scoring ------------------------------------------------------------
ASA_POINTS_PER_CLASS = 10
AIRWAY_POINTS_PER_CLASS_ABOVE_2 = 8
AGE_POINTS_ELDERLY = 6
AGE_POINTS_INFANT = 4
ELDERLY_AGE_YEARS = 70
INFANT_AGE_YEARS = 3
COMORBIDITY_POINTS_EACH = 3
COMORBIDITY_POINTS_CAP = 12
WEIGHT_POINTS = 5
WEIGHT_THRESHOLD_KG = 120
LEVEL_MULTIPLIER = {
    "LOCAL_ONLY": 0.5,
    "MINIMAL_SEDATION": 0.8,
    "MODERATE_SEDATION": 1.0,
    "DEEP_SEDATION_GENERAL": 1.3,
}
PENALTY_NPO_SHORTFALL = 15
PENALTY_NO_ESCORT = 10
PENALTY_RESTRICTED_PRIVILEGE = 6
RISK_BAND_FLOORS = {"ELEVATED": 25, "HIGH": 40, "PROHIBITIVE": 55}

# --- Fasting -----------------------------------------------------------------
NPO_SOLIDS_MINUTES_REQUIRED = 480
NPO_CLEARS_MINUTES_REQUIRED = 120

# --- Benefit allocation ------------------------------------------------------
MEDICAL_COINSURANCE = 0.80
DENTAL_COINSURANCE = 0.50
MEDICAL_FIRST_CATEGORIES = ["PATHOLOGY", "TRAUMA", "TMJ", "ORTHOGNATHIC"]
MAX_SERVICE_LINES = 8

# --- Implant pricing ---------------------------------------------------------
RESTOCKING_TIERS = [(50_000, 0.15), (150_000, 0.10), (None, 0.05)]
CONSIGNMENT_CREDIT_RATE = 0.20
AUTO_SIZE_DIAMETER_TOLERANCE_MM = 0.5
AUTO_SIZE_LENGTH_TOLERANCE_MM = 2.0

# --- Adverse events ---------------------------------------------------------
REPORTING_DEADLINE_HOURS = {"SENTINEL": 24, "SEVERE": 72}
REPORTING_DEADLINE_DAYS = {"MODERATE": 7, "MINOR": 30}

# --- Imaging -----------------------------------------------------------------
DOSE_REFERENCE_LEVEL = {
    "PANORAMIC": 100.0,
    "CEPHALOMETRIC": 60.0,
    "CBCT_SMALL_FOV": 250.0,
    "CBCT_LARGE_FOV": 900.0,
}
CBCT_LARGE_FOV_JUSTIFICATIONS = [
    "ORTHOGNATHIC_PLANNING",
    "PATHOLOGY_STAGING",
    "TRAUMA_SURVEY",
]
CBCT_SMALL_FOV_JUSTIFICATIONS = [
    "IMPLANT_PLANNING",
    "THIRD_MOLAR_ASSESSMENT",
    "PATHOLOGY_STAGING",
    "TRAUMA_SURVEY",
]
RETENTION_FLOOR_YEARS = 7
AGE_OF_MAJORITY_YEARS = 18

# --- Block time / scheduling ------------------------------------------------
DEFAULT_RELEASE_DEADLINE_HOURS = 48
MAX_RELEASE_DEADLINE_HOURS = 336
DEFAULT_TURNOVER_BUFFER_MINUTES = 15
SWEEP_UTILIZATION_KEEP_FLOOR = 60.00
COMMITTING_SCHEDULING_STATUSES = ["BLOCK_HELD", "CONFIRMED", "IN_RECOVERY", "COMPLETED"]

# --- Pagination --------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --- Practice defaults ------------------------------------------------------
DEFAULT_CONSIGNMENT_CREDIT_LIMIT_CENTS = 500_000
DEFAULT_DENTAL_ANNUAL_REMAINING_CENTS = 150_000

ALL_ROLES = [
    "PracticeAdministrator",
    "SchedulingCoordinator",
    "BenefitsSpecialist",
    "InventoryManager",
    "Surgeon",
    "AnesthesiaCoordinator",
    "QualityReviewer",
]
