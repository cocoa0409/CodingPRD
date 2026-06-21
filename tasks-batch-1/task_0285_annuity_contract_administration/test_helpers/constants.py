"""Domain thresholds and numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Projection / MVA reference rates (PRD §3.5, §3.6).
ASSUMED_GROWTH_BPS = 400        # assumed growth rate when product carries no fixed rate
MARKET_REFERENCE_BPS = 500      # market reference used in the MVA rate differential

# Default minimum initial premium (PRD §3.1): $10,000.00.
DEFAULT_MIN_INITIAL_PREMIUM_CENTS = 1_000_000

# Default free-withdrawal corridor (PRD §3.1): 10.00%.
DEFAULT_FREE_WITHDRAWAL_CORRIDOR_BPS = 1000

# Annuitization age-band factors per $1000 of value per month (PRD §3.8).
AGE_FACTORS_PER_1000 = {
    "band_lt60": 480,
    "band_60_69": 540,
    "band_70_79": 640,
    "band_gte80": 820,
}

# Annuitization option multipliers, applied as a percentage (PRD §3.8).
OPTION_MULT = {
    "LIFE_ONLY": 100,
    "PERIOD_CERTAIN": 92,
    "LIFE_WITH_PERIOD_CERTAIN": 88,
    "JOINT_LIFE": 84,
}

# Period-certain haircut keyed on guaranteed years, applied as a percentage (PRD §3.8).
PERIOD_CERTAIN_HAIRCUT = {10: 100, 15: 96, 20: 92}

# Annuitant age domain (PRD §3.2): whole years 0..85 inclusive.
ANNUITANT_AGE_MIN = 0
ANNUITANT_AGE_MAX = 85

# Allocation / beneficiary / share completeness target (PRD §3.2, §3.7, §3.9).
FULL_BPS = 10000
