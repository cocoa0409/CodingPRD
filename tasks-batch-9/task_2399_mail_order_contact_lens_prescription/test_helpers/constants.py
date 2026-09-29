"""Domain thresholds and canonical test values drawn from the PRD."""

# ---------------------------------------------------------------- order total
FREE_SHIPPING_THRESHOLD_CENTS = 5000
STANDARD_SHIPPING_CENTS = 695

# ------------------------------------------------------ parameter deviation
WEIGHT_BASE_CURVE = 4
WEIGHT_DIAMETER = 2
WEIGHT_SPHERE_PER_EYE = 1
AUTO_APPROVE_MAX_INDEX = 0.50
CONSENT_MAX_INDEX = 1.00

# ---------------------------------------------------- business-hour clock
BUSINESS_DAY_START_UTC = "08:00"
BUSINESS_DAY_END_UTC = "17:00"
BUSINESS_HOURS_PER_DAY = 9
DIRECTORY_VERIFIED_BUSINESS_HOURS = 8
SELF_REPORTED_BUSINESS_HOURS = 12
CONTACT_COOLDOWN_BUSINESS_HOURS = 4
BUSINESS_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]

# ------------------------------------------------------------ return settlement
TORN_LENS_CAP_RATE = 0.20

# ------------------------------------------------------ insurance reimbursement
FEE_TIER_1_MAX_CENTS = 5000
FEE_TIER_1_CENTS = 0
FEE_TIER_2_MAX_CENTS = 15000
FEE_TIER_2_CENTS = 250
FEE_TIER_3_CENTS = 500

# --------------------------------------------------------- auto-reorder cadence
MIN_CADENCE_DAYS = 14
REORDER_LEAD_TIME_DAYS = 5
DAYS_PER_LENS_DAILY_DISPOSABLE = 1
DAYS_PER_LENS_BIWEEKLY = 14
DAYS_PER_LENS_MONTHLY = 30
MAX_CONSECUTIVE_SKIPS = 2
RUN_HOUR_UTC = "08:00"

# --------------------------------------------------------------- verification
MAX_VERIFICATION_ROUNDS = 3

# ----------------------------------------------------------- allowance ledger
INCLUDED_CLAIM_STATUSES = ["GENERATED", "SUBMITTED"]

# ------------------------------------------------------------------ pagination
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ------------------------------------------------------------- logical clock
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
"""The clock reads this value until it is explicitly set."""

WORKING_TUESDAY_10AM = "2026-09-08T10:00:00Z"
"""A Tuesday inside business hours, used as the anchor for deadline arithmetic."""

# ------------------------------------------------------------- actor user ids
ADMIN_ROOT = "admin-root"
CO_ALPHA = "co-alpha"
CO_BRAVO = "co-bravo"
FO_ONE = "fo-one"

# ------------------------------------------------- canonical uuids that resolve
# to nothing, used for not-found assertions.
UNKNOWN_ORDER_UUID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_CUSTOMER_UUID = "00000000-0000-0000-0000-0000000000aa"
UNKNOWN_PLAN_UUID = "00000000-0000-0000-0000-0000000000bb"
UNKNOWN_PRESCRIPTION_UUID = "00000000-0000-0000-0000-0000000000cc"
UNKNOWN_PRODUCT_UUID = "00000000-0000-0000-0000-0000000000dd"
UNKNOWN_PRESCRIBER_UUID = "00000000-0000-0000-0000-0000000000ee"
UNKNOWN_GENERIC_UUID = "00000000-0000-0000-0000-00000000001a"
