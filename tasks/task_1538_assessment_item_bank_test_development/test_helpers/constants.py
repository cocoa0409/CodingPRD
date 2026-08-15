"""Domain thresholds and shared constants from the PRD."""

# Program logical clock (PRD system-wide section on the program clock)
CLOCK_INIT = "2026-08-01T00:00:00Z"

# Standard field-test window bounds used by fixtures. The clock is advanced
# ADVANCE_INTO_WINDOW seconds to sit inside the window, then
# ADVANCE_PAST_WINDOW further seconds to pass end_utc for closing.
WINDOW_START = "2026-08-05T00:00:00Z"
WINDOW_END = "2026-08-10T23:59:59Z"
ADVANCE_INTO_WINDOW = 432000        # 5 days -> 2026-08-06T00:00:00Z
ADVANCE_PAST_WINDOW = 500000        # -> 2026-08-11T18:53:20Z (> WINDOW_END)

# Review sessions are scheduled at the clock's initial value so they can be
# opened immediately (the clock has "reached" scheduled_at).
SESSION_SCHEDULED_AT = "2026-08-01T00:00:00Z"

# Statistical thresholds (PRD field-testing section)
TARGET_SAMPLE_SIZE = 50             # minimum allowed target_sample_size
MIN_DURATION_SECONDS = 30           # FINAL-set minimum attempt duration
P_LOW = 0.30
P_HIGH = 0.85
PB_MIN = 0.20
PB_SEVERE = 0.10
STATS_DECIMALS = 4                  # p_value / point_biserial rounding
EQUATING_DECIMALS = 6               # scaling coefficient rounding

# Item defaults
DEFAULT_EXPOSURE_CAP = 3
MAX_SCORE_POINTS = 1

# Review rules
RATIONALE_MIN_CHARS = 20
AGENDA_MAX_ITEMS = 25
QUORUM_SIZE = 2

# Dossier rules
DOSSIER_MIN_CHARS = 200

# Form archival gate: strictly more than 90 days past intended_admin_date.
ARCHIVE_GRACE_DAYS = 90

# Default intended administration date for forms created in fixtures.
INTENDED_ADMIN_DATE = "2026-09-01T00:00:00Z"

# Grant validity interval wide enough to cover any clock position in tests.
GRANT_VALID_FROM = "2026-01-01T00:00:00Z"
GRANT_VALID_UNTIL = "2027-12-31T23:59:59Z"
