"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD: the logical clock reads
# exactly 2026-08-01T00:00:00Z at server startup, never wall-clock time).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Standard rights period used across tests unless overridden.
DEFAULT_SELLABLE_FROM = "2026-08-01T00:00:00Z"
DEFAULT_SELLABLE_TO = "2027-08-01T00:00:00Z"

# Standard metadata spec string used by test platforms.
DEFAULT_METADATA_SPEC = "MEC-2.3"

THRESHOLDS = {
    # Volume-discount tiers on the gross guaranteed total of accepted lines;
    # each boundary is inclusive (gross >= threshold).
    "TIER_1_THRESHOLD_CENTS": 5_000_000,
    "TIER_1_PCT": 15,
    "TIER_2_THRESHOLD_CENTS": 2_000_000,
    "TIER_2_PCT": 10,
    "TIER_3_THRESHOLD_CENTS": 500_000,
    "TIER_3_PCT": 5,
    # Termination proration: length of one monthly block in days.
    "DAYS_PER_MONTH_BLOCK": 30,
}

# Holdback matrix: exclusive licenses on a window block the listed downstream
# windows for the given number of days beyond license_end. Empty rows block
# nothing cross-window (holdback_until stays null).
HOLDBACK_MATRIX = {
    "THEATRICAL": {"EST": 90, "TVOD": 90, "SVOD": 90, "AVOD": 90, "FREE_TV": 90},
    "EST": {"SVOD": 60, "AVOD": 60, "FREE_TV": 60},
    "TVOD": {"SVOD": 30, "AVOD": 30, "FREE_TV": 30},
    "SVOD": {"AVOD": 30, "FREE_TV": 30},
    "AVOD": {},
    "FREE_TV": {},
}

TEST_DEFAULTS = {
    "HOLDER_SHARE_PCT": 100,
    "FLAT_FEE_CENTS": 10000,
    "OFFER_EXPIRES_AT": "2026-12-01T00:00:00Z",
}
