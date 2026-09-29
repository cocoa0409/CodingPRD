"""Business constants and enumerations declared by the PRD.

Everything here is transcribed from the contract: the logical clock origin, the
pagination defaults, the discount and penalty tables, the depth multipliers, and
the state / status vocabularies of every entity.
"""

from decimal import Decimal

# ---------------------------------------------------------------------------
# The logical adoption clock
# ---------------------------------------------------------------------------

#: Reading of the logical clock before any operator has set it.
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_STATE_ADOPTION_OFFICER = "StateAdoptionOfficer"
ROLE_REVIEW_COMMITTEE_MEMBER = "ReviewCommitteeMember"
ROLE_PUBLISHER_EDITOR = "PublisherEditor"
ROLE_EDITORIAL_DIRECTOR = "EditorialDirector"
ROLE_PRICING_MANAGER = "PricingManager"
ROLE_SALES_REP = "SalesRep"
ROLE_PUBLIC_COMMENTER = "PublicCommenter"


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

ADOPTION_MODEL_ADOPTION_LIST = "ADOPTION_LIST"
ADOPTION_MODEL_OPEN_TERRITORY = "OPEN_TERRITORY"

CYCLE_STATUS_SCHEDULED = "SCHEDULED"
CYCLE_STATUS_OPEN = "OPEN"
CYCLE_STATUS_CLOSED_FOR_SUBMISSION = "CLOSED_FOR_SUBMISSION"
CYCLE_STATUS_IN_REVIEW = "IN_REVIEW"
CYCLE_STATUS_PUBLIC_COMMENT = "PUBLIC_COMMENT"
CYCLE_STATUS_DECIDED = "DECIDED"
CYCLE_STATUS_ARCHIVED = "ARCHIVED"

#: The seven cycle phases in the order the calendar walks them.
CYCLE_PHASE_ORDER = (
    CYCLE_STATUS_SCHEDULED,
    CYCLE_STATUS_OPEN,
    CYCLE_STATUS_CLOSED_FOR_SUBMISSION,
    CYCLE_STATUS_IN_REVIEW,
    CYCLE_STATUS_PUBLIC_COMMENT,
    CYCLE_STATUS_DECIDED,
    CYCLE_STATUS_ARCHIVED,
)

TITLE_STATUS_DRAFT = "DRAFT"
TITLE_STATUS_ACTIVE = "ACTIVE"
TITLE_STATUS_REVISION_PLANNED = "REVISION_PLANNED"
TITLE_STATUS_SUNSET = "SUNSET"

REVIEW_STATUS_DRAFT = "DRAFT"
REVIEW_STATUS_FILED = "FILED"
REVIEW_STATUS_SCHEDULED = "SCHEDULED"
REVIEW_STATUS_PRESENTED = "PRESENTED"
REVIEW_STATUS_ADOPTED = "ADOPTED"
REVIEW_STATUS_NOT_ADOPTED = "NOT_ADOPTED"
REVIEW_STATUS_WITHDRAWN = "WITHDRAWN"

PRICING_STATUS_UNPRICED = "UNPRICED"
PRICING_STATUS_PRICE_FILED = "PRICE_FILED"
PRICING_STATUS_PRICE_APPROVED = "PRICE_APPROVED"
PRICING_STATUS_PRICE_REJECTED = "PRICE_REJECTED"

SAMPLING_STATUS_NOT_REQUIRED = "NOT_REQUIRED"
SAMPLING_STATUS_PENDING = "PENDING"
SAMPLING_STATUS_PARTIAL = "PARTIAL"
SAMPLING_STATUS_SHIPPED = "SHIPPED"

CONTENT_EDIT_STATUS_PROPOSED = "PROPOSED"
CONTENT_EDIT_STATUS_APPROVED = "APPROVED"
CONTENT_EDIT_STATUS_REJECTED = "REJECTED"
CONTENT_EDIT_STATUS_APPLIED = "APPLIED"
CONTENT_EDIT_STATUS_REVERTED = "REVERTED"

EDIT_TYPE_ADD_REQUIRED_TOPIC = "ADD_REQUIRED_TOPIC"
EDIT_TYPE_REMOVE_PROHIBITED_TAG = "REMOVE_PROHIBITED_TAG"
EDIT_TYPE_REGIONAL_SUBSTITUTION = "REGIONAL_SUBSTITUTION"

PANEL_STATUS_SCHEDULED = "SCHEDULED"
PANEL_STATUS_IN_SESSION = "IN_SESSION"
PANEL_STATUS_CLOSED = "CLOSED"

SLOT_STATUS_RESERVED = "RESERVED"
SLOT_STATUS_PRESENTED = "PRESENTED"
SLOT_STATUS_TALLIED = "TALLIED"
SLOT_STATUS_CANCELLED = "CANCELLED"
SLOT_STATUS_NO_SHOW = "NO_SHOW"

TALLY_OUTCOME_PENDING = "PENDING"
TALLY_OUTCOME_RECOMMEND = "RECOMMEND"
TALLY_OUTCOME_RECOMMEND_WITH_CONDITIONS = "RECOMMEND_WITH_CONDITIONS"
TALLY_OUTCOME_REJECT = "REJECT"

VOTE_RECOMMEND = "RECOMMEND"
VOTE_RECOMMEND_WITH_CONDITIONS = "RECOMMEND_WITH_CONDITIONS"
VOTE_REJECT = "REJECT"
VOTE_ABSTAIN = "ABSTAIN"

DEPTH_MENTION = "MENTION"
DEPTH_PRACTICE = "PRACTICE"
DEPTH_MASTERY = "MASTERY"

VERDICT_PENDING = "PENDING"
VERDICT_ACCEPTED = "ACCEPTED"
VERDICT_REJECTED = "REJECTED"

COMMENT_STATUS_OPEN = "OPEN"
COMMENT_STATUS_ESCALATED = "ESCALATED"
COMMENT_STATUS_RESPONDED = "RESPONDED"

COMMENT_CATEGORY_ERROR_OF_FACT = "ERROR_OF_FACT"
COMMENT_CATEGORY_BIAS_CONCERN = "BIAS_CONCERN"
COMMENT_CATEGORY_PROHIBITED_CONTENT = "PROHIBITED_CONTENT"
COMMENT_CATEGORY_OTHER = "OTHER"

SEVERITY_MINOR = "MINOR"
SEVERITY_MAJOR = "MAJOR"
SEVERITY_CRITICAL = "CRITICAL"

PROPOSAL_STATUS_FILED = "FILED"
PROPOSAL_STATUS_APPROVED = "APPROVED"
PROPOSAL_STATUS_REJECTED = "REJECTED"
PROPOSAL_STATUS_SUPERSEDED = "SUPERSEDED"

ORDER_STATUS_QUOTED = "QUOTED"
ORDER_STATUS_CONFIRMED = "CONFIRMED"
ORDER_STATUS_FULFILLED = "FULFILLED"
ORDER_STATUS_CANCELLED = "CANCELLED"

ACCESSIBILITY_NONE = "NONE"
ACCESSIBILITY_WCAG_2_1_AA = "WCAG_2_1_AA"
ACCESSIBILITY_WCAG_2_2_AA = "WCAG_2_2_AA"

#: Accessibility conformance is a ranked ladder; a bundle satisfies a state when
#: its rank is at least the state's requirement.
ACCESSIBILITY_RANK = {
    ACCESSIBILITY_NONE: 0,
    ACCESSIBILITY_WCAG_2_1_AA: 1,
    ACCESSIBILITY_WCAG_2_2_AA: 2,
}

ROSTERING_ONEROSTER_1_1 = "ONEROSTER_1_1"
ROSTERING_ONEROSTER_1_2 = "ONEROSTER_1_2"
ROSTERING_CSV_MANUAL = "CSV_MANUAL"

INVENTORY_RECEIPT = "RECEIPT"
INVENTORY_WRITE_OFF = "WRITE_OFF"

REVISION_PLAN_PLAN = "PLAN"
REVISION_PLAN_CANCEL_PLAN = "CANCEL_PLAN"
REVISION_PLAN_SUNSET = "SUNSET"

WITHDRAW_REASON_REVISE = "REVISE"
WITHDRAW_REASON_ABANDON = "ABANDON"


# ---------------------------------------------------------------------------
# Correlation coverage
# ---------------------------------------------------------------------------

DEPTH_MULTIPLIERS = {
    DEPTH_MENTION: Decimal("0.40"),
    DEPTH_PRACTICE: Decimal("0.70"),
    DEPTH_MASTERY: Decimal("1.00"),
}


# ---------------------------------------------------------------------------
# State net price
# ---------------------------------------------------------------------------

#: projected_adoption_units floor -> volume discount fraction.
VOLUME_TIERS = ((20000, Decimal("0.12")), (5000, Decimal("0.07")), (0, Decimal("0.00")))

#: term_years floor -> term discount fraction.
TERM_TIERS = ((5, Decimal("0.06")), (3, Decimal("0.03")), (1, Decimal("0.00")))

#: bundle component_count floor -> bundle discount fraction.
BUNDLE_TIERS = ((4, Decimal("0.09")), (2, Decimal("0.05")), (1, Decimal("0.00")))

MAX_TOTAL_DISCOUNT_PCT = Decimal("0.20")


# ---------------------------------------------------------------------------
# Order total value
# ---------------------------------------------------------------------------

FREIGHT_WAIVER_THRESHOLD_CENTS = 2500000
FREIGHT_RATE = Decimal("0.015")
ADOPTED_LIST_REBATE_PCT = Decimal("0.02")
DEFAULT_OPEN_TERRITORY_SEAT_CENTS = 1200


# ---------------------------------------------------------------------------
# Committee tally
# ---------------------------------------------------------------------------

CONDITIONS_WEIGHT = Decimal("0.5")
RECOMMEND_RATIO_THRESHOLD = Decimal("0.6667")


# ---------------------------------------------------------------------------
# Public comment response obligation
# ---------------------------------------------------------------------------

SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Compliance score
# ---------------------------------------------------------------------------

PENALTY_PROHIBITED = 25
PENALTY_MISSING_TOPIC = 10
PENALTY_CRITICAL = 15
PENALTY_OVERDUE = 5
BLOCK_THRESHOLD = 70


# ---------------------------------------------------------------------------
# Workflow ceilings
# ---------------------------------------------------------------------------

MAX_REVISION_ROUNDS = 3
ARCHIVE_DELAY_DAYS = 30


# ---------------------------------------------------------------------------
# Stale-version field names
# ---------------------------------------------------------------------------

EXPECTED_SUBMISSION_VERSION = "expected_submission_version"
EXPECTED_PANEL_VERSION = "expected_panel_version"


# ---------------------------------------------------------------------------
# Common field sets
# ---------------------------------------------------------------------------

#: Fields every resource carries.
BASE_IDENTITY_FIELDS = ("id", "created_at")

#: Fields every mutable resource additionally carries.
MUTABLE_RECORD_FIELDS = ("updated_at", "version")

#: Append-only resources: only the base identity fields are present.
APPEND_ONLY_ENTITIES = ("StateStandard", "CommitteeVote")
