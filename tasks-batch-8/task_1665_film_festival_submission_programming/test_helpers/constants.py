"""Domain thresholds and defaults — numeric constants from PRD §2.4, §3."""

# Logical clock (PRD §2.4: startup default reads exactly this instant)
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Standard edition calendar used across tests
EDITION_CALENDAR = {
    "intake_open_at": "2026-08-01T00:00:00Z",
    "early_deadline_at": "2026-08-15T00:00:00Z",
    "regular_deadline_at": "2026-09-01T00:00:00Z",
    "late_deadline_at": "2026-09-15T00:00:00Z",
    "festival_start_at": "2027-01-21T00:00:00Z",
    "festival_end_at": "2027-02-01T00:00:00Z",
}

# Fee discounts (PRD §3.2)
STUDENT_DISCOUNT_PCT = 0.25
MEMBER_DISCOUNT_PCT = 0.10

# Refunds (PRD §3.2)
FULL_REFUND_WINDOW_HOURS = 48
WITHDRAWAL_REFUND_PCT = 0.50

# Score weights (PRD §3.4)
WEIGHT_STAFF = 1.0
WEIGHT_SENIOR = 1.5
WEIGHT_LEAD = 2.0
SCREENER_COUNT_DEFAULT = 3

# Slate lock threshold (PRD §3.5)
SLATE_COMPOSITE_THRESHOLD = 7.5

# RSVP default (PRD §3.1)
RSVP_WINDOW_DAYS_DEFAULT = 7

# Travel stipend (PRD §3.7)
DOMESTIC_BASE_CENTS = 50000
INTERNATIONAL_BASE_CENTS = 150000
PER_EXTRA_DELEGATE_CENTS = 20000
MAX_DELEGATES_COVERED = 2
PER_FILM_CAP_CENTS = 200000
BOOKED_CANCEL_PENALTY_PCT = 0.25

# Scheduling (PRD §3.8)
QA_MINUTES = 15
TURNOVER_MINUTES_DEFAULT = 30

# Programmer default cap (PRD §3.1)
MAX_ACTIVE_ASSIGNMENTS_DEFAULT = 12

# Assignment due date used by default fixtures (safely after the default clock)
DEFAULT_ASSIGNMENT_DUE = "2026-11-01T00:00:00Z"
