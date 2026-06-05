"""Domain thresholds — numeric constants from PRD calculations."""

# Basis-point denominator: 10000 bps == a full multiplier of 1 (PRD §2.5).
BPS_DENOMINATOR = 10000

# Violation fine tiering (PRD §3.8).
BASE_PENALTY_CENTS = 2500
TIER_STEP_CENTS = 1500

# Account auto-reload defaults (PRD §3.1).
DEFAULT_LOW_BALANCE_THRESHOLD_CENTS = 1000
DEFAULT_RELOAD_AMOUNT_CENTS = 4000
DEFAULT_TARGET_BALANCE_CENTS = 5000

# Plaza defaults (PRD §3.6).
DEFAULT_PEAK_MULTIPLIER_BPS = 0
DEFAULT_AXLE_SURCHARGE_CENTS = 0
DEFAULT_HOV_MIN_OCCUPANTS = 3
DEFAULT_PLATE_SURCHARGE_BPS = 5000

# InteropAgency default clearing fee (PRD §3.9).
DEFAULT_SETTLEMENT_FEE_BPS = 200

# HOV window buffer in minutes (PRD §3.5).
HOV_WINDOW_BUFFER_MINUTES = 15
