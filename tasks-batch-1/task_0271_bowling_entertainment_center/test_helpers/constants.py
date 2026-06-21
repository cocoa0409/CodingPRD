"""Domain thresholds — numeric constants from the PRD's pricing, deposit, and
refund rules (PRD §2.8, §3.4, §3.6, §2.9, §2.7).
"""

# Basis-point denominator: 10000 bps == factor of 1 (PRD §2.8).
BPS_DENOM = 10000

# Sales tax on taxable food lines: 825 bps == 8.25% (PRD §3.4).
SALES_TAX_BPS = 825

# Cancellation refund notice tiers (PRD §3.6).
FULL_REFUND_NOTICE_MINUTES = 1440   # 24h -> full refund (>=)
PARTIAL_REFUND_NOTICE_MINUTES = 120  # 2h -> 50% refund (>=)
PARTIAL_REFUND_BPS = 5000            # 50%

# Check-in / hold-expiry timing (PRD §3.5, §3.9).
CHECKIN_WINDOW_MINUTES = 30   # may check in up to 30 min before start_at
HOLD_TTL_MINUTES = 60         # HELD aged >= 60 min expires on clock-advance sweep

# Default config values (PRD §3.1).
DEFAULT_LANE_MAX_BOWLERS = 6
DEFAULT_BAY_CAPACITY = 12
DEFAULT_BAY_CLEANUP_BUFFER_MINUTES = 15
DEFAULT_BLOCK_MINUTES = 60
DEFAULT_PEAK_MULTIPLIER_BPS = 10000
DEFAULT_PEAK_START_HOUR = 18
DEFAULT_PEAK_END_HOUR = 23
DEFAULT_DEPOSIT_PCT_BPS = 2000
DEFAULT_INCLUDED_LANE_HOURS = 2

# Convenience test-default bundle.
TEST_DEFAULTS = {
    "DEPOSIT_PCT_BPS": DEFAULT_DEPOSIT_PCT_BPS,
    "BLOCK_MINUTES": DEFAULT_BLOCK_MINUTES,
}
