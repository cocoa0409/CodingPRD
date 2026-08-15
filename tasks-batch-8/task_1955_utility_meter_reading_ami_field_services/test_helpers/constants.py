"""Domain thresholds and numeric constants named in the PRD."""

# Logical clock startup default (PRD section 2.4)
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# Hazard flag time-to-live in days (PRD sections 2.10, 3.5)
HAZARD_TTL_DAYS = 30

# AMI comms degradation thresholds (PRD section 3.9 step 2)
AMI_MISS_THRESHOLD = 3
ENDPOINT_FAILURE_DAYS = 14

# Estimate eligibility (PRD section 3.4)
MAX_CONSECUTIVE_ESTIMATES = 3
MIN_TRAILING_VALIDATED_READS = 2
TRAILING_HISTORY_DAYS = 365

# No-read escalation scoring (PRD section 3.9 step 3)
ESC_BASE = 10
ESC_STREAK_W = 25
ESC_WINDOW_W = 5
ESC_URGENCY_DAYS = 7
ESC_HAZARD_BONUS = 15
ESC_DISPATCH_THRESHOLD = 40
ESC_SCORE_CAP = 100

# Theft back-bill (PRD section 3.6)
RATE_CENTS_PER_KWH = 11.25
PENALTY_PCT = 0.25

# SLA evaluation (PRD section 3.9 finalization): breach iff
# covered * SLA_TARGET_DEN < eligible * SLA_TARGET_NUM (98.50% standard)
SLA_TARGET_NUM = 197
SLA_TARGET_DEN = 200

# Backlog aging (PRD section 3.9 step 4)
BACKLOG_AGED_DAYS = 7

# Pagination defaults (PRD section 2.3)
PAGE_DEFAULT_LIMIT = 10
PAGE_MAX_LIMIT = 100

# A well-formed UUID that no test ever registers (path-existence probes)
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
