"""Domain thresholds and canonical values from PRD calculation rules."""

# Logical clock startup default (PRD §2.5)
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical six-hour event window used across scenarios
EVENT_START = "2026-08-20T09:00:00Z"
EVENT_END = "2026-08-20T15:00:00Z"
EVENT_SCHEDULED_HOURS = 6.0

THRESHOLDS = {
    # Supervision ratios (PRD §3.3)
    "ADULT_RATIO": 8,
    "MINOR_RATIO": 4,
    # Procurement tax (PRD §3.5)
    "TAX_RATE": 0.0875,
    # Meal vendor daily capacity (PRD §3.6)
    "VENDOR_DAILY_CAPACITY": 6,
    # Vehicle turnaround buffer (PRD §3.6)
    "TURNAROUND_BUFFER_MINUTES": 30,
    # Net-cost offset cap (PRD §3.8)
    "OFFSET_CAP_PCT": 0.50,
    # Repeat-booking cap uplift (PRD §3.8)
    "REPEAT_CAP_UPLIFT_PCT": 0.10,
    # Reputation bands (PRD §3.9)
    "RECENCY_WINDOW_DAYS": 90,
    "SUSPEND_RATING_THRESHOLD": 2.50,
    "REINSTATE_RATING_THRESHOLD": 3.00,
    "SUSPEND_MIN_SURVEYS": 3,
    # Repeat booking (PRD §3.2)
    "REPEAT_RATING_THRESHOLD": 4.0,
    "REPEAT_WINDOW_DAYS": 180,
    # Temporal windows
    "EVENT_START_LEAD_HOURS": 24,
    "MEAL_ORDER_LEAD_HOURS": 72,
}

# Date-of-birth fixtures: adult (36 at event) and minor (15 at event)
ADULT_DOB = "1990-01-01"
MINOR_DOB = "2011-05-01"
LEAD_DOB = "1985-03-03"

# Standard procurement lines whose per-line rounding is pinned:
# round_half_up(3 x 999 x 1.0875) = 3259; round_half_up(7 x 149 x 1.0875) = 1134
PINNED_LINES = [
    {"item_name": "Lumber", "quantity": 3, "unit_cost_cents": 999},
    {"item_name": "Screws", "quantity": 7, "unit_cost_cents": 149},
]
PINNED_LINES_TOTAL_CENTS = 4393  # 3259 + 1134 (per-line rounding, not sum-then-round 4394)

# Simple lines: round_half_up(2 x 500 x 1.0875) = 1088
GLOVES_LINES = [{"item_name": "Gloves", "quantity": 2, "unit_cost_cents": 500}]
GLOVES_TOTAL_CENTS = 1088
