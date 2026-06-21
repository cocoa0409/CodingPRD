"""Domain thresholds — numeric constants from PRD calculations (Section 3, 2.5).

All money is integer cents. Constants mirror the rate/threshold values stated
in the PRD prose; tests import these so expected values stay in one place.
"""

# Add-on service fees (PRD Section 3.2)
ASSEMBLY_FEE_PER_UNIT_CENTS = 4900
HAUL_AWAY_FEE_PER_UNIT_CENTS = 3500

# Delivery tier flat fees (PRD Section 3.3)
THRESHOLD_FEE_CENTS = 7900
WHITE_GLOVE_FEE_CENTS = 19900

# Tax (PRD Section 3.3)
TAX_RATE_BPS = 825  # 8.25%, applied once on the combined taxable base

# Financing — monthly payment (PRD Section 3.5)
INSTALLMENT_APR_BPS = 1200  # 12% add-on, prorated by term_months/12
LEASE_MARKUP_NUM = 13
LEASE_MARKUP_DEN = 10  # lease-to-own total = 1.30x principal

# Financing — eligibility gates (PRD Section 3.5)
MIN_CREDIT_SCORE_INSTALLMENT = 640
MIN_CREDIT_SCORE_LEASE_TO_OWN = 600
MAX_DTI_PCT = 43  # MAX_DTI = 0.43, compared as exact integers
MAX_OPEN_PLANS = 2

# Protection premium (PRD Section 3.7)
BASIC_RATE_BPS = 300   # 3% of line total per year
PREMIUM_RATE_BPS = 650  # 6.5% of line total per year

# Return windows (PRD Section 3.10)
STANDARD_RETURN_WINDOW_DAYS = 30
MATTRESS_RETURN_WINDOW_DAYS = 100

# Return refund (PRD Section 3.10)
RESTOCK_RATE_BPS = 1500  # 15% restocking fee on change-of-mind returns

THRESHOLDS = {
    "ASSEMBLY_FEE_PER_UNIT_CENTS": ASSEMBLY_FEE_PER_UNIT_CENTS,
    "HAUL_AWAY_FEE_PER_UNIT_CENTS": HAUL_AWAY_FEE_PER_UNIT_CENTS,
    "THRESHOLD_FEE_CENTS": THRESHOLD_FEE_CENTS,
    "WHITE_GLOVE_FEE_CENTS": WHITE_GLOVE_FEE_CENTS,
    "TAX_RATE_BPS": TAX_RATE_BPS,
    "INSTALLMENT_APR_BPS": INSTALLMENT_APR_BPS,
    "LEASE_MARKUP_NUM": LEASE_MARKUP_NUM,
    "LEASE_MARKUP_DEN": LEASE_MARKUP_DEN,
    "MIN_CREDIT_SCORE_INSTALLMENT": MIN_CREDIT_SCORE_INSTALLMENT,
    "MIN_CREDIT_SCORE_LEASE_TO_OWN": MIN_CREDIT_SCORE_LEASE_TO_OWN,
    "MAX_DTI_PCT": MAX_DTI_PCT,
    "MAX_OPEN_PLANS": MAX_OPEN_PLANS,
    "BASIC_RATE_BPS": BASIC_RATE_BPS,
    "PREMIUM_RATE_BPS": PREMIUM_RATE_BPS,
    "STANDARD_RETURN_WINDOW_DAYS": STANDARD_RETURN_WINDOW_DAYS,
    "MATTRESS_RETURN_WINDOW_DAYS": MATTRESS_RETURN_WINDOW_DAYS,
    "RESTOCK_RATE_BPS": RESTOCK_RATE_BPS,
}
