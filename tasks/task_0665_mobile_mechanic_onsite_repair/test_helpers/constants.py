"""Domain thresholds — numeric constants from PRD calculations and global rules."""

# Tiered parts markup bands (PRD §3.9).
MARKUP = {
    "BAND_A_CAP_CENTS": 5000,    # first band: 0..5000 inclusive
    "BAND_B_CAP_CENTS": 20000,   # second band ends at 20000 inclusive
    "BAND_A_RATE": 0.45,
    "BAND_B_RATE": 0.30,
    "BAND_C_RATE": 0.18,
}

# Global domain constants (PRD §2.6, §2.9, §3.1, §3.8).
WARRANTY_WINDOW_DAYS = 30
CALLBACK_BUFFER_MINUTES = 30
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"
ZONE_CODES = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7", "Z8", "Z9"]

# Fleet labor discount bound (PRD §3.1): 0 <= labor_discount_pct <= 0.40.
MAX_LABOR_DISCOUNT_PCT = 0.40

# Common test defaults.
TEST_DEFAULTS = {
    "LABOR_RATE_CENTS_PER_HOUR": 9000,
    "CLOCK_DEFAULT_UTC": CLOCK_DEFAULT_UTC,
}
