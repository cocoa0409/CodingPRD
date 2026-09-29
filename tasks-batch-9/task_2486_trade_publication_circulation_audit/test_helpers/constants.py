"""Constants drawn from the PRD: defaults, bounds, thresholds and clock anchors."""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
CLOCK_PATH = "/_clock/set_current_utc"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Publication defaults and bounds (PRD §3.1)
# --------------------------------------------------------------------------
DEFAULT_QUALIFICATION_VALIDITY_MONTHS = 36
QUALIFICATION_VALIDITY_MONTHS_MIN = 1
QUALIFICATION_VALIDITY_MONTHS_MAX = 60

DEFAULT_RENEWAL_GRACE_DAYS = 90
RENEWAL_GRACE_DAYS_MIN = 0
RENEWAL_GRACE_DAYS_MAX = 365

DEFAULT_SOURCE_DOC_RETENTION_MONTHS = 36
SOURCE_DOC_RETENTION_MONTHS_MIN = 1
SOURCE_DOC_RETENTION_MONTHS_MAX = 120

DEFAULT_UNDELIVERABLE_RESTRICT_PCT = 5.00
DEFAULT_MATERIALITY_PCT = 2.00
DEFAULT_CONTROLLED_CAP_PCT = 25.00
PCT_MIN = 0.00
PCT_MAX = 99.00

PUBLICATION_NAME_MIN_LEN = 1
PUBLICATION_NAME_MAX_LEN = 200
INDUSTRY_CODE_MIN_LEN = 1
INDUSTRY_CODE_MAX_LEN = 40

# Qualification rules (PRD §3.1)
ALLOWED_VALUES_MIN = 1
ALLOWED_VALUES_MAX = 20
RULE_POINTS_MIN = 0
RULE_POINTS_MAX = 100
DEFAULT_IS_MANDATORY = False

# --------------------------------------------------------------------------
# Recipients (PRD §3.2)
# --------------------------------------------------------------------------
DEFAULT_COPIES = 1
MIN_COPIES = 1
DEFAULT_PAID_AMOUNT_CENTS = 0
MIN_PAID_AMOUNT_CENTS_FOR_PAID_CLASS = 1

# --------------------------------------------------------------------------
# Qualification scoring (PRD §3.4)
# --------------------------------------------------------------------------
QUALIFICATION_SCORE_THRESHOLD = 70
SCORE_MIN = 0
SCORE_MAX = 100

CHANNEL_BONUS = {
    "DIRECT_MAIL": 10,
    "WEB": 5,
    "EMAIL": 5,
    "TELEPHONE": 0,
}
CHANNEL_BONUS_MAX_SIGNATURE_AGE_MONTHS = 12
STALENESS_PENALTY_PER_MONTH = 5
STALENESS_PENALTY_GRACE_MONTHS = 12
STALENESS_PENALTY_CAP = 30

# --------------------------------------------------------------------------
# Qualification request review (PRD §3.3)
# --------------------------------------------------------------------------
INFO_REQUEST_LIMIT = 2
SUPERSEDED_DECISION_REASON = "SUPERSEDED_BY_NEWER_REQUEST"

# --------------------------------------------------------------------------
# Hygiene sweeps (PRD §3.5)
# --------------------------------------------------------------------------
DEFAULT_UNDELIVERABLE_THRESHOLD = 2
MIN_UNDELIVERABLE_THRESHOLD = 1

# --------------------------------------------------------------------------
# Digital audience snapshots (PRD §3.6)
# --------------------------------------------------------------------------
DEFAULT_OVERLAP_PCT = 15.00

# --------------------------------------------------------------------------
# Audit engagements and findings (PRD §3.8)
# --------------------------------------------------------------------------
FIELDWORK_SEPARATION_CLEAR_DAYS = 14

# --------------------------------------------------------------------------
# Advertiser contracts and make-goods (PRD §3.9)
# --------------------------------------------------------------------------
DEFAULT_SHORTFALL_TOLERANCE_PCT = 2.00
RESTATEMENT_CASCADE_REASON = "RESTATEMENT_REQUIRED_CASCADE"

# --------------------------------------------------------------------------
# Money / percentage comparison tolerance for floating point assertions
# --------------------------------------------------------------------------
PCT_TOLERANCE = 0.01
