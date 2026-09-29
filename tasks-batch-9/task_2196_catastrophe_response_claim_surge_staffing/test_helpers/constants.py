"""Domain thresholds and numeric constants named by the PRD's calculation rules."""

# The logical clock reads exactly this instant on startup.
CLOCK_START_UTC = "2026-08-01T00:00:00.000Z"

# Event posture strain banding.
POSTURE = {
    "RESTRICTED_STRAIN_THRESHOLD": 3,
    "FROZEN_STRAIN_THRESHOLD": 8,
    "STALE_SNAPSHOT_STRAIN": 3,
    "MORATORIUM_STRAIN": 4,
}

# Claim severity score.
PERIL_WEIGHT = {
    "HURRICANE": 1.15,
    "WILDFIRE": 1.25,
    "FLOOD": 1.20,
    "HAIL": 0.95,
    "WINTER_STORM": 0.90,
    "EARTHQUAKE": 1.30,
}
ACCESS_ADJUSTMENT = {"ACCESSIBLE": 0.0, "RESTRICTED": 6.0, "INACCESSIBLE": 12.0}
ALE_BONUS = 10.0
SEVERITY_INDEX_WEIGHT = 20.0
TIER_FLOORS = {"CAT_SEVERE": 75.0, "COMPLEX": 50.0, "STANDARD": 25.0}

# Advance payment cap: each coverage line is rounded to cents first, then summed.
LINE_ADVANCE_PCT = {"DWELLING": 0.30, "CONTENTS": 0.25, "ALE": 0.50, "OTHER_STRUCTURES": 0.20}
ADVANCE_TIER_MULTIPLIER = {"CAT_SEVERE": 1.00, "COMPLEX": 0.85, "STANDARD": 0.60, "FAST_TRACK": 0.40}

# Initial case reserve: raw line values summed, rounded once at the end.
TIER_RESERVE_FACTOR = {"CAT_SEVERE": 0.85, "COMPLEX": 0.65, "STANDARD": 0.45, "FAST_TRACK": 0.25}

# Deployment cost.
INDEPENDENT_RATE_FACTOR = 1.35
STAFF_RATE_FACTOR = 1.0
PREMIUM_MID_FLOOR = 5000.00
PREMIUM_HIGH_FLOOR = 20000.00
PREMIUM_MID_RATE = 0.06
PREMIUM_HIGH_RATE = 0.11

# Loss estimate.
PERIL_DEV_FACTOR = {
    "HURRICANE": 1.40,
    "WILDFIRE": 1.55,
    "FLOOD": 1.65,
    "HAIL": 1.20,
    "WINTER_STORM": 1.10,
    "EARTHQUAKE": 1.80,
}
REPORT_RATE = 0.35

# Adjuster surge capacity score.
CREDENTIAL_PENALTY = {"VALID": 0.0, "EXPIRING": 15.0, "WAIVED": 8.0, "EXPIRED": 100.0}
FATIGUE_STEP = 3.0
FATIGUE_CAP = 30.0
CERT_BONUS = 5.0

# Inspection mode resolution.
DESK_LOSS_CEILING = 10000.00

# Acknowledgement deadline.
BASE_ACK_DAYS = 15

# Deployment rest separation. Inspection windows carry no buffer at all.
REST_BUFFER_HOURS = 12

# Numeric input ranges named by the PRD's schema-validation rule.
RANGES = {
    "rooms_total": (0, 400),
    "max_open_claims": (1, 60),
    "expected_severity_index": (0.0, 1.0),
    "mandated_advance_pct": (0.0, 1.0),
    "deadline_extension_days": (0, 365),
    "coverage_lines_entries": (1, 6),
    "performance_score": (0, 100),
    "rooms_reserved": (0, 4),
    "max_concurrent_jobs": (1, 200),
    "limit": (1, 100),
    "cat_code_chars": (3, 24),
}

# Pagination defaults.
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MAX_LIMIT = 100
MIN_LIMIT = 1

# Claim reopen ceiling.
MAX_REOPENS = 2
