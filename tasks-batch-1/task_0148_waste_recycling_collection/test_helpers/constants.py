"""Domain thresholds — numeric constants from the PRD's charge calculations.

All money is integer cents (PRD §2.6). Tier breakpoints are in pounds.
"""

# Pay-as-you-throw weight charge (PRD §3.6 #2)
FREE_ALLOWANCE_LBS = {
    "RESIDENTIAL": 100,
    "COMMERCIAL_SMALL": 0,
    "COMMERCIAL_LARGE": 0,
}
RATE_PER_LB_CENTS = {
    "RESIDENTIAL": {"t1": 5, "t2": 8, "t3": 12},
    "COMMERCIAL_SMALL": {"t1": 7, "t2": 10, "t3": 15},
    "COMMERCIAL_LARGE": {"t1": 6, "t2": 9, "t3": 13},
}
TIER1_UPPER_LBS = 200
TIER2_UPPER_LBS = 500

# Contamination surcharge (PRD §3.6 #3)
SEVERITY_RATE_PER_LB_CENTS = {"MINOR": 2, "MAJOR": 5, "REJECT": 10}
SEVERITY_FLAT_CENTS = {"MINOR": 500, "MAJOR": 1500, "REJECT": 4000}

# Special-pickup fee schedule (PRD §3.7)
BASE_FEE_CENTS = {"BULK": 3500, "HAZARDOUS": 8000}
HAZARD_MULT = {"FLAMMABLE": 1.5, "CORROSIVE": 1.75, "TOXIC": 2.0, "EWASTE": 1.25}

# Missed-pickup credit amounts (PRD §3.7)
CREDIT_FLAT_CENTS_PICKUP = 1500
SPECIAL_REFUND_PCT = 0.5

# Diversion penalty (PRD §3.6 #4)
PENALTY_CENTS_PER_PCT_POINT = 100

# Pagination (PRD §2.3)
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}

# Cart capacity domain (PRD §3.1)
VALID_SIZE_GALLONS = (35, 65, 96)
