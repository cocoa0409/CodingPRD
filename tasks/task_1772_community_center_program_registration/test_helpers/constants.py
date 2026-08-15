"""Domain thresholds and shared instants (PRD §2.5, §2.9, §3.6-§3.9)."""

# --- Numeric thresholds pinned by the PRD ---
REFUND_REVIEW_THRESHOLD_CENTS = 10000   # PRD §3.7: one hundred dollars
ROOM_TURNOVER_BUFFER_MINUTES = 15       # PRD §2.9: fixed room turnover buffer
NO_SHOW_ABSENCE_THRESHOLD = 3           # PRD §3.9: consecutive unexcused absences
ATTENDANCE_QUALIFYING_PCT = 50          # PRD §3.9: ATTENDANCE_BASIS qualifying mark
ENROLLED_PAYMENT_WINDOW_HOURS = 72      # PRD §3.6: creation payment deadline
PROMOTED_PAYMENT_WINDOW_HOURS = 48      # PRD §3.8: promotion payment deadline
SCHOLARSHIP_PCT_OPTIONS = (25, 50, 75, 100)  # PRD §3.5

# --- Shared logical-clock instants used across setups ---
SEASON_START = "2026-09-01T00:00:00Z"
SEASON_END = "2026-12-15T00:00:00Z"
RESIDENT_OPENS = "2026-08-10T00:00:00Z"
GENERAL_OPENS = "2026-08-17T00:00:00Z"
REGISTRATION_CLOSES = "2026-09-15T00:00:00Z"
GENERAL_WINDOW_CLOCK = "2026-08-17T00:00:00Z"
ENROLLMENT_CHECK_AT = "2026-09-08T00:00:00Z"

# Default single meeting (a Saturday evening, after the enrollment check)
MEETING_START = "2026-09-20T18:00:00Z"
MEETING_END = "2026-09-20T19:00:00Z"

# Four-meeting block used by settlement and refund-tier setups
MEETING_TIMES_4 = (
    ("2026-09-20T18:00:00Z", "2026-09-20T19:00:00Z"),
    ("2026-09-27T18:00:00Z", "2026-09-27T19:00:00Z"),
    ("2026-10-04T18:00:00Z", "2026-10-04T19:00:00Z"),
    ("2026-10-11T18:00:00Z", "2026-10-11T19:00:00Z"),
)
AFTER_ALL_MEETINGS = "2026-10-12T00:00:00Z"

ADULT_BIRTH_DATE = "1990-01-01T00:00:00Z"   # age 36 at SEASON_START
MINOR_BIRTH_DATE = "2015-01-01T00:00:00Z"   # age 11 at SEASON_START
