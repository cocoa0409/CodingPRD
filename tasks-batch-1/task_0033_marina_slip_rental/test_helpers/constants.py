"""Domain thresholds — numeric constants drawn from PRD §2.6, §3.5, §3.6, §3.7, §3.9."""

# ─── Seasonal pricing multipliers (PRD §3.5) ─────────────────────
# SUMMER tier: multiplier numerator 150, denominator 100 (i.e., 1.50).
SEASONAL_MULTIPLIER_SUMMER_NUM = 150
SEASONAL_MULTIPLIER_SUMMER_DEN = 100
# WINTER tier: multiplier numerator 80, denominator 100 (i.e., 0.80).
SEASONAL_MULTIPLIER_WINTER_NUM = 80
SEASONAL_MULTIPLIER_WINTER_DEN = 100
# Liveaboard surcharge: numerator 110, denominator 100 (i.e., 1.10).
LIVEABOARD_SURCHARGE_NUM = 110
LIVEABOARD_SURCHARGE_DEN = 100

# Liveaboard utility surcharge per night (PRD §3.5, fifteen dollars in cents).
LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS = 1500

# ─── Pump-out charges (PRD §3.6) ─────────────────────────────────
PUMPOUT_PORTABLE_FEE_CENTS = 2500  # twenty-five dollars in cents

# ─── Tow-assist minimum insurance coverage (PRD §3.5, §3.7) ──────
MIN_INSURANCE_COVERAGE_CENTS = 5_000_000  # fifty thousand dollars in cents

# ─── Default seasonal window for marinas (PRD §3.1) ──────────────
DEFAULT_SEASON_SUMMER_START = "05-01"
DEFAULT_SEASON_SUMMER_END = "09-30"

# ─── Default tow-assist radius (PRD §3.1) ────────────────────────
DEFAULT_TOW_ASSIST_RADIUS_NM = 25.0
