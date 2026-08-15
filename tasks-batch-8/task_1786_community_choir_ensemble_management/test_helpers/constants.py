"""Domain thresholds and shared literals from PRD calculation rules."""

# Audition scoring (PRD §3.2)
TONE_WEIGHT = 0.40
PITCH_WEIGHT = 0.35
SIGHT_WEIGHT = 0.25
ACCEPT_SCORE_THRESHOLD = 7.0

# Attendance weighting (PRD §3.3)
LATE_WEIGHT = 0.5
EXCUSED_WEIGHT = 0.75
UNEXCUSED_WEIGHT = 0.0
DEFAULT_ATTENDANCE_THRESHOLD = 0.75

# Season policy defaults (PRD §3.1)
DEFAULT_AUDITION_SLOT_MINUTES = 30

# Library fine accrual (PRD §3.5)
OVERDUE_WEEKLY_FINE_CENTS = 200

# Program buffer at LOCK_PROGRAM (PRD §3.6)
PROGRAM_BUFFER_SECONDS = 900

# Booking lead time (PRD §3.6)
BOOKING_LEAD_TIME_HOURS = 72

# Recognition tiers (PRD §3.9)
SILVER_MIN_CENTS = 10000
GOLD_MIN_CENTS = 50000

# Tour refund schedule boundaries in days (PRD §3.8)
FULL_REFUND_DAYS = 60
HALF_REFUND_DAYS = 30

# Guest contract cancellation fee fraction after acceptance (PRD §3.7)
CANCELLATION_FEE_FRACTION = 0.20

# Standard season configuration reused across scenarios. With the logical
# clock at its startup default of 2026-08-01T00:00:00Z, an invoice issued at
# startup keeps the early-bird discount: round_half_up(20000 * 0.9) = 18000.
STANDARD_SEASON_PAYLOAD = {
    "name": "Fall",
    "base_dues_cents": 20000,
    "early_bird_pct": 0.10,
    "early_bird_cutoff": "2026-08-15T00:00:00Z",
    "dues_due_date": "2026-09-01T00:00:00Z",
    "late_fee_weekly_cents": 500,
    "late_fee_cap_cents": 2000,
    "scholarship_pool_cents": 50000,
}

STANDARD_DISCOUNTED_DUES_CENTS = 18000
STANDARD_BASE_DUES_CENTS = 20000
STANDARD_SCHOLARSHIP_POOL_CENTS = 50000

CLOCK_START = "2026-08-01T00:00:00Z"
