"""Domain thresholds — numeric constants from the Renters Insurance PRD.

Generic NON_EXISTENT_UUID comes from the framework. The well-formed but
unknown UUID below is used where a specific 4xx-on-missing case is asserted.
"""

# Premium calculation (PRD §3.2)
BASE_POLICY_FEE_CENTS = 12000
PP_RATE = 0.004
LIAB_RATE = 0.0008
LOU_RATE = 0.0015
SCHED_RATE = 0.018
BUNDLE_DISCOUNT_FACTOR = 0.90
INSTALLMENT_SURCHARGE_PCT = 0.05
TERRITORY_FACTORS = {"HIGH": 1.25, "STANDARD": 1.00, "LOW": 0.85}

# Bundle membership (PRD §3.1)
MIN_BUNDLE_MEMBERS = 2

# Claim settlement (PRD §3.8)
MAX_DEPRECIATION_PCT = 0.80

# Cancellation refund (PRD §3.5)
SHORT_RATE_PENALTY_PCT = 0.10

# Lapse / reinstatement timing (PRD §3.4, §3.5)
GRACE_DAYS = 14
REINSTATE_WINDOW_DAYS = 30

# Appeals (PRD §3.8)
MAX_APPEALS = 2

# Standard reference figures used across fixtures/tests.
# A STANDARD-territory policy with PP 3000000 + LIABILITY 10000000 +
# LOSS_OF_USE 900000, no scheduled items, no bundle discount, prices to:
#   12000 + 12000 + 8000 + 1350 = 33350 cents.
STANDARD_ANNUAL_PREMIUM_CENTS = 33350

# Common coverage limits used to build a fully-covered STANDARD policy.
PP_LIMIT_CENTS = 3000000
LIAB_LIMIT_CENTS = 10000000
LOU_LIMIT_CENTS = 900000

# A well-formed UUID that resolves to no resource.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
