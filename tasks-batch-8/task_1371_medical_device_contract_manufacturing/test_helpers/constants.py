"""Domain thresholds and shared constants from the PRD's calculation rules."""

# Logical clock startup value (PRD section 2.5).
CLOCK_START = "2026-08-01T00:00:00Z"

# Lot expiry ladder (PRD section 3.2).
PROVISIONAL_RATIO = 0.5
PROVISIONAL_CAP_MONTHS = 12
FINAL_CAP_MONTHS = 60

# Supplier scoring (PRD section 2.9).
SEVERITY_PENALTY = {"MINOR": 5, "MAJOR": 15, "CRITICAL": 30}
AUDIT_FINDING_PENALTY = 2
AUDIT_MAJOR_FINDING_PENALTY = 8
AUTO_SUSPEND_BELOW = 50
TIER_LOW_MIN = 90
TIER_MEDIUM_MIN = 70

# Audit cadence in months (PRD section 2.9).
INTERVAL_LOW_MONTHS = 24
INTERVAL_MEDIUM_MONTHS = 12
INTERVAL_HIGH_MONTHS = 6
INITIAL_INTERVAL_MONTHS = 12

# Sterility sampling (PRD section 3.6).
MATURITY_MIN_LOTS = 3
CRITICAL_MULTIPLIER = 1.5

# Complaint-rate review flag (PRD section 3.7).
FLAG_THRESHOLD = 5.0

# Revalidation cadence (PRD section 3.3).
REVALIDATION_MONTHS = 36

# UDI-DI length (PRD section 3.6).
UDI_DI_LENGTH = 14

# Sample UDI-DI strings used across tests. "12345678901231" satisfies the GS1
# mod-10 check digit over the first thirteen digits; "...32" does not.
UDI_VALID = "12345678901231"
UDI_VALID_ALT = "09876543210982"
UDI_BAD_CHECK_DIGIT = "12345678901232"

# Common time values (logical clock starts at CLOCK_START).
MFG_DEFAULT = "2026-08-02T00:00:00Z"
AGREEMENT_FROM = "2026-07-01T00:00:00Z"
AGREEMENT_TO = "2027-07-01T00:00:00Z"
PROTOCOL_WINDOW_START = "2026-09-01T00:00:00Z"
PROTOCOL_WINDOW_END = "2026-09-10T00:00:00Z"

# A well-formed UUID that never matches a persisted resource.
UNKNOWN_UUID = "11111111-2222-3333-4444-555555555555"
