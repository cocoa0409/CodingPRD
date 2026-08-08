"""Domain constants, verbatim from the PRD / scaffold specification."""

# --- Roles -------------------------------------------------------------------
ROLES = {
    "JointUseCoordinator",
    "Engineer",
    "PermitOfficer",
    "FieldAuditor",
    "Attacher",
}

# --- Shot clocks / validity windows (whole days on the logical clock) --------
SURVEY_SHOT_CLOCK_DAYS = 45
ESTIMATE_SHOT_CLOCK_DAYS = 14
PERMIT_SHOT_CLOCK_DAYS = 60
ESTIMATE_VALIDITY_DAYS = 30
INVOICE_DUE_DAYS = 30

# --- make_ready_fee ----------------------------------------------------------
PER_EXISTING_ATTACHER_TRANSFER_CENTS = 7500
COMPLEXITY_MULTIPLIER_SIMPLE = "1.0"
COMPLEXITY_MULTIPLIER_COMPLEX = "1.75"
CONTINGENCY_PCT = "0.15"

# --- annual rental -----------------------------------------------------------
DAYS_IN_YEAR = 365

# --- unauthorized finding back-rental & penalty ------------------------------
UNAUTHORIZED_TIER1_MAX_INCHES = 12
PENALTY_TIER1_CENTS = 25000
PENALTY_TIER2_CENTS = 50000
BACK_RENTAL_GOOD_FAITH_YEARS = 1
BACK_RENTAL_BAD_FAITH_MAX_YEARS = 5

# --- clearance ---------------------------------------------------------------
CLEARANCE_INCHES = 12

# --- attacher default --------------------------------------------------------
DEFAULT_CREDIT_LIMIT_CENTS = 5000000

# --- enums -------------------------------------------------------------------
OWNER_CATEGORIES = {"ELECTRIC_UTILITY", "ILEC", "MUNICIPAL"}
PURPOSES = {"FIBER", "COAX", "POWER_SUPPLY", "WIRELESS"}
COMPLEXITY_CLASSES = {"SIMPLE", "COMPLEX"}
INVOICE_TYPES = {"MAKE_READY", "ANNUAL_RENTAL", "UNAUTHORIZED"}

# --- logical clock default ---------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
