"""System-wide constants per PRD/SCAFFOLD."""

# --- Roles ---
ROLE_PATIENT = "Patient"
ROLE_DOCTOR = "Doctor"
ROLE_PHARMACIST = "Pharmacist"
ROLE_ADMIN = "PlatformAdmin"

VALID_ROLES = {ROLE_PATIENT, ROLE_DOCTOR, ROLE_PHARMACIST, ROLE_ADMIN}

# --- Pagination ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# --- Triage severity scoring (calculations.triage_severity_score) ---
CHIEF_COMPLAINT_FACTOR = 10
VITAL_ANOMALY_FACTOR = 2
RISK_FACTOR = 3
RISK_TABLE = {
    "DIABETES": 1,
    "HYPERTENSION": 1,
    "IMMUNOCOMPROMISED": 2,
}

# --- Consultation fee (calculations.consultation_fee) ---
TIER1_CAP_MIN = 10
TIER1_RATE_CENTS = 100
TIER2_RATE_CENTS = 200

# --- Insurance reimbursement (calculations.insurance_reimbursement) ---
DEDUCTIBLE_CENTS = 5000
INSURANCE_TIER1_CAP_CENTS = 10000
INSURANCE_TIER1_RATE_IN_SCOPE = 0.70
INSURANCE_TIER2_RATE_IN_SCOPE = 0.50
INSURANCE_TIER1_RATE_OUT_OF_SCOPE = 0.30
INSURANCE_TIER2_RATE_OUT_OF_SCOPE = 0.20
ANNUAL_CAP_CENTS = 1000000

# Diseases in scope for insurance reimbursement (PRD §3.7; test constants).
INSURANCE_IN_SCOPE_DISEASES = {
    "HYPERTENSION",
    "DIABETES",
    "ASTHMA",
}

# --- Prescription rules (PRD §3.6; test constants) ---
PRESCRIPTION_ALLOWED_DISEASES = {
    "HYPERTENSION",
    "DIABETES",
    "ASTHMA",
}
MAX_REVISIONS = 3

# --- Appointment ---
SLOT_MINUTES = 30
GRACE_BEFORE_MINUTES = 5

# --- Follow-up ---
VALID_REMINDER_CHANNELS = {"SMS", "EMAIL", "APP_PUSH"}
ABNORMAL_THRESHOLD = 3

# Vital question prefix for vital anomaly scoring
VITAL_PREFIX = "VITAL_"
