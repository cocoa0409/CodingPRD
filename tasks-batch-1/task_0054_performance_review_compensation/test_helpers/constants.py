"""Domain thresholds — numeric constants from the PRD calculation engines.

Sourced from PRD Sections 2.7, 3.5, 3.6, and 3.8.
"""

# Composite score weights (PRD Section 3.5)
GOAL_WEIGHT = 0.70
FEEDBACK_WEIGHT = 0.30
ATTAINMENT_CAP = 1.0

# Merit / promotion matrix (PRD Section 3.8)
PROMO_UPLIFT_PER_BAND = 0.03
MERIT_PCT_CAP = 0.25

# Equity refresh waterfall (PRD Section 3.8)
MIN_TENURE_YEARS = 1
TENURE_STEP = 0.10
TENURE_CAP_YEARS = 5
BAND_EQUITY_FACTOR = {"EXCEEDS": 400, "MEETS": 150, "BELOW": 0}

# Distribution / tolerance (PRD Sections 3.1, 3.4)
DEFAULT_DISTRIBUTION_TOLERANCE = 0.05
DISTRIBUTION_SUM_TOLERANCE = 0.0005

# Precision (PRD Section 2.7)
MONEY_DECIMALS = 2
EQUITY_DECIMALS = 3

# PIP windows (PRD Section 3.7)
PIP_DURATIONS = [30, 60, 90]
