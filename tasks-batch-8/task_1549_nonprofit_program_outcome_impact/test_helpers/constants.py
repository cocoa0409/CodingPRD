"""Domain thresholds and default timestamps used across the test suite.

All numeric thresholds and ISO 8601 instants below come from the PRD's
calculation rules (section 3) and the logical clock contract (section 2.5).
"""

# --- Logical clock defaults (PRD section 2.5) ---
STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- Attainment calculation (PRD section 3.2) ---
ATTAINMENT_CAP = 150
ATTAINMENT_FLOOR = 0
ATTAINMENT_BAND_GREEN_MIN = 90.00
ATTAINMENT_BAND_YELLOW_MIN = 70.00

# --- Data-quality score (PRD section 3.7) ---
DQ_WEIGHT_COMPLETENESS = 0.5
DQ_WEIGHT_VALIDATED = 0.3
DQ_WEIGHT_CONSENT = 0.2
DQ_FINDING_PENALTY = 4.00
DQ_CAP = 100
DQ_GATE_MIN = 80.00

# --- Default entity windows used by fixtures ---
DEFAULT_ENROLLMENT_START = "2026-08-01T00:00:00Z"
DEFAULT_ENROLLMENT_END = "2026-08-31T23:59:59Z"
DEFAULT_CYCLE_START = "2026-09-01T00:00:00Z"
DEFAULT_CYCLE_END = "2026-09-30T23:59:59Z"
DEFAULT_REPORTING_DUE = "2026-10-15T00:00:00Z"
DEFAULT_CONSENT_EXPIRY = "2027-01-01T00:00:00Z"
DEFAULT_CERTIFICATION_EXPIRY = "2027-01-01T00:00:00Z"

# --- Canonical actor ids (opaque identifiers, PRD section 2.1) ---
DIRECTOR_USER = "dir-1"
LEAD_USER = "lead-1"
COLLECTOR_USER = "collector-1"
STEWARD_USER = "steward-1"
STEWARD_OTHER_USER = "steward-other"
PRIVACY_USER = "privacy-1"
