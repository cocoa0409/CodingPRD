"""Domain thresholds — numeric constants from the PRD's pricing, settlement,
scoring, refund, and standing-tier calculations (§3.3, §3.5, §3.6, §3.7, §3.8)."""

# Basis-point conventions (§2.6, §3.3).
NEUTRAL_BPS = 10000          # 1.0x
WEEKEND_BPS = 11000          # 1.1x weekend uplift (HOURLY/DAILY only)
OVERSTAY_RATE_BPS = 15000    # 1.5x base hourly for overstay charge
BPS_DENOM = 10000

# Time unit constants (§3.3, §3.5, §3.6).
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
SEVEN_DAYS_S = 604800
ONE_DAY_S = 86400

# Refund tier factors (§3.6).
FULL_REFUND_BPS = 10000      # >= 7 days lead
EARLY_REFUND_BPS = 7500      # >= 1 day & < 7 days lead
LATE_REFUND_BPS = 5000       # >= 0 & < 1 day lead
NO_REFUND_BPS = 0            # at/after start_at

# Violation scoring (§3.8).
KIND_WEIGHT = {"OVERSTAY": 1, "UNAUTHORIZED_GATE": 2, "NO_SHOW": 3}
ESCALATION_STEP_BPS = 2500   # +25% per prior CONFIRMED record
ESCALATION_CAP_STEPS = 3     # capped at +75%

# Driver standing-tier thresholds on confirmed points (§3.8).
WATCH_THRESHOLD = 5          # >= 5 inclusive -> WATCH
SUSPENDED_THRESHOLD = 10     # >= 10 -> SUSPENDED

# Host commission default (§3.1).
DEFAULT_PLATFORM_FEE_BPS = 1500

# AccessPass gate redemptions at mint (§3.4).
GATE_OPENS_AT_CHECKIN = 2

# Logical clock startup default (§2.9).
CLOCK_DEFAULT_ISO = "2026-04-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_HOURLY_CENTS": 400,
    "BASE_DAILY_CENTS": 6000,
    "MONTHLY_FLAT_CENTS": 120000,
    "OVERSTAY_GRACE_MINUTES": 15,
    "WALLET_TOPUP_CENTS": 5000,
    "AVAILABILITY_START": "2026-04-01T00:00:00Z",
    "AVAILABILITY_END": "2026-05-01T00:00:00Z",
}
