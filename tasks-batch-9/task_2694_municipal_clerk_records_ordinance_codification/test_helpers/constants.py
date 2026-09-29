"""Business constants declared by the Municipal Clerk Records & Ordinance
Codification PRD.

Every value here is transcribed from the PRD narrative (sections 2 and 3) so
that tests never re-derive a rule they are supposed to be checking.
"""

# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

API_PREFIX = "/clerk"

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

ROLE_CITY_CLERK = "CityClerk"
ROLE_DEPUTY_CLERK = "DeputyClerk"
ROLE_PRESIDING_OFFICER = "PresidingOfficer"
ROLE_RECORDS_OFFICER = "RecordsOfficer"
ROLE_CODIFICATION_EDITOR = "CodificationEditor"
ROLE_REQUESTER = "Requester"
ROLE_ANONYMOUS = "Anonymous"

STAFF_ROLES = (
    ROLE_CITY_CLERK,
    ROLE_DEPUTY_CLERK,
    ROLE_PRESIDING_OFFICER,
    ROLE_RECORDS_OFFICER,
    ROLE_CODIFICATION_EDITOR,
)

ALL_ROLES = STAFF_ROLES + (ROLE_REQUESTER, ROLE_ANONYMOUS)

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Venue (PRD 3.1)
# ---------------------------------------------------------------------------

DEFAULT_TEARDOWN_BUFFER_MINUTES = 30
MIN_TEARDOWN_BUFFER_MINUTES = 0
MAX_TEARDOWN_BUFFER_MINUTES = 240

VENUE_STATUS_AVAILABLE = "AVAILABLE"
VENUE_STATUS_CLOSED = "CLOSED"

# ---------------------------------------------------------------------------
# Meeting (PRD 3.1)
# ---------------------------------------------------------------------------

BODY_TYPES = ("COUNCIL", "PLANNING_COMMISSION", "BOARD_OF_ADJUSTMENT")
MEETING_TYPES = ("REGULAR", "SPECIAL", "EMERGENCY", "WORKSHOP")

MEETING_SCHEDULED = "SCHEDULED"
MEETING_NOTICED = "NOTICED"
MEETING_IN_SESSION = "IN_SESSION"
MEETING_ADJOURNED = "ADJOURNED"
MEETING_CANCELLED = "CANCELLED"

# Venue occupation blocks these meeting statuses (PRD 3.1).
VENUE_BLOCKING_MEETING_STATUSES = (MEETING_SCHEDULED, MEETING_NOTICED, MEETING_IN_SESSION)

# ---------------------------------------------------------------------------
# Agenda packet / notice arithmetic (PRD 3.2)
# ---------------------------------------------------------------------------

PACKET_DRAFT = "DRAFT"
PACKET_POSTED = "POSTED"
PACKET_SUPERSEDED = "SUPERSEDED"
PACKET_WITHDRAWN = "WITHDRAWN"

MAX_PACKET_REVISIONS = 3

BASE_NOTICE_HOURS = {
    "REGULAR": 72,
    "SPECIAL": 48,
    "WORKSHOP": 48,
    "EMERGENCY": 24,
}

PUBLIC_HEARING_ADDITIONAL_HOURS = 168
LATE_ADDENDUM_ADDITIONAL_HOURS = 24

BODY_MULTIPLIER = {
    "COUNCIL": 1.0,
    "PLANNING_COMMISSION": 1.5,
    "BOARD_OF_ADJUSTMENT": 1.5,
}

ITEM_TYPES = (
    "CONSENT",
    "PUBLIC_HEARING",
    "ORDINANCE_FIRST_READING",
    "ORDINANCE_ADOPTION",
    "RESOLUTION",
    "MINUTES",
    "REPORT",
)

# ---------------------------------------------------------------------------
# Motions and the vote arithmetic (PRD 3.3)
# ---------------------------------------------------------------------------

MOTION_SECONDED = "SECONDED"
MOTION_TALLIED = "TALLIED"
MOTION_WITHDRAWN = "WITHDRAWN"

OUTCOME_PENDING = "PENDING"
OUTCOME_PASSED = "PASSED"
OUTCOME_FAILED = "FAILED"
OUTCOME_TIE_BROKEN_PASSED = "TIE_BROKEN_PASSED"
OUTCOME_TIE_BROKEN_FAILED = "TIE_BROKEN_FAILED"

MOTION_TYPES = (
    "ORDINANCE_ADOPTION",
    "RESOLUTION_ADOPTION",
    "VETO_OVERRIDE",
    "MINUTES_APPROVAL",
    "MINUTES_CORRECTION",
    "PROCEDURAL",
)

MAJORITY_RULES = ("SIMPLE", "TWO_THIRDS", "FOUR_FIFTHS", "UNANIMOUS_CONSENT")

# ---------------------------------------------------------------------------
# Minutes (PRD 3.4)
# ---------------------------------------------------------------------------

MINUTES_DRAFT = "DRAFT"
MINUTES_SUBMITTED = "SUBMITTED"
MINUTES_APPROVED = "APPROVED"
MINUTES_CORRECTION_PENDING = "CORRECTION_PENDING"

# ---------------------------------------------------------------------------
# Numbering series and instruments (PRD 3.5)
# ---------------------------------------------------------------------------

SERIES_OPEN = "OPEN"
SERIES_CLOSED = "CLOSED"

INSTRUMENT_CLASSES = ("ORDINANCE", "RESOLUTION")
ORDINANCE_CATEGORIES = ("GENERAL", "ZONING", "CODE_AMENDMENT", "EMERGENCY")

INSTRUMENT_INTRODUCED = "INTRODUCED"
INSTRUMENT_FIRST_READING_PASSED = "FIRST_READING_PASSED"
INSTRUMENT_ADOPTED_UNOFFICIAL = "ADOPTED_UNOFFICIAL"
INSTRUMENT_ADOPTED = "ADOPTED"
INSTRUMENT_VETOED = "VETOED"
INSTRUMENT_VETO_OVERRIDDEN = "VETO_OVERRIDDEN"
INSTRUMENT_PUBLISHED = "PUBLISHED"
INSTRUMENT_EFFECTIVE = "EFFECTIVE"
INSTRUMENT_FAILED = "FAILED"

# Minted numbers are prefix-year-sequence with the sequence zero padded to
# three digits (PRD 3.5).
NUMBER_SEQUENCE_PAD = 3
MAX_NUMBER_SEQUENCE = 999

EFFECTIVE_BASIS_ADOPTION_IMMEDIATE = "ADOPTION_IMMEDIATE"
EFFECTIVE_BASIS_PUBLICATION_PLUS_30 = "PUBLICATION_PLUS_30"
EFFECTIVE_BASIS_SUPPLEMENT_CERTIFIED = "SUPPLEMENT_CERTIFIED"

PUBLICATION_EFFECTIVE_DELAY_DAYS = 30

# ---------------------------------------------------------------------------
# Publication notices (PRD 3.6)
# ---------------------------------------------------------------------------

NOTICE_DRAFT = "DRAFT"
NOTICE_ORDERED = "ORDERED"
NOTICE_PUBLISHED = "PUBLISHED"
NOTICE_VOID = "VOID"

NOTICE_TYPE_ORDINANCE_SUMMARY = "ORDINANCE_SUMMARY"
NOTICE_TYPE_ORDINANCE_FULL_TEXT = "ORDINANCE_FULL_TEXT"
NOTICE_TYPE_MEETING_AGENDA = "MEETING_AGENDA"
NOTICE_TYPE_CANCELLATION = "CANCELLATION"
NOTICE_TYPE_REPLACEMENT = "REPLACEMENT"

# A full-text run needs two insertions, a summary run one (PRD 3.6).
SUMMARY_TEXT_LENGTH_THRESHOLD = 4000
FULL_TEXT_INSERTIONS = 2
SUMMARY_INSERTIONS = 1
MEETING_NOTICE_INSERTIONS = 1

PUBLICATION_DEADLINE_DAYS = 15
MEETING_AGENDA_DEADLINE_LEAD_DAYS = 1
MIN_PUBLICATION_INTERVAL_DAYS = 7

COLUMN_INCH_RATE_CENTS = 500
AFFIDAVIT_FEE_CENTS = 2500

# Volume discount tiers keyed on the gross cost (PRD 3.6).
DISCOUNT_TIER_MID_FLOOR_CENTS = 50000
DISCOUNT_TIER_HIGH_FLOOR_CENTS = 150000
DISCOUNT_PCT_LOW = 0.00
DISCOUNT_PCT_MID = 0.05
DISCOUNT_PCT_HIGH = 0.10

# ---------------------------------------------------------------------------
# Codification (PRD 3.7)
# ---------------------------------------------------------------------------

CODE_TITLE_ACTIVE = "ACTIVE"
CODE_TITLE_RESERVED = "RESERVED"

CYCLE_OPEN = "OPEN"
CYCLE_LOCKED = "LOCKED"
CYCLE_CERTIFIED = "CERTIFIED"

SUBMISSION_PENDING = "PENDING"
SUBMISSION_IN_REVIEW = "IN_REVIEW"
SUBMISSION_CONFLICT_HELD = "CONFLICT_HELD"
SUBMISSION_ACCEPTED = "ACCEPTED"
SUBMISSION_REJECTED = "REJECTED"
SUBMISSION_WITHDRAWN = "WITHDRAWN"

SUBMISSION_ORIGIN_CLIENT = "CLIENT"
SUBMISSION_ORIGIN_CASCADE = "CASCADE"

SUBMISSION_ACTIONS = ("ADD", "AMEND", "REPEAL")

MAX_CLIENT_SUBMISSIONS_PER_CYCLE = 3

RESOLUTION_BASIS_LATER_ADOPTION_WINS = "LATER_ADOPTION_WINS"
RESOLUTION_BASIS_SPECIFIC_OVER_GENERAL = "SPECIFIC_OVER_GENERAL"
RESOLUTION_BASIS_MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

# Specificity ladder used by SPECIFIC_OVER_GENERAL (PRD 3.7).
SPECIFICITY_RANK = {
    "ZONING": 0,
    "CODE_AMENDMENT": 1,
    "GENERAL": 2,
    "EMERGENCY": 3,
}

# ---------------------------------------------------------------------------
# Public records requests (PRD 3.8)
# ---------------------------------------------------------------------------

FULFILLMENT_RECEIVED = "RECEIVED"
FULFILLMENT_UNDER_REVIEW = "UNDER_REVIEW"
FULFILLMENT_EXEMPTION_REVIEW = "EXEMPTION_REVIEW"
FULFILLMENT_RELEASED = "RELEASED"
FULFILLMENT_PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
FULFILLMENT_DENIED = "DENIED"
FULFILLMENT_CLOSED = "CLOSED"
FULFILLMENT_WITHDRAWN = "WITHDRAWN"

FEE_NOT_ASSESSED = "NOT_ASSESSED"
FEE_ASSESSED = "ASSESSED"
FEE_DEPOSIT_HELD = "DEPOSIT_HELD"
FEE_PAID = "PAID"
FEE_WAIVED = "WAIVED"
FEE_REFUNDED = "REFUNDED"

DISPOSITION_FULL_RELEASE = "FULL_RELEASE"
DISPOSITION_PARTIAL_RELEASE = "PARTIAL_RELEASE"
DISPOSITION_DENIAL = "DENIAL"

FEE_VARIANT_ACTUAL_COST = "ACTUAL_COST"
FEE_VARIANT_FLAT_SCHEDULE = "FLAT_SCHEDULE"

DELIVERY_MEDIUM_PAPER = "PAPER"
DELIVERY_MEDIUM_ELECTRONIC = "ELECTRONIC"

RESPONSE_DEADLINE_BUSINESS_DAYS = 5

FREE_PAGE_ALLOWANCE = 20
ACTUAL_COST_PAGE_RATE_CENTS = 15
FLAT_SCHEDULE_PAGE_RATE_CENTS = 25
STAFF_MINUTES_PER_QUARTER_HOUR = 15
FREE_STAFF_QUARTER_HOURS = 2
STAFF_QUARTER_HOUR_RATE_CENTS = 875
COMMERCIAL_SURCHARGE_MULTIPLIER = 1.20

# ---------------------------------------------------------------------------
# Retention, custody and destruction (PRD 3.9)
# ---------------------------------------------------------------------------

RETENTION_TRIGGERS = ("CREATION", "FISCAL_YEAR_END", "REQUEST_CLOSURE")

LEGAL_HOLD_NONE = "NONE"
LEGAL_HOLD_LITIGATION = "LITIGATION_HOLD"
LEGAL_HOLD_AUDIT = "AUDIT_HOLD"

MIN_RETENTION_YEARS = 0
MAX_RETENTION_YEARS = 100

BATCH_PROPOSED = "PROPOSED"
BATCH_CERTIFIED = "CERTIFIED"
BATCH_RESCINDED = "RESCINDED"

# The fiscal year closes on 30 June (PRD 3.9).
FISCAL_YEAR_END_MONTH = 6
FISCAL_YEAR_END_DAY = 30

# ---------------------------------------------------------------------------
# Common fields (PRD 2.5)
# ---------------------------------------------------------------------------

# AgendaItem is the one entity that carries only id and created_at.
ENTITIES_WITHOUT_VERSION = ("AgendaItem",)

INITIAL_VERSION = 1
