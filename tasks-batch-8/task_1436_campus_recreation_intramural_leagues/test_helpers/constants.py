"""Domain thresholds and fee tables from the PRD (§3.1, §3.4-§3.9)."""

# Membership term windows and flat fees (PRD §3.1).
TERM_WINDOWS = {
    "FALL_2026": ("2026-08-24", "2026-12-11"),
    "SPRING_2027": ("2027-01-12", "2027-05-07"),
    "SUMMER_2027": ("2027-05-24", "2027-08-06"),
}
TERM_FEE_CENTS = {"STUDENT": 6000, "FACULTY": 20000, "COMMUNITY": 32000}
FULL_WINDOW_DAYS = 7  # day 1..7 inclusive -> FULL; day 8+ -> PRORATED

# Locker flat per-term fees by affiliation (PRD §3.9).
LOCKER_FEE_CENTS = {"STUDENT": 1500, "FACULTY": 1500, "COMMUNITY": 3000}

# Official pay (PRD §3.6).
CERT_MULTIPLIER = {1: 1.0, 2: 1.25, 3: 1.5}
TRAVEL_BUFFER_MINUTES = 30
FORFEIT_FLAT_HOURS = 1
MAX_NON_TERMINAL_ASSIGNMENTS_PER_GAME = 2
PLAYOFF_MIN_CERT_LEVEL = 2

# Instructor pay bonus tiers (PRD §3.8), bounds inclusive.
BONUS_TIERS = [(0.80, 0.20), (0.50, 0.10)]

# Standings points (PRD §3.4).
WIN_POINTS = 3
TIE_POINTS = 1
LOSS_POINTS = 0

# Team suspension / playoff eligibility (PRD §3.4, §3.5).
FORFEIT_SUSPENSION_THRESHOLD = 3
PLAYOFF_MIN_RATING = 3.00
PLAYOFF_MAX_FORFEITS = 1

# Logical clock (PRD §2.4).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Common fixture datetimes.
TIME_REG_DAY = "2026-08-24T00:00:00Z"  # FALL_2026 day 1
GAME_START = "2026-09-08T18:00:00Z"  # Tuesday
GAME_END = "2026-09-08T19:30:00Z"
