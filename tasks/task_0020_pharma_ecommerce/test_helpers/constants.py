"""Domain thresholds — numeric constants from PRD calculations and rules."""

# --- Cold chain (PRD §3.7) ---
COLD_RANGE_LOW_TENTHS = 20         # 2.0 °C inclusive lower bound of safe band
COLD_RANGE_HIGH_TENTHS = 80        # 8.0 °C inclusive upper bound of safe band
CRITICAL_LOW_TENTHS = 0            # < 0.0 °C is critical
CRITICAL_HIGH_TENTHS = 150         # > 15.0 °C is critical
MILD_SEVERITY = 1
CRITICAL_SEVERITY = 5
SAFE_SEVERITY = 0
COLD_CHAIN_DISPOSE_THRESHOLD = 30  # PRD §3.7: dispose iff excursion_score > 30

# --- Pharmacist review (PRD §3.6) ---
MAX_REVISIONS = 2
REVIEW_NOTES_MIN_LENGTH = 10

# --- ADR (PRD §3.8) ---
SERIOUS_DEADLINE_HOURS = 24
NON_SERIOUS_DEADLINE_DAYS = 15
GRACE_HOURS = 0
FOLLOW_UP_DAYS = 7

# --- Vendor qualification (PRD §3.1) ---
ALERT_DAYS = 30
GREEN_MULTIPLIER = 1.0
YELLOW_MULTIPLIER = 1.5
RED_MULTIPLIER = 2.0

# --- Pagination (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Defaults used by factories ---
DEFAULT_PLATFORM_NAME = "Acme Pharma Platform"
DEFAULT_JURISDICTION = "CN"
DEFAULT_REGULATORY_ENDPOINT = "https://regulatory.example/mock"

# Far-future timestamp safe for license/permit/certificate expiries that
# tests do NOT want to interact with the clock.
FAR_FUTURE_ISO = "2099-01-01T00:00:00.000Z"

# Baseline clock used by conftest's autouse reset; well before FAR_FUTURE_ISO.
CLOCK_BASELINE_ISO = "2025-01-01T00:00:00.000Z"
