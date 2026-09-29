"""PRD-derived literal constants.

Every value here is quoted from the PRD; nothing is invented. Section
references are given inline so a reader can check each literal.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------
# "whose value at server startup is exactly `2026-08-01T00:00:00.000Z`"
CLOCK_START = "2026-08-01T00:00:00.000Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Precision regimes (PRD §2.8)
# --------------------------------------------------------------------------
GPA_DECIMALS = 3
SEED_POINT_DECIMALS = 4
INTEGRITY_DECIMALS = 2

# --------------------------------------------------------------------------
# District defaults (PRD §3.1)
# --------------------------------------------------------------------------
DEFAULT_MAX_AGE_RATING = "T"
DEFAULT_ACADEMIC_STANDING_BASIS = "TERM_SNAPSHOT"
DEFAULT_MIN_GPA = 2.000
DEFAULT_PROBATION_GPA_FLOOR = 1.750
DEFAULT_DISPUTE_WINDOW_HOURS = 48
DEFAULT_SUBSIDY_PCT = 0.250
DEFAULT_SUBSIDY_POOL_CENTS = 5000000
DEFAULT_RECRUITING_CONTACT_CAP_PER_WINDOW = 3
DEFAULT_RECRUITING_WINDOW_DAYS = 30
DEFAULT_BROADCAST_BUFFER_MINUTES = 15

# --------------------------------------------------------------------------
# School defaults (PRD §3.1)
# --------------------------------------------------------------------------
DEFAULT_ENROLLMENT_VERIFIED_THROUGH = "2027-06-30"
DEFAULT_CONCURRENT_BROADCAST_CAPACITY = 1

# --------------------------------------------------------------------------
# Title defaults (PRD §3.3)
# --------------------------------------------------------------------------
DEFAULT_AGE_RATING = "T"
DEFAULT_MIN_PLAYER_AGE = 13
DEFAULT_SERVER_POOL_ID = "POOL-DEFAULT"
DEFAULT_SERVER_POOL_CAPACITY = 1
DEFAULT_MATCH_DURATION_MINUTES = 60

# --------------------------------------------------------------------------
# Season defaults (PRD §3.4)
# --------------------------------------------------------------------------
DEFAULT_REGISTRATION_OPENS_AT = "2026-08-01T00:00:00.000Z"
DEFAULT_REGISTRATION_CLOSES_AT = "2026-09-15T23:59:59.999Z"
DEFAULT_ROSTER_LOCK_AT = "2026-09-20T00:00:00.000Z"
DEFAULT_REGULAR_SEASON_END_AT = "2026-11-30T00:00:00.000Z"
DEFAULT_AGE_CUTOFF_DATE = "2026-09-01"
DEFAULT_MAX_AGE = 19
DEFAULT_MIN_STARTERS = 1
DEFAULT_MAX_STARTERS = 3
DEFAULT_BASE_ENTRY_FEE_CENTS = 12510
DEFAULT_PER_STARTER_FEE_CENTS = 3335
DEFAULT_SEEDING_BASIS = "MATCH_POINT_BASIS"
DEFAULT_PLAYOFF_SLOTS = 2

# --------------------------------------------------------------------------
# Age-rating ordinal scale (PRD §3.1 / §3.3)
# --------------------------------------------------------------------------
AGE_RATING_SCALE = {"E": 0, "E10": 1, "T": 2, "M": 3}

# --------------------------------------------------------------------------
# Fair-play integrity scoring (PRD §3.8)
# --------------------------------------------------------------------------
INTEGRITY_SCORE_START = 100.00
INTEGRITY_FLOOR = 40.00
INTEGRITY_MIN = 0.00
INTEGRITY_MAX = 100.00
# "a severity component worth 5 for MINOR, 15 for MAJOR and 40 for SEVERE"
SEVERITY_COMPONENT = {"MINOR": 5, "MAJOR": 15, "SEVERE": 40}
# "a case-type surcharge worth 5 for ACCOUNT_SHARING, 10 for SMURFING,
#  20 for CHEAT_DETECTION and 0 for SPECTATOR_CONDUCT"
CASE_TYPE_SURCHARGE = {
    "ACCOUNT_SHARING": 5,
    "SMURFING": 10,
    "CHEAT_DETECTION": 20,
    "SPECTATOR_CONDUCT": 0,
}
# "1.0 for the first case in the set, 1.5 for the second, and 2.0 for the
#  third and every case after it"
REPEAT_MULTIPLIERS = [1.0, 1.5, 2.0]
CLEAN_CONDUCT_DAYS_PER_BLOCK = 30
CLEAN_CONDUCT_POINTS_PER_BLOCK = 5
CLEAN_CONDUCT_MAX_CREDIT = 10

# --------------------------------------------------------------------------
# Broadcast (PRD §3.8)
# --------------------------------------------------------------------------
MAX_SPECTATOR_STRIKES = 3

# --------------------------------------------------------------------------
# Match points (PRD §3.7)
# --------------------------------------------------------------------------
POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0
POINTS_FORFEIT_WIN = 3

# --------------------------------------------------------------------------
# Showcase scholarship projection (PRD §3.9)
# --------------------------------------------------------------------------
SCHOLARSHIP_BASE_CENTS = 150000
SEED_BONUS_PER_RANK_CENTS = 45000
SEED_BONUS_REFERENCE_RANK = 5
ACADEMIC_MULTIPLIER = {
    "GOOD": 1.0,
    "PROBATION": 0.5,
    "UNEVALUATED": 0.0,
    "INELIGIBLE": 0.0,
}
TIER_GOLD_FLOOR_CENTS = 350000
TIER_SILVER_FLOOR_CENTS = 200000
TIER_BONUS_RATE = {"BRONZE": 0.05, "SILVER": 0.12, "GOLD": 0.20}

# --------------------------------------------------------------------------
# Convenience clock instants used by fixtures
# --------------------------------------------------------------------------
T_2026_08_01 = "2026-08-01T00:00:00.000Z"
T_2026_08_02 = "2026-08-02T00:00:00.000Z"
T_2026_08_03 = "2026-08-03T00:00:00.000Z"
T_2026_08_05 = "2026-08-05T00:00:00.000Z"
T_2026_08_10 = "2026-08-10T00:00:00.000Z"
T_2026_08_15 = "2026-08-15T00:00:00.000Z"
T_2026_09_01 = "2026-09-01T00:00:00.000Z"
T_2026_09_15 = "2026-09-15T00:00:00.000Z"
T_2026_09_21 = "2026-09-21T00:00:00.000Z"
T_2026_10_01 = "2026-10-01T00:00:00.000Z"
T_2026_12_01 = "2026-12-01T00:00:00.000Z"
