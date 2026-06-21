"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Reliability scoring (PRD §3.5): raw = 100*ratio - NO_SHOW_PENALTY*N, clamped [0,100].
NO_SHOW_PENALTY = 8

# Recognition milestone tier breakpoints (PRD §3.6), inclusive lower bounds (>=).
MILESTONE_BRONZE_AT = 25
MILESTONE_SILVER_AT = 100
MILESTONE_GOLD_AT = 200
MILESTONE_PLATINUM_AT = 500

# Background-check expiry (PRD §3.2): valid_until = cleared_at + validity_days * 86400s.
SECONDS_PER_DAY = 86400

# Organization governance defaults (PRD §2.9 / §3.1).
DEFAULT_RELIABILITY_SUSPENSION_THRESHOLD = 40
DEFAULT_NO_SHOW_STRIKE_LIMIT = 3

# Field defaults (PRD §3.1 / §3.2 / §3.3).
DEFAULT_BG_VALIDITY_DAYS = 365
DEFAULT_TRAINING_VALID_DAYS = 730
DEFAULT_WAIVER_REVISION = 1

# Background-check tier ranks (PRD §3.2): NONE < BASIC < STANDARD < ENHANCED.
BG_TIER_RANK = {"NONE": 0, "BASIC": 1, "STANDARD": 2, "ENHANCED": 3}

# A clock instant comfortably before any test shift, used as the baseline now.
BASE_CLOCK = "2026-06-15T00:00:00Z"
