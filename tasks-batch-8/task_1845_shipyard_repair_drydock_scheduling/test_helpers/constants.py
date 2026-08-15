"""Domain thresholds and constants from PRD §2.5, §3.2, §3.3, §3.5, §3.7."""

# PRD §2.5: the logical clock reads exactly this instant at startup.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# PRD §3.3: dockage-fee length-overall multiplier tiers and turnaround buffer.
DOCKAGE = {
    "TIER1_MAX_LOA_M": 100,
    "TIER1_MULTIPLIER": 1.00,
    "TIER2_MAX_LOA_M": 200,
    "TIER2_MULTIPLIER": 1.25,
    "TIER3_MULTIPLIER": 1.60,
    "TURNAROUND_BUFFER_HOURS": 12,
}

# PRD §3.7: liquidated-damages tier table, grace days, and percentage cap.
LIQUIDATED_DAMAGES = {
    "GRACE_DAYS": 3,
    "CAP_PCT": 0.10,
    "TIER1_RATE_CENTS": 200000,
    "TIER1_MAX_PRICE_CENTS": 50000000,
    "TIER2_RATE_CENTS": 500000,
    "TIER2_MAX_PRICE_CENTS": 200000000,
    "TIER3_RATE_CENTS": 1000000,
}

# PRD §3.2: materials markup for TIME_AND_MATERIALS pricing.
MATERIALS_MARKUP_PCT = 0.15

# PRD §3.5: owner countersign threshold (strictly greater than).
OWNER_APPROVAL_THRESHOLD_CENTS = 5000000

# PRD §3.4: a firm may hold at most this many IN_PROGRESS work items.
MAX_SUBCONTRACTOR_IN_PROGRESS = 3

# Common windows used across setups.
DEFAULT_CONTRACT_DELIVERY_DATE = "2026-08-10"
DEFAULT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-08-20T00:00:00Z"

TEST_DEFAULTS = {
    "DOCK_DAILY_RATE_CENTS": 400000,
    "DOCK_MAX_LENGTH_M": 230.0,
    "DOCK_MAX_BEAM_M": 40.0,
    "DOCK_MAX_DEPTH_M": 12.0,
    "VESSEL_LENGTH_M": 228.5,
    "VESSEL_BEAM_M": 38.0,
    "VESSEL_DRAFT_M": 10.5,
    "VESSEL_OWNER_USER_ID": "owner_9",
}
