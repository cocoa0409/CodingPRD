"""Domain thresholds and numeric constants for the AMC API (PRD §3).

Generic NON_EXISTENT_UUID comes from the framework. These mirror the fixed
constants stated in the PRD's calculation and validation prose.
"""

# Fee split (PRD §2.7, §3.6).
RUSH_PREMIUM_PCT = 0.10          # rush premium fraction
REVISION_PENALTY_PCT = 0.05      # per-round revision penalty fraction
APPRAISER_FLOOR_CENTS = 5000     # appraiser share floor

# Panel score (PRD §3.8).
W_COMPLETION = 0.4
W_ON_TIME = 0.3
W_LOAD = 0.3
MAX_ACTIVE_LOAD = 5              # maximum concurrent active assignments

# Turnaround SLA (PRD §3.9).
SLA_BASE_HOURS = {
    "URAR_1004": 120,
    "CONDO_1073": 96,
    "EXTERIOR_2055": 72,
}
RUSH_SHORTEN_HOURS = 48

# Reconsideration of value (PRD §3.7).
ROV_DELTA_THRESHOLD_PCT = 10.0

# Compliance (PRD §3.5).
USPAP_MIN_COMPARABLES = 3

# Inspection windows (PRD §3.3).
TRAVEL_BUFFER_MINUTES = 60

# Convenient defaults used by factories and fixtures.
TEST_DEFAULTS = {
    "ORDER_FEE_CENTS": 50000,
    "LENDER_BUDGET_CENTS": 1_000_000,
    "BASE_FEE_SHARE_PCT": 0.50,
    "OPINION_OF_VALUE_CENTS": 500000,
}
