"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Fixed numeric constants the PRD pins by value.
THRESHOLDS = {
    "MIN_DELAY_HOURS": 12,            # §3.6: delay_hours must be at least 12
    "DELAY_BLOCK_HOURS": 12,          # §3.6: completed delay blocks = floor(delay_hours / 12)
    "SHORT_RATE_ADMIN_FEE_CENTS": 2500,  # §3.5: flat short-rate administrative fee
    "DELAY_MERGE_BUFFER_HOURS": 6,    # §3.7: delay-event six-hour merge buffer
    "DEFAULT_SENIOR_AGE_THRESHOLD": 70,  # §3.1: senior_age_threshold default when omitted
    "BPS_DIVISOR": 10000,             # basis-points divisor
    "PCT_DIVISOR": 100,               # percentage divisor
}

# Standard plan configuration used across most fixtures. Values mirror the
# design-index baseline plan so pre-computed expected amounts line up.
STANDARD_PLAN = {
    "tier": "STANDARD",
    "base_rate_bps": 600,
    "cancellation_limit_pct": 100,
    "medical_limit_cents": 500000,
    "delay_block_cap_cents": 20000,
    "delay_limit_cents": 100000,
    "baggage_item_sublimit_cents": 30000,
    "baggage_limit_cents": 100000,
    "baggage_depreciation_bps": 2000,
    "waiver_window_days": 14,
    "free_look_days": 10,
    "claim_filing_window_days": 90,
    "cfar_loading_bps": 4000,
    "cfar_reimbursement_pct": 75,
    "senior_loading_bps": 5000,
}

BASIC_PLAN = {
    **STANDARD_PLAN,
    "tier": "BASIC",
    "base_rate_bps": 400,
}

PREMIER_PLAN = {
    **STANDARD_PLAN,
    "tier": "PREMIER",
    "base_rate_bps": 800,
}

# Common policy / trip timing defaults.
TEST_DEFAULTS = {
    "TRIP_COST_CENTS": 500000,
    "INITIAL_DEPOSIT_AT": "2026-05-25T00:00:00Z",
    "TRIP_START_AT": "2026-07-01T00:00:00Z",
    "TRIP_END_AT": "2026-07-15T00:00:00Z",
    "BASE_CLOCK": "2026-06-01T00:00:00Z",
    "ADULT_AGE": 36,
    "SENIOR_AGE": 76,
}
