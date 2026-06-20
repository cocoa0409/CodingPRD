"""Domain thresholds — numeric constants from the PRD calculations (PRD §3).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Basis-point denominator: 10000 bps == 100 percent (PRD §2.7).
BPS_DENOM = 10000

# Refund-tier floors (PRD §3.7).
FIFTY_FLOOR_BPS = 5000
NINETY_FLOOR_BPS = 9000

# Plan knob defaults (PRD §3.1).
DEFAULT_DECLINING_MONTHLY_BPS = 200
DEFAULT_DECLINING_NONREFUNDABLE_BPS = 400
DEFAULT_ASSISTED_SURCHARGE_CENTS = 0
DEFAULT_SKILLED_PER_DIEM_CENTS = 0
DEFAULT_TYPEB_DISCOUNTED_DAYS = 0

# Community defaults (PRD §2.11 / §3.1).
DEFAULT_TARGET_FUNDED_RATIO_BPS = 10000
DEFAULT_RESERVE_ASSETS_CENTS = 0

# Actuarial reserve disclosure (PRD §3.6).
ACTUARIAL_HORIZON_MONTHS = 240
DEFICIENCY_FREEZE_DIVISOR = 2

# Unit (PRD §3.1).
DEFAULT_BED_CAPACITY = 1

# Council (PRD §3.8).
DEFAULT_QUORUM_PCT_BPS = 5000

# Invoice skilled-day bound (PRD §3.6).
DAYS_IN_MONTH = 30
