"""Domain thresholds and shared fixtures values — numeric constants from the PRD.

Sources: PRD §2.7 (logical clock default), §3.1 (program defaults), §3.3
(ranking tiers and cap), §3.5 (certification freshness, lifespan), §3.6
(advance cap and expenditure clock), §3.7 (default sampling modulus),
§3.8 (recoupment due window, extension bound).
"""

# Logical clock startup value (PRD §2.7).
DEFAULT_CLOCK_START = "2026-08-01T00:00:00Z"

# Program defaults (PRD §3.1).
DEFAULT_SPOT_CHECK_MODULUS = 5
DEFAULT_ADVANCE_CAP_PCT = 0.5

# Ranking score tiers (PRD §3.3).
TIER_HIGH_BASE = 60
TIER_HIGH_BONUS = 10
TIER_MID_BASE = 40
TIER_MID_BONUS = 5
SCORE_CAP = 100

# Temporal constants (PRD §3.5, §3.6, §3.8).
ADVANCE_EXPENDITURE_DAYS = 90
ADVANCE_ESCALATION_DAYS = 30
CERTIFICATION_FRESHNESS_DAYS = 365
EXTENSION_MAX_DAYS = 365
RECOUPMENT_DUE_DAYS = 30
DAYS_PER_LIFESPAN_YEAR = 365

# Conventional window used across tests (inclusive at both ends, PRD §3.1).
DEFAULT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-09-01T00:00:00Z"

# Conventional implementation deadline for practice items under test.
DEFAULT_ITEM_DEADLINE = "2027-03-01T00:00:00Z"

# Conventional money/rate values used by the setups.
TEST_DEFAULTS = {
    "POOL_GENERAL_ALLOCATED": 1_000_000,
    "POOL_HU_ALLOCATED": 500_000,
    "FENCE_STANDARD_RATE": 300,
    "FENCE_HU_RATE": 360,
    "FENCE_LIFESPAN_YEARS": 10,
    "COVER_CROP_STANDARD_RATE": 15_000,
    "COVER_CROP_HU_RATE": 18_000,
    "COVER_CROP_LIFESPAN_YEARS": 5,
}

# Fixed operator identities used across workflows (opaque staff identifiers,
# PRD §2.1). Distinct users keep the segregation-of-duties boundaries clean.
ADMIN_USER = "admin-1"
PLANNER_USER = "planner-1"
PLANNER_USER_2 = "planner-2"
PAYMENT_OFFICER_USER = "po-1"
QA_USER = "qa-1"
QA_USER_2 = "qa-2"
