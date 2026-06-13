"""Domain thresholds — numeric constants from the PRD's calculations.

NON_EXISTENT_UUID comes from the framework.
"""

# Fee-waiver eligibility (PRD 3.6)
POVERTY_BASE_CENTS = 130000
POVERTY_PER_PERSON_CENTS = 47000
ELIGIBILITY_CUTOFF = 1.25

# Appeal transmittal fee tiers (PRD 3.8)
APPEAL_BASE_FEE_CENTS = 5000
APPEAL_RATE1 = 50   # cents/page, pages 1-100
APPEAL_RATE2 = 30   # cents/page, pages 101-500
APPEAL_RATE3 = 15   # cents/page, pages 501+

# Judgment interest (PRD 3.7)
BPS_DIVISOR = 10000
DAYS_PER_YEAR = 365

# Case posture (PRD 2.7)
POSTURE_DEADLINE_LIMIT = 5

# Response deadline created on service completion (PRD 3.3)
RESPONSE_DEADLINE_INTERVAL_DAYS = 30

# Court defaults (PRD 3.1)
DEFAULT_APPEAL_WINDOW_DAYS = 30

# Test default court filing fee (a positive COMPLAINT fee so ASSESSED applies)
DEFAULT_FILING_FEE_CENTS = 43500
