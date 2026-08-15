"""Domain thresholds and shared constants from the PRD's pricing and timing rules."""

# Logical clock startup default (PRD §2.5); the server starts here after every
# restart, so fixtures never need to set the clock to this value.
START_CLOCK = "2026-08-01T00:00:00Z"

# Default future audition deadline used by project payloads.
DEFAULT_AUDITION_DEADLINE = "2026-08-10T00:00:00Z"

# Provisional buyout quote (PRD §3.2)
UNION_SCALE_SESSION_FEE_CENTS = 65000
USAGE_MULT_BROADCAST = 2.50
USAGE_MULT_DIGITAL = 1.50
TERM_BASE_MULT = 1.00
TERM_PER_MONTH_MULT = 0.10
SPOT_UPLIFT_PER_EXTRA = 0.20

# Union multiplier on the talent's own fee (PRD §3.4)
UNION_MULT_UNION = 1.00
UNION_MULT_FICORE = 1.00
UNION_MULT_NON_UNION = 0.85

# Agency commission tiers (PRD §3.4)
TIER1_MAX_CENTS = 500000        # buyout < 500000 -> 10%
TIER2_MAX_CENTS = 1500000       # [500000, 1500000) -> 15%; >= 1500000 -> 20%
TIER1_PCT = 0.10
TIER2_PCT = 0.15
TIER3_PCT = 0.20
UNION_REDUCTION = 0.02
COMMISSION_FLOOR_PCT = 0.05

# Session fee final variant (PRD §3.7)
MIN_BILLED_MINUTES = 15
FINAL_GRANULARITY_MINUTES = 5
PROVISIONAL_BLOCK_MINUTES = 15
DIRECTED_PATCH_SURCHARGE = 0.25

# Delivery revision window (PRD §3.8)
REVISION_WINDOW_HOURS = 72

# Session shape rule (PRD §3.6)
MIN_SESSION_DURATION_MINUTES = 15

TEST_DEFAULTS = {
    "TALENT_BASE_FEE_CENTS": 80000,
    "STUDIO_HOURLY_RATE_CENTS": 20000,
}
