"""Domain thresholds for the Driving School API (PRD §3 numeric constants)."""

# GPS validation threshold (PRD §2.6, §3.5): inclusive at 5.00 km
MIN_DRIVING_KM = 5.0

# Late-cancellation tier cliffs (PRD §3.4): strict less-than
LATE_CANCEL_TIER_2H_PCT = 100   # delta_hours < 2 → 100%
LATE_CANCEL_TIER_24H_PCT = 50   # 2 <= delta_hours < 24 → 50%
LATE_CANCEL_TIER_72H_PCT = 0    # delta_hours >= 24 → 0%

# Vehicle calendar buffer (PRD §3.3): 15 minutes between bookings
VEHICLE_BUFFER_MINUTES = 15

# Instructor safety caps (PRD §3.3)
INSTRUCTOR_DAILY_LIMIT_MINUTES = 480     # 8h
INSTRUCTOR_WEEKLY_LIMIT_MINUTES = 2400   # 40h
INSTRUCTOR_REST_DAYS_PER_WEEK = 1

# No-show grace period (PRD §3.4)
NO_SHOW_GRACE_MINUTES = 15
NO_SHOW_THRESHOLD_PER_CYCLE = 3

# Reschedule cap (PRD §3.4)
RESCHEDULE_LIMIT_PER_CYCLE = 3

# Exam retake cap (PRD §3.5)
RETAKE_LIMIT = 3

# Cycle length (PRD §3.4)
CYCLE_DAYS = 30

# Stage minimum hours (PRD §3.5)
MIN_BASIC_MINUTES = 600
MIN_HIGHWAY_MINUTES = 480
MIN_THEORY_MINUTES = 0

# Exam passing scores (PRD §3.5)
PASSING_SCORE_THEORY = 90
PASSING_SCORE_BASIC = 80
PASSING_SCORE_FINAL = 85

# Complaint escalation cap (PRD §3.7)
ESCALATION_LIMIT = 3

# Default test fixtures (sensible test fixture sizing)
DEFAULT_PACKAGE = {
    "name": "Standard Package",
    "total_minutes": 2000,
    "total_price_cents": 200_000,
    "included_simulator_sessions": 10,
    "included_exam_attempts": 6,
    "per_minute_overage_price_cents": 200,
    "per_simulator_session_overage_price_cents": 15_000,
}
