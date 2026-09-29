"""Domain constants for the gluten-free certification API, taken from the PRD."""

# --- API surface ------------------------------------------------------------
API_PREFIX = "/gfco"

# --- logical clock ----------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"

# --- sanitation validation --------------------------------------------------
SANITATION_SWAB_LIMIT_PPM = 5
SANITATION_VALIDITY_DAYS = 365

# --- nonconformance penalty points -----------------------------------------
NC_PENALTY_POINTS = {"MINOR": 2, "MAJOR": 8, "CRITICAL": 25}

# --- applicant compliance posture ------------------------------------------
POSTURE_SUSPENDED_CERT_PENALTY = 5
POSTURE_SUBSTANTIATED_COMPLAINT_PENALTY = 15
POSTURE_GOOD_STANDING_FLOOR = 85
POSTURE_WATCH_FLOOR = 60
POSTURE_ROLLING_WINDOW_DAYS = 365

# --- supplier documents -----------------------------------------------------
REQUIRED_DOC_TYPES = {
    "INHERENTLY_GF": {"ALLERGEN_STATEMENT"},
    "GF_PROCESSED": {"ALLERGEN_STATEMENT", "PROCESS_FLOW"},
    "HIGH_RISK_GRAIN": {"ALLERGEN_STATEMENT", "PROCESS_FLOW", "COA"},
}
MAX_COA_PPM_CLAIM = {
    "INHERENTLY_GF": 20,
    "GF_PROCESSED": 10,
    "HIGH_RISK_GRAIN": 5,
}

# --- threshold standard selection ------------------------------------------
PROGRAM_THRESHOLD_PPM = 20
TIER_THRESHOLD_PPM = {"STANDARD": 20, "PREMIUM": 10, "ELITE": 5}
INGREDIENT_THRESHOLD_PPM = {
    "INHERENTLY_GF": 20,
    "GF_PROCESSED": 15,
    "HIGH_RISK_GRAIN": 10,
}
EQUIPMENT_THRESHOLD_PPM = {True: 10, False: 20}
OPERATIONS_THRESHOLD_PPM = {"NONE": 20, "ADJACENT_LINES": 10, "SAME_LINE": 5}
THRESHOLD_PENALTY_PPM = 2
THRESHOLD_FLOOR_PPM = 5

# --- sampling plan ----------------------------------------------------------
SAMPLING_BASE_LOTS_PER_LINE = 4
SAMPLING_RISK_WEIGHT = {
    "INHERENTLY_GF": 0.25,
    "GF_PROCESSED": 0.5,
    "HIGH_RISK_GRAIN": 1.0,
}
SAMPLING_LOW_INCLUSION_PCT = 2
SAMPLING_LOW_INCLUSION_FACTOR = 0.5
SAMPLING_MIN_LOTS_PER_YEAR = 2
SAMPLING_MIN_EXCLUSION_DAYS = 7
DAYS_PER_YEAR = 365

# --- audit scoring ----------------------------------------------------------
AUDIT_CATEGORY_WEIGHT = {
    "SHARED_EQUIPMENT": 1.5,
    "AIR_HANDLING": 1.25,
    "SANITATION": 1.25,
    "DOCUMENTATION": 1.0,
    "LABELING": 1.0,
    "THRESHOLD_EXCEEDANCE": 1.5,
}
AUDIT_VERIFIED_HALVING_FACTOR = 0.5
AUDIT_ESCALATION_FLAT_PENALTY = 10
AUDIT_PASS_SCORE = 90
AUDIT_CONDITIONAL_SCORE = 75

# --- corrective actions -----------------------------------------------------
MAX_CA_REVISIONS = 2
CA_DUE_DAYS = {"CRITICAL": 15, "MAJOR": 30, "MINOR": 90}

# --- certification fees -----------------------------------------------------
CERT_BASE_FEE_CENTS = 98000
CERT_FEE_PER_INGREDIENT_CENTS = 6000
CERT_SHARED_EQUIPMENT_FEE_CENTS = 45000
FEE_RATE_TIER_1_MAX_CENTS = 150000
FEE_RATE_TIER_2_MAX_CENTS = 250000
FEE_RATE_TIER_1 = 0.20
FEE_RATE_TIER_2 = 0.15
FEE_RATE_TIER_3 = 0.10
FEE_REFUND_WINDOW_DAYS = 30

# --- certificate lifecycle --------------------------------------------------
CERT_VALIDITY_DAYS = 1095
SURVEILLANCE_DUE_DAYS = 365
SURVEILLANCE_GRACE_DAYS = 60

# --- change notifications ---------------------------------------------------
CHANGE_NOTICE_DAYS = 30
NOTICE_REQUIRING_CHANGE_TYPES = ("INGREDIENT_SUBSTITUTION", "SUPPLIER_CHANGE")

# --- consumer complaints ----------------------------------------------------
TRIAGE_PRIORITY_BY_SEVERITY = {
    "ANAPHYLAXIS": "P1",
    "SEVERE": "P1",
    "MODERATE": "P2",
    "MILD": "P3",
}
RECALL_LOOKBACK_DAYS = 90
RECALL_MAX_CANDIDATES = 3

# --- surveillance sweep counter keys ---------------------------------------
SWEEP_COUNTER_KEYS = (
    "run_at",
    "certificates_marked_due",
    "certificates_marked_overdue",
    "certificates_suspended",
    "certificates_expired",
    "documents_expired",
    "ingredients_blocked",
    "facility_validations_expired",
    "audits_cancelled",
    "nonconformances_escalated",
)
