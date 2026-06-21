"""Domain thresholds — numeric constants from the PRD calculations and validations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Shortage charge per missing garment unit (PRD §3.9, §3.10): 1,500 cents.
SHORTAGE_UNIT_CENTS = 1500

# PAST_DUE crossing threshold (PRD §3.1): strictly above 50,000 cents.
PAST_DUE_THRESHOLD_CENTS = 50000

# Default per-account soil-count grace tolerance (PRD §2.8, §3.1).
DEFAULT_SHORTAGE_GRACE_UNITS = 2

# Damage-fee tier thresholds against soil_strikes (PRD §3.6).
LIGHT_STRIKE_THRESHOLD = 2   # >= 2 strikes -> 0.50 multiplier
HEAVY_STRIKE_THRESHOLD = 4   # >= 4 strikes -> 0.75 multiplier

# Damage-fee tier multipliers (PRD §3.6).
LIGHT_DAMAGE_PCT = 0.25      # fewer than 2 strikes
MODERATE_DAMAGE_PCT = 0.50   # at least 2 strikes
HEAVY_DAMAGE_PCT = 0.75      # at least 4 strikes

# Retire-for-damage strike floor (PRD §3.5): retire requires soil_strikes >= 4.
DAMAGE_RETIRE_STRIKES = 4

# Route-stop travel buffer between sequence-ordered stops (PRD §3.7): 15 minutes.
SEQUENCE_BUFFER_MIN = 15

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
