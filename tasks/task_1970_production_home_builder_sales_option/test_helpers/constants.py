"""Domain thresholds and calendar constants from the PRD (§2.6, §2.7, §3)."""

# PRD §2.6 — the logical clock's startup reading.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD §3.2 — reservation hold length in hours.
HOLD_HOURS = 72

# PRD §3.2 — per-lot-type premium table and premium cap (integer cents).
LOT_TYPE_PREMIUM_CENTS = {
    "STANDARD": 0,
    "CORNER": 1_500_000,
    "VIEW": 2_500_000,
    "CUL_DE_SAC": 1_000_000,
}
PREMIUM_CAP_CENTS = 3_000_000

# PRD §3.8 — re-release uplift applied on post-contract fallout.
RE_RELEASE_UPLIFT_PCT = 0.02

# PRD §2.7 — planned stage durations and estimate buffers.
STAGE_DURATIONS_DAYS = {
    "PRE_CONSTRUCTION": 30,
    "FOUNDATION": 21,
    "FRAMING": 28,
    "DRYWALL": 35,
    "FINAL_WALKTHROUGH": 14,
}
CLOSE_BUFFER_DAYS = 7
WEATHER_BUFFER_PCT = 0.15

# PRD §3.5 — past-cutoff change fee on confirmed selections.
CHANGE_FEE_PCT = 0.10

# PRD §3.3 / §3.8 — earnest money floor and forfeiture share.
MIN_EARNEST_CENTS = 100_000
EARNEST_FORFEIT_PCT = 0.25

# PRD §3.7 — incentive auto-approval limit and agreement-level cap.
AUTO_APPROVE_LIMIT_CENTS = 300_000
INCENTIVE_CAP_PCT = 0.06

# PRD §3.9 — standard warranty term set at close.
WARRANTY_TERM_MONTHS = 12

# Ordinal ordering of build stages (PRD §2.7).
STAGE_ORDINAL = {
    "NOT_STARTED": 0,
    "PRE_CONSTRUCTION": 1,
    "FOUNDATION": 2,
    "FRAMING": 3,
    "DRYWALL": 4,
    "FINAL_WALKTHROUGH": 5,
    "COMPLETE": 6,
}

# Expected values for the canonical fixture scenario (derived from the PRD
# formulas): community "Cedar Ridge" with phase P1 (uplift 0.03), plan Maple
# (35,000,000; elevations A=0 / B=250,000), lot L-101 (CORNER, base 8,000,000,
# view adjustment 200,000).
CANONICAL_RELEASE_PRICE_CENTS = 9_991_000  # 8,240,000 + 1,751,000
CANONICAL_PROVISIONAL_TOTAL_CENTS = 45_241_000  # 9,991,000 + 35,000,000 + 250,000
CANONICAL_RE_RELEASE_PRICE_CENTS = 10_190_820  # round_half_up(9,991,000 * 1.02)
CANONICAL_INCENTIVE_CAP_CENTS = 2_714_460  # round_half_up(45,241,000 * 0.06)
STANDARD_LOT_RELEASE_PRICE_CENTS = 5_150_000  # round_half_up(5,000,000 * 1.03)

# Closing estimates for a signing at the default clock with all 5 stages open.
CANONICAL_ESTIMATED_CLOSE_STANDARD = "2026-12-14T00:00:00Z"  # 128 + 7 days
CANONICAL_ESTIMATED_CLOSE_PADDED = "2027-01-06T00:00:00Z"  # 151 + 7 days
