"""Domain thresholds — numeric constants from PRD calculations."""

# Basis-point denominator: 10000 bps == factor 1.0 (PRD §2.5).
BPS_DENOM = 10000

# Overtime is billed per started 15-minute block (PRD §3.7).
OVERTIME_BLOCK_MINUTES = 15

# Cancellation lead-time tiers in basis points (PRD §3.9).
CANCEL_TIER_30_PLUS_DAYS_BPS = 1000     # lead_days >= 30 -> 10%
CANCEL_TIER_14_TO_29_DAYS_BPS = 2500    # 14 <= lead_days < 30 -> 25%
CANCEL_TIER_7_TO_13_DAYS_BPS = 5000     # 7 <= lead_days < 14 -> 50%
CANCEL_TIER_UNDER_7_DAYS_BPS = 10000    # lead_days < 7 (incl past) -> 100%
CANCEL_CONFIRMED_SURCHARGE_BPS = 1000   # +10pp surcharge when CONFIRMED at cancel
CANCEL_FEE_CAP_BPS = 10000              # combined fee capped at 100%

# Seconds in a UTC day, used for lead_days floor (PRD §3.9).
SECONDS_PER_DAY = 86400

# Default package deposit fraction (PRD §3.1).
DEFAULT_DEPOSIT_PCT_BPS = 2500

# Performer score starting values (PRD §3.2).
RELIABILITY_SCORE_START = 100
RELIABILITY_SCORE_FLOOR = 0
RELIABILITY_DECLINE_PENALTY = 5    # decline a backup offer (PRD §3.11)
RELIABILITY_PROMOTE_PENALTY = 10   # former performer on promote (PRD §3.11)

# Song-request defaults (PRD §3.10).
DEFAULT_SONG_PRIORITY = 100

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# Canonical scenario figures used across the difficulty/corner setups.
# Home-zone STANDARD booking: set 200000 + package 50000 = 250000 (no travel).
HOME_QUOTE_CENTS = 250_000
# Charged-zone STANDARD booking with two equipment lines (30000 + 20000) and a
# travel fee of 24000 (round_half_up((10000 + 500*20) * 12000 / 10000)).
CHARGED_QUOTE_CENTS = 324_000
CHARGED_TRAVEL_FEE_CENTS = 24_000
EQUIPMENT_SUM_CENTS = 50_000
