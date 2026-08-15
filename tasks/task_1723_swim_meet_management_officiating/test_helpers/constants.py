"""Domain thresholds and shared defaults (PRD §2.4, §3.1)."""

# Meet configuration defaults (PRD §3.1: "The tuning knobs all carry defaults")
DEFAULT_LANE_COUNT = 6
DEFAULT_POINTS_TABLE = [9, 7, 6, 5, 4, 3, 2, 1]
DEFAULT_RELAY_POINTS_MULTIPLIER = 2
DEFAULT_MAX_INDIVIDUAL_ENTRIES_PER_SWIMMER = 4
DEFAULT_DQ_PROTEST_WINDOW_MINUTES = 30
DEFAULT_MIN_RECOVERY_MINUTES = 20
DEFAULT_TIMING_DELTA_THRESHOLD_CS = 30
DEFAULT_SCORING_TIE_POLICY = "SPLIT"

# Standard meet geometry used across tests
DEFAULT_COURSE = "SCY"
DEFAULT_START_DATE = "2026-08-15"
DEFAULT_SESSION_DATE = "2026-08-15"
DEFAULT_ENTRY_DEADLINE_UTC = "2026-08-10T00:00:00Z"

# Logical clock (PRD §2.4): server startup default before any explicit set.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
# An instant strictly past the default entry deadline — close-entries succeeds.
CLOCK_PAST_DEADLINE = "2026-08-11T00:00:00Z"
# Meet-day instants used for DQ notification / protest-window scenarios.
CLOCK_MEET_DAY_1000 = "2026-08-15T10:00:00Z"
CLOCK_MEET_DAY_1030 = "2026-08-15T10:30:00Z"  # exactly window end at default 30m
CLOCK_MEET_DAY_1031 = "2026-08-15T10:31:00Z"  # strictly past the window

# Swimmer defaults (born 2014-03-10 -> age 12 at a 2026-08-15 start: ELEVEN_TWELVE)
DEFAULT_BIRTH_DATE = "2014-03-10"
DEFAULT_GENDER = "M"
DEFAULT_AGE_GROUP = "ELEVEN_TWELVE"

# Six-lane pool middle-out lane preference (PRD §3.6)
LANE_PRIORITY_6 = [3, 4, 2, 5, 1, 6]
LANE_PRIORITY_8 = [4, 5, 3, 6, 2, 7, 1, 8]
