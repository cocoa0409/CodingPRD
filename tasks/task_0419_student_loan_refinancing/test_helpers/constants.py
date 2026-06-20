"""Domain thresholds — numeric constants from the PRD's pricing, accrual, and
servicing rules (PRD Sections 2.7, 3.2, 3.4, 3.7, 3.9, 3.10, 3.11)."""

# DTI computation (PRD 3.2 / 3.3)
AMORT_FACTORS = {60: 0.0188, 84: 0.0142, 120: 0.0110, 180: 0.0080, 240: 0.0065}
MAX_DTI_RATIO = 0.4300

# Estimated APR band surcharge (PRD 3.2)
BAND_SURCHARGE_BPS = {"SUBPRIME": 300, "NEAR_PRIME": 150, "PRIME": 50, "SUPER_PRIME": 0}

# Locked APR discounts (PRD 3.4)
AUTOPAY_DISCOUNT_BPS = 25
MEMBER_DISCOUNT_BPS = {"NONE": 0, "SILVER": 10, "GOLD": 25, "PLATINUM": 50}
APR_FLOOR_BPS = 200

# Interest accrual (PRD 3.9)
DAYS_PER_YEAR = 365

# On-time determination / cosigner release (PRD 3.9 / 3.10)
GRACE_DAYS = 5
COSIGNER_RELEASE_STREAK = 3

# Offer expiry (PRD 3.2)
OFFER_TTL_HOURS = 48

# Band ordering (PRD 3.2 soft pull)
BAND_ORDER = ["SUBPRIME", "NEAR_PRIME", "PRIME", "SUPER_PRIME"]

# Pagination (PRD 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Convenient test defaults
TEST_DEFAULTS = {
    "ANNUAL_INCOME_CENTS": 30_000_000,
    "PRINCIPAL_CENTS": 5_000_000,
    "TERM_MONTHS": 120,
    "BASE_APR_BPS": 650,
}
