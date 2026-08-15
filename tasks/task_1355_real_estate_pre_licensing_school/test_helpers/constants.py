"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock default at server startup (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

THRESHOLDS = {
    # Seat-time daily credit cap (PRD §3.6).
    "DAILY_CREDIT_CAP_MINUTES": 480,
    # Attendance minutes range 1..1440 (PRD §3.6).
    "ATTENDANCE_MINUTES_MIN": 1,
    "ATTENDANCE_MINUTES_MAX": 1440,
    # Refund schedule tiers in basis points (PRD §3.9).
    "REFUND_TIER_1_BPS": 1000,
    "REFUND_TIER_2_BPS": 2500,
    "REFUND_TIER_3_BPS": 5000,
    # Administrative fees (PRD §3.9).
    "ADMIN_FEE_CENTS": 5000,
    "STATUTORY_ADMIN_FEE_CENTS": 1000,
    # Registration fee tiers keyed on discounted tuition (PRD §3.5).
    "REGISTRATION_FEE_HIGH_CENTS": 2500,
    "REGISTRATION_FEE_LOW_CENTS": 1500,
    "FEE_TIER_THRESHOLD_CENTS": 100000,
    # Pass-rate surveillance (PRD §3.1).
    "PASS_RATE_WINDOW_DAYS": 90,
    "PASS_RATE_MIN_ATTEMPTS": 10,
    "DEFAULT_PASS_RATE_THRESHOLD_BPS": 6000,
    # Credit-report late fee (PRD §3.8).
    "LATE_FEE_BASE_CENTS": 5000,
    "LATE_FEE_PER_DAY_CENTS": 1000,
    "LATE_FEE_CAP_CENTS": 50000,
    "REPORTING_DEADLINE_DAYS": 30,
    # Approval aging and late-renewal window (PRD §3.2).
    "EXPIRING_RUNWAY_DAYS": 30,
    "LATE_RENEWAL_WINDOW_DAYS": 30,
    # No-show grace (PRD §3.7).
    "NO_SHOW_GRACE_HOURS": 24,
    # Default max exam attempts (PRD §3.2).
    "DEFAULT_MAX_EXAM_ATTEMPTS": 2,
}

TEST_DEFAULTS = {
    "SCHOOL_NAME": "Lone Star Realty School",
    "SCHOOL_CODE": "LSRS",
    "HOME_STATE": "TX",
    "OTHER_STATE": "NM",
    "COURSE_CODE": "PRE-101",
    "COURSE_TITLE": "TX Pre-Licensing",
    "REQUIRED_SEAT_MINUTES": 3000,
    "TUITION_CENTS": 50000,
    "PASS_SCORE_PCT": 70,
    "COMPLETION_DEADLINE_DAYS": 30,
    # Tuition 50000 with no scholarship -> discounted 50000 < 100000 -> fee 1500.
    "CHARGE_TOTAL_CENTS": 51500,
    "OFFERING_START": "2026-09-01",
    "OFFERING_END": "2026-09-10",
    "APPROVAL_VALID_FROM": "2026-08-01",
    "APPROVAL_VALID_UNTIL": "2027-07-31",
    "EXAM_SCHEDULED_AT": "2026-09-11T14:00:00Z",
}

# Placeholder UUID for not-found probes (never references a real resource).
BADID = "00000000-0000-0000-0000-000000000000"
