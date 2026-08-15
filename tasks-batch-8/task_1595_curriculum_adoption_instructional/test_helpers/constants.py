"""Domain thresholds and numeric constants from the PRD.

Every value below is stated verbatim in the PRD's workflow sections.
"""

# Logical clock (PRD: before any clock call the clock reads exactly this).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
# Clock position used to close a public review window opened at the default
# clock (window is 30 days, so it closes at 2026-08-31; the day after is safe).
BOARD_DECISION_CLOCK = "2026-09-01T00:00:00Z"

# Alignment gate (PRD: every VETTED material must show coverage_pct of at
# least 85.00, boundary inclusive).
COVERAGE_THRESHOLD_PCT = 85.00
RATING_WEIGHTS = {"FULL": 1.0, "PARTIAL": 0.5, "NONE": 0.0}

# Review rubric weights (PRD: 0.4 pedagogy + 0.3 alignment + 0.2 usability
# + 0.1 equity, exact decimal arithmetic).
W_PEDAGOGY = 0.4
W_ALIGNMENT = 0.3
W_USABILITY = 0.2
W_EQUITY = 0.1

# Official composite trims one lowest + one highest once the pool holds at
# least this many reviews (PRD: "at least five reviews").
TRIM_MIN_REVIEWS = 5

# Board decision quality gates (PRD: official_composite at least 3.20 with
# exactly 3.20 passing; participation_rate at least 0.60 with exactly 0.60
# passing).
COMPOSITE_THRESHOLD = 3.20
PARTICIPATION_FLOOR = 0.60

# Bid rule (PRD: at least three responsive quotes when the target's
# evaluated_total is at least 250,000.00; at least two otherwise).
BID_FORMAL_THRESHOLD = 250000.00
BID_FORMAL_POOL_SIZE = 3
BID_INFORMAL_POOL_SIZE = 2

# Best-value weights (PRD: half price + quarter training + quarter license;
# training 10 points per session capped at 100; license 20 points per year
# capped at 100).
BV_W_PRICE = 0.50
BV_W_TRAINING = 0.25
BV_W_LICENSE = 0.25
BV_TRAINING_POINTS_PER_SESSION = 10
BV_LICENSE_POINTS_PER_YEAR = 20

# Committee quorum (PRD: at least three votes in the current vote_round).
QUORUM_VOTES = 3

# Temporal windows in days (PRD: public review 30 days; same-subject clear
# gap 30 days; challenge window 90 days; appeal window 14 days).
PUBLIC_REVIEW_DAYS = 30
PUBLIC_REVIEW_GAP_DAYS = 30
CHALLENGE_WINDOW_DAYS = 90
APPEAL_WINDOW_DAYS = 14

# Budget forecast constants (PRD §3.10 equivalent prose: per-pupil 120.00,
# replacement ratio 0.20, five-year horizon, three percent inflation).
PER_PUPIL_RATE = 120.00
REPLACEMENT_RATIO = 0.20
FORECAST_YEARS = 5
INFLATION_FACTOR = 0.03
FORECAST_HISTORY_CYCLES = 3
# Contingency tiers keyed on the rounded base_amount.
TIER_1_CAP = 100000.00
TIER_2_CAP = 500000.00
TIER_1_RATE = 0.05
TIER_2_RATE = 0.08
TIER_3_RATE = 0.12

# Distribution need_priority bounds (PRD: 1 to 5, 5 most urgent).
NEED_PRIORITY_MIN = 1
NEED_PRIORITY_MAX = 5
