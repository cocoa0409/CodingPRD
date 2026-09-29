"""Domain constants and canonical test values taken from the PRD."""

# The logical clock starts at exactly this instant on a freshly started server.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Money and award arithmetic (PRD ceremony logistics section).
NIGHTLY_PER_DIEM_CENTS = 18333
AIRFARE_CAP_CENTS = 95000
POSTHUMOUS_TRAVELER_COUNT = 2
LIVING_TRAVELER_COUNT = 1
POSTHUMOUS_PER_DIEM_FACTOR = 0.75
LIVING_PER_DIEM_FACTOR = 1.0
AUSTERITY_REDUCED_AT = 0.50
AUSTERITY_MINIMAL_AT = 0.80
TIER_FACTORS = {"FULL": 1.0, "REDUCED": 0.8, "MINIMAL": 0.6}

# Vote allowance arithmetic (PRD ballot construction section).
VOTES_DIVISOR = 2
MIN_VOTES_FLOOR = 1
MAX_VOTES_CAP = 5

# Round and quota bounds.
MAX_ROUNDS = 3
MIN_RUNOFF_CONTENDERS = 2
MAX_INFO_REQUESTS = 2
SPECIAL_MAX_PER_CYCLE = 1
LAPSE_MISSED_CYCLES = 2

# Career eligibility arithmetic.
POSTHUMOUS_WAITING_YEARS = 1
VETERANS_MIN_YEARS = 25
VETERANS_COOLDOWN_YEARS = 3

# Pagination defaults (PRD pagination section).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1

# Canonical test values reused across fixtures.
TEST_DEFAULTS = {
    "SPORT_CODE": "BASEBALL",
    "CYCLE_YEAR": 2026,
    "MAX_INDUCTEES": 5,
    "TRAVEL_BUDGET_CENTS": 1_000_000,
    "ESCORT_POOL_SIZE": 1,
    "BLOC_CODE": "WRITERS",
    "BLOC_NAME": "Baseball Writers",
    "SEAT_CAP": 10,
    "MIN_PARTICIPATION_PCT": 0.5,
    "CREDENTIAL_EXPIRES_ON": "2027-12-31T00:00:00Z",
    "BALLOT_OPENS_AT": "2026-08-01T00:00:00Z",
    "BALLOT_CLOSES_AT": "2026-08-20T00:00:00Z",
    "CEREMONY_DATE": "2026-11-15T18:00:00Z",
    "CEREMONY_VENUE": "Hall Rotunda",
}

# Eligibility rule shape reused by nearly every fixture.
RULE_DEFAULTS = {
    "waiting_period_years": 5,
    "min_career_seasons": 10,
    "min_career_metric": 2000,
    "max_ballot_appearances": 3,
    "election_threshold_pct": 0.75,
    "carryover_min_pct": 0.05,
    "runoff_floor_pct": 0.25,
}
