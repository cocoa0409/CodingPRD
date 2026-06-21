"""Domain thresholds and the standard rate card used across the suite.

The pricing values are the canonical rate card the test recipes assume; the
threshold constants come from the PRD's pricing rules (the deposit fraction and
the pumpkin breakpoint default). NON_EXISTENT_UUID comes from the framework.
"""

# Deposit fraction applied at group confirm (PRD §3.7: "the ceiling of
# quoted_total_cents multiplied by one quarter").
DEPOSIT_PCT = 0.25

# PRD §3.1 default pumpkin breakpoint and group-rate parameters.
DEFAULT_HEAVY_PUMPKIN_LB = 20
DEFAULT_GROUP_RATE_MIN_HEADCOUNT = 15
DEFAULT_GROUP_DISCOUNT_PCT = 0.20
DEFAULT_SCHOOL_DISCOUNT_PCT = 0.35

# PRD §3.1 default farm parameters.
DEFAULT_PARKING_FEE_CENTS = 1000
DEFAULT_WINDOW_BUFFER_MINUTES = 30

# Canonical rate card (cents) used by the standard pricing policy.
RATE_CARD = {
    "adult_admission_cents": 2000,
    "child_admission_cents": 1200,
    "hayride_pass_cents": 800,
    "maze_pass_cents": 600,
    "upick_pass_cents": 1000,
    "pumpkin_per_lb_cents": 150,
    "pumpkin_flat_each_cents": 2500,
    "season_pass_price_cents": 8000,
    "heavy_pumpkin_lb": 20,
    "group_rate_min_headcount": 15,
    "group_discount_pct": 0.20,
    "school_discount_pct": 0.35,
}

# Common test clock anchors.
CLOCK_BASE = "2026-10-10T12:00:00Z"
WINDOW_START = "2026-10-11T14:00:00Z"
WINDOW_END = "2026-10-11T16:00:00Z"
