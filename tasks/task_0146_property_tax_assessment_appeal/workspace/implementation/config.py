"""System constants from the PRD/SCAFFOLD."""

from decimal import Decimal

# Growth cap on capped assessed value (Prop 13 style)
GROWTH_CAP = Decimal("0.02")  # 2%

# Exemption stack constants
HOMESTEAD_PCT = Decimal("0.20")
HOMESTEAD_CAP_DOLLARS = Decimal("75000")
SENIOR_FLAT = Decimal("25000")
VETERAN_FLAT = Decimal("15000")
DISABILITY_FULL = Decimal("30000")
DISABILITY_MIN_PCT = 50
SENIOR_AGE = 65

# Tax bill defaults
DEFAULT_MILL_RATE = Decimal("12.5")
DUE_WINDOW_DAYS = 30

# Appeal window
APPEAL_WINDOW_DAYS = 30

# Hearing constraints
HEARING_MAX_DURATION_MIN = 120
OFFICER_BUFFER_MIN = 15
GRACE_MIN = 30

# Deferral plan
DEFERRAL_INTEREST_RATE = Decimal("0.05")
DEFERRAL_MAX_TERM_DAYS = 365
DEFERRAL_DISABILITY_MIN_PCT = 50

# Pagination
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Valid roles
VALID_ROLES = {"Assessor", "Treasurer", "HearingOfficer", "Owner"}
