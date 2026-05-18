"""Static configuration values used across the API."""

# Roles recognized by the system (X-User-Role header values).
ROLES = {"Debtor", "Trustee", "Creditor", "Judge"}

# Pagination defaults per response_envelope.pagination_defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Means-test fixed state median annual income table (in cents).
# Keyed by (state_code, household_size) with documented defaults for unknown.
STATE_MEDIAN_TABLE = {
    ("CA", 1): 6_500_000,
    ("CA", 2): 8_500_000,
    ("TX", 1): 6_000_000,
    ("TX", 2): 8_000_000,
}

# Fallbacks (in cents) for combinations not present in STATE_MEDIAN_TABLE.
DEFAULT_STATE_MEDIAN_1 = 6_000_000
DEFAULT_STATE_MEDIAN_2 = 8_000_000

# Required schedule letters (A-J).
REQUIRED_SCHEDULES = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
SCHEDULE_TYPES = set(REQUIRED_SCHEDULES)

# Chapter enum values.
CHAPTERS = {"CHAPTER_7", "CHAPTER_13"}

# Creditor/claim class enums.
CREDITOR_TYPES = {"SECURED", "PRIORITY", "GENERAL_UNSECURED"}

# CollectionAction kinds.
COLLECTION_ACTION_KINDS = {"GARNISH", "LIEN", "LAWSUIT", "DUNNING_LETTER"}

# 21-day gap between filing and 341 meeting.
MEETING_341_MIN_DAYS_AFTER_FILING = 21

# Strict three-strikes default boundary for dismissal from IN_REPAYMENT.
DISMISSAL_MIN_MISSED_PAYMENTS = 3

# Administrative fee rate for waterfall (10%).
ADMIN_FEE_RATE_NUMERATOR = 1
ADMIN_FEE_RATE_DENOMINATOR = 10
