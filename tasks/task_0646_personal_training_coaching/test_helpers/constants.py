"""Domain thresholds — numeric constants drawn from the PRD's calculations (§2, §3)."""

THRESHOLDS = {
    # §3.4 / §3.5: a cancellation at least 24h (86,400s) ahead is free; under it is late.
    "NO_SHOW_CUTOFF_SECONDS": 86400,
    # §3.5: late-cancel / no-show fee is 50% of per_session_value_cents.
    "NO_SHOW_FEE_PCT": 0.50,
    # §3.4: the third strike suspends; two strikes stay ALLOWED (inclusive >= 3).
    "NO_SHOW_STRIKE_LIMIT": 3,
    # §3.4: trainer calendar pads each existing booking by 15 minutes (900s) each side.
    "TRAINER_BUFFER_SECONDS": 900,
    # §3.7: monthly subscription cycle is always 30 days.
    "MONTHLY_CYCLE_DAYS": 30,
    # §3.3: invoice tax rate is 8.75%.
    "TAX_PCT": 0.0875,
}

# §3.6 adherence weights.
ADHERENCE_WEIGHTS = {
    "W_WORKOUT": 0.50,
    "W_NUTRITION": 0.30,
    "W_HABIT": 0.20,
}

# §3.7 macro plan constants.
ACTIVITY_MULT = {"SEDENTARY": 1.2, "MODERATE": 1.55, "ACTIVE": 1.725}
SPLIT = {
    "FAT_LOSS": [0.40, 0.30, 0.30],
    "MAINTENANCE": [0.30, 0.40, 0.30],
    "MUSCLE_GAIN": [0.30, 0.45, 0.25],
}

# The server's logical-clock startup default (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-04-01T00:00:00Z"

# Values reused across fixtures to keep setups deterministic.
TEST_DEFAULTS = {
    "PACK_TOTAL_SESSIONS": 5,
    "PACK_PRICE_CENTS": 50000,
    "PER_SESSION_VALUE_CENTS": 10000,
    "MONTHLY_FEE_CENTS": 6000,
}
