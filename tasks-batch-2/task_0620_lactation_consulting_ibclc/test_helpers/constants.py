"""Domain thresholds — numeric constants drawn from the PRD's calculations (§3)."""

THRESHOLDS = {
    # §3.6: the third no-show strike suspends; two strikes do not (inclusive >= 3).
    "NO_SHOW_SUSPEND_THRESHOLD": 3,
    # §3.10: STANDARD_ELECTRIC qualifies when infant age in days is at or below 30 (inclusive).
    "DME_WINDOW_DAYS": 30,
}

# Values reused across fixtures to keep setups deterministic.
TEST_DEFAULTS = {
    "STANDARD_RATE_CENTS": 20000,
    "TRAVEL_BUFFER_MINUTES": 60,
}
