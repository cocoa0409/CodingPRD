"""Domain thresholds and fixed values from the PRD's calculation rules (§3.3, §3.7, §3.8)."""

# Logical clock startup default (PRD §2.4).
CLOCK_START = "2026-08-01T00:00:00Z"

# Identity resolution weighted legs (PRD §3.3).
IDENTITY_WEIGHTS = {"NPI": 50, "TIN": 30, "LOCATION": 20}
MATCH_THRESHOLD = 70
EXACT_SCORE = 100

# Quality score component bounds and per-unit points (PRD §3.7).
QUALITY = {
    "MAX_COMPLETENESS": 40,
    "MAX_FRESHNESS": 30,
    "MAX_CONFLICT": 20,
    "MAX_ATTESTATION": 10,
    "POINTS_PER_FRESH_GROUP": 6,
    "POINTS_PER_OPEN_CONFLICT": 5,
    "POINTS_PER_UNATTESTED": 5,
    "REQUIRED_KEY_COUNT": 10,
}

# Deterministic score of a freshly created provider with no attributes, no
# conflicts, and no attestation history: 0 + 0 + 20 + 10 = 30 (PRD §3.7).
FRESH_PROVIDER_SCORE = {
    "completeness_component": 0,
    "freshness_component": 0,
    "conflict_component": 20,
    "attestation_component": 10,
    "total_score": 30,
}

# Consecutive-expiry count that suspends a provider (PRD §3.8, inclusive).
SUSPEND_THRESHOLD_CONSECUTIVE_EXPIRIES = 2

# Pagination envelope defaults (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# Opaque operator identifiers used by segregation-of-duties scenarios (PRD §2.8).
INTAKE_USER_1 = "op_intake_1"
INTAKE_USER_2 = "op_intake_2"
STEWARD_USER_1 = "steward_1"
DIST_USER_1 = "dist_op_1"
CONTACT_USER_1 = "contact_1"
