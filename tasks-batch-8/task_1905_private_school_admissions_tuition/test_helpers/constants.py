"""Domain thresholds and default values from the PRD's calculation rules (§3)."""

# Logical clock (PRD §2.4)
BOOT_CLOCK = "2026-08-01T00:00:00Z"

# Standard cycle deadlines used across fixtures (PRD §3.1 ordering:
# early < regular < reenroll <= melt).
DEADLINES = {
    "EARLY": "2026-11-01T00:00:00Z",
    "REGULAR": "2027-01-15T00:00:00Z",
    "REENROLL": "2027-03-01T00:00:00Z",
    "MELT": "2027-08-01T00:00:00Z",
}

# Composite score (PRD §3.3)
TEST_WEIGHT = 0.6
INTERVIEW_WEIGHT = 0.4
SIBLING_POINTS = 10
LEGACY_POINTS = 5

# Committee ranking / offers (PRD §3.5)
OFFER_EXPIRY_DAYS = 21
PROMOTED_OFFER_EXPIRY_DAYS = 7
CONTRACT_RESPONSE_DAYS = 14

# Aid award formula (PRD §3.4)
HOUSEHOLD_BASE_ALLOWANCE_CENTS = 2_500_000
HOUSEHOLD_PER_MEMBER_CENTS = 750_000
TIER1_WIDTH_CENTS = 2_500_000
TIER2_WIDTH_CENTS = 5_000_000
TIER1_RATE = 0.12
TIER2_RATE = 0.22
TIER3_RATE = 0.30
MAX_AWARD_PCT = 0.90

# Deposit (PRD §3.5 estimated variant, §3.6 final variant)
DEPOSIT_PCT = 0.10
MIN_DEPOSIT_CENTS = 50_000

# Aid pacing (PRD §3.1)
EARLY_PACING_PCT = 0.40
MID_PACING_PCT = 0.75

# Re-enrollment sibling pricing (PRD §3.7)
SIBLING_DISCOUNT_PCT = 0.10

TEST_DEFAULTS = {
    "AID_BUDGET_CENTS": 18_050_000,
    "TUITION_CENTS": 3_000_000,
    "SECTION_CAPACITY": 5,
    "MAX_AID_SEAT_PCT": 0.5,
    "SESSION_CAPACITY": 5,
}

# Default evaluation windows (inside the default session window).
TEST_WINDOW = ("2026-10-10T09:00:00Z", "2026-10-10T10:00:00Z")
INTERVIEW_WINDOW = ("2026-10-12T10:00:00Z", "2026-10-12T11:00:00Z")

# Standard close/sweep instants.
EARLY_CLOSE_CLOCK = "2026-11-02T00:00:00Z"   # one day past the EARLY deadline
REGULAR_CLOSE_CLOCK = "2027-01-16T00:00:00Z"  # one day past the REGULAR deadline
