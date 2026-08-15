"""Domain thresholds — numeric constants stated in the PRD (§3)."""

# Pump alternation: candidate must exceed lead runtime by this many hours (§3.5).
ALTERNATION_THRESHOLD_HOURS = 24.0

# Generator-test minimum durations (§3.7).
LOAD_BANK_MIN_DURATION_MINUTES = 30
OTHER_TEST_MIN_DURATION_MINUTES = 15

# Confined-space permit validity window in hours (§3.9).
PERMIT_VALIDITY_HOURS = 12

# SSO regulator deadlines in hours (§3.8).
STANDARD_DEADLINE_HOURS = 24
SURFACE_WATER_DEADLINE_HOURS = 12
SURFACE_WATER_MULTIPLIER = 1.20

# Capital risk score components (§3.10).
RISK_RECENCY_BONUS = 15
RISK_RESILIENCE_BONUS = 10
RISK_AGE_SCORE_CAP = 25
RISK_SCORE_CAP = 100.0

# Capital plan cooling period before lock (§3.10).
PLAN_SETTLE_DAYS = 7

# Grease-management action threshold in inches (§3.6).
TARGET_DEPTH_INCHES = 6.0

# Overdue derivation: SCHEDULED rows more than this many hours past
# scheduled_for flip to OVERDUE on tick (§3.6, §3.7).
OVERDUE_AFTER_HOURS = 24

# Callout selection scores (§3.3).
CALLOUT_ZONE_MATCH_SCORE = 100
CALLOUT_LOAD_PENALTY_PER_TICKET = 50
CALLOUT_FAIRNESS_PENALTY_PER_CALL = 10
MAX_ACTIVE_TICKETS_PER_OPERATOR = 3

# Default logical clock before any explicit set (§2.9).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
