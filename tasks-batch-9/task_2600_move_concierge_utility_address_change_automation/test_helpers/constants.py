"""Domain constants for the Move Concierge Utility Automation API.

Every value here is stated verbatim in the PRD; nothing is inferred.
"""

# ---------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
# "Before any call to the clock-control endpoint the logical clock reads
#  exactly 2026-08-01T00:00:00Z; that startup default is mandatory".
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Duplicate detection (PRD 3.2)
# ---------------------------------------------------------------------------
DUP_SUSPECT_THRESHOLD = 0.80
W_NAME = 0.35
W_EMAIL = 0.25
W_ADDRESS = 0.25
W_RECENCY = 0.15
PARTIAL_NAME_SCORE = 0.60
PARTIAL_ADDRESS_SCORE = 0.50
DEFAULT_DEDUPE_WINDOW_DAYS = 30
MIN_DEDUPE_WINDOW_DAYS = 1
MAX_DEDUPE_WINDOW_DAYS = 120

# ---------------------------------------------------------------------------
# Readiness scoring (PRD 3.9)
# ---------------------------------------------------------------------------
W_IDENTITY = 0.30
W_UTILITY = 0.30
W_FILING = 0.20
W_CONSENT = 0.20
PRE_VERIFICATION_DIVISOR = 0.70
READINESS_MIN = 0
READINESS_MAX = 100
FILING_COMPONENT_SUBMITTED = 60
FILING_COMPONENT_CONFIRMED = 100
IDENTITY_COMPONENT_PENDING = 50
CONSENT_COMPONENT_ONE_SCOPE = 50
CONSENT_COMPONENT_BOTH_SCOPES = 100

# ---------------------------------------------------------------------------
# Identity verification (PRD 3.3)
# ---------------------------------------------------------------------------
KBA_PASS_SCORE = 700
MAX_IDENTITY_ATTEMPTS = 3
PENDING_TTL_HOURS = 72
IDENTITY_VALIDITY_DAYS = 30

# ---------------------------------------------------------------------------
# Credit and deposits (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------
CREDIT_CLEAR_THRESHOLD = 640
CREDIT_DEPOSIT_FLOOR = 580
DEPOSIT_BASE_CENTS = 15000
DEPOSIT_CAP_CENTS = 50000
SCORE_MULT_LOW = 1.50
SCORE_MULT_MID = 1.25
SCORE_MULT_HIGH = 1.00
READINESS_MULT_WEAK = 1.20
READINESS_MULT_NORMAL = 1.00
READINESS_MULT_STRONG = 0.90
ESTIMATE_SCORE_MULTIPLIER = 1.50
ESTIMATE_READINESS_MULTIPLIER = 1.00
# "A CREDIT_SCORE_BASED provider therefore always estimates 22500 cents."
CREDIT_SCORE_BASED_ESTIMATE_CENTS = 22500
BUREAU_SCORE_MIN = 300
BUREAU_SCORE_MAX = 850

# ---------------------------------------------------------------------------
# Move intake window (PRD 3.2)
# ---------------------------------------------------------------------------
MOVE_DATE_HORIZON_DAYS = 180
MOVE_DATE_PAST_GRACE_DAYS = 30

# ---------------------------------------------------------------------------
# Service windows (PRD 3.5)
# ---------------------------------------------------------------------------
MAX_WINDOW_HOURS = 8

# ---------------------------------------------------------------------------
# Postal filing (PRD 3.7)
# ---------------------------------------------------------------------------
FORWARD_TERM_DAYS = 365
MAX_FILING_RESUBMITS = 2

# ---------------------------------------------------------------------------
# Referral economics (PRD 3.8)
# ---------------------------------------------------------------------------
PROVISIONAL_HOLDBACK_PCT = 0.90
REFERRAL_REVENUE_SHARE_PCT_MAX = 0.5000
REV_SHARE_PCT_MAX = 0.9000
SETTLEMENT_GROSS_MULTIPLE = 2

# ---------------------------------------------------------------------------
# Territory ranks (PRD 3.1)
# ---------------------------------------------------------------------------
PRIORITY_RANK_MIN = 1
PRIORITY_RANK_MAX = 999

# ---------------------------------------------------------------------------
# A UUID that is well formed but resolves to no row.
# ---------------------------------------------------------------------------
NON_EXISTENT_UUID = "00000000-0000-0000-0000-0000000000ff"
