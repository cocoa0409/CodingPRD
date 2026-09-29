"""Business constants for the Fair Trade Certification & Producer Premium Administration API.

Every value here is taken verbatim from the PRD. Nothing in this module performs
assertions; it is a pure vocabulary and constant table shared by factories,
assertions and the test suite.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

# "Until an operator sets it explicitly, the clock reads 2026-08-01T00:00:00Z."
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

ROLES = (
    "CertificationOfficer",
    "Auditor",
    "CommitteeChair",
    "CommitteeMember",
    "ProducerRepresentative",
    "BrandLicensee",
)

# ---------------------------------------------------------------------------
# Enumerations (PRD 3.x)
# ---------------------------------------------------------------------------

HOLDER_TYPES = ("PRODUCER_ORG", "PROCESSOR", "EXPORTER", "IMPORTER", "BRAND")
PRODUCT_CODES = ("COFFEE_ARABICA", "COCOA", "BANANA")
CERTIFICATE_STATUSES = ("PENDING", "CERTIFIED", "SUSPENDED", "TRANSITIONING", "DECERTIFIED")
SUSPENSION_REASONS = ("NONE", "NONCONFORMITY_ESCALATION", "VOLUME_VARIANCE", "MANUAL")
LABEL_LICENSE_STATUSES = ("NONE", "ACTIVE", "SUSPENDED", "TERMINATED")
LICENSE_TIERS = ("TIER_1", "TIER_2", "TIER_3")

NODE_ROLES = (
    "FARM",
    "COOPERATIVE",
    "PROCESSOR",
    "EXPORTER",
    "IMPORTER",
    "MANUFACTURER",
    "BRAND_NODE",
)
NODE_STATUSES = ("REGISTERED", "ACTIVE", "SUSPENDED", "RETIRED")
TRACEABILITY_MODES = ("PHYSICAL", "MASS_BALANCE")
CHAIN_MODES = ("ALL_PHYSICAL", "CONTAINS_MASS_BALANCE", "NO_CHAIN")

QUALITY_GRADES = ("STANDARD", "SPECIALTY")
VERIFICATION_STATUSES = ("UNVERIFIED", "VERIFIED", "DISPUTED", "REJECTED")
SETTLEMENT_STATUSES = ("PENDING", "SETTLED", "REVERSED")
PREMIUM_BASES = ("PHYSICAL_TRACEABILITY", "MASS_BALANCE")

COMMITTEE_STATUSES = ("FORMING", "ACTIVE", "RESTRICTED", "DISSOLVED")
USE_CATEGORIES = (
    "EDUCATION",
    "HEALTHCARE",
    "INFRASTRUCTURE",
    "PRODUCTIVITY_TOOLS",
    "WORKING_CAPITAL",
    "CASH_DISTRIBUTION",
)
PROPOSAL_STATUSES = (
    "DRAFT",
    "UNDER_VOTE",
    "REVISION_REQUESTED",
    "APPROVED",
    "REJECTED",
    "DISBURSED",
    "CANCELLED",
)
BALLOTS = ("APPROVE", "REJECT", "ABSTAIN")
ENTRY_TYPES = ("ACCRUAL", "REVERSAL", "COMMITMENT", "RELEASE", "DISBURSEMENT")

AUDIT_TYPES = ("INITIAL", "SURVEILLANCE", "FOLLOW_UP", "UNANNOUNCED")
AUDIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "REPORT_PENDING", "CLOSED", "CANCELLED")
NONCONFORMITY_GRADES = ("CRITICAL", "MAJOR", "MINOR", "OBSERVATION")
NONCONFORMITY_STATUSES = (
    "OPEN",
    "CAP_SUBMITTED",
    "CAP_REJECTED",
    "OVERDUE",
    "ESCALATED",
    "CLOSED",
)
OPEN_NONCONFORMITY_STATUSES = (
    "OPEN",
    "CAP_SUBMITTED",
    "CAP_REJECTED",
    "OVERDUE",
    "ESCALATED",
)

CLAIM_TYPES = ("FT_CERTIFIED_100", "FT_INGREDIENT_MASS_BALANCE")
MARK_REQUEST_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "WITHDRAWN")

RECONCILIATION_STATUSES = ("SUBMITTED", "MATCHED", "VARIANCE_FLAGGED")
RECONCILIATION_BASES = ("SELLER_BASIS", "BUYER_BASIS")

# ---------------------------------------------------------------------------
# The minimum price floor (PRD 3.3, step one)
# ---------------------------------------------------------------------------

# "320 cents per kilogram for COFFEE_ARABICA, 260 cents per kilogram for COCOA,
#  and 45 cents per kilogram for BANANA."
FLOOR_BASE_CENTS_PER_KG = {
    "COFFEE_ARABICA": 320,
    "COCOA": 260,
    "BANANA": 45,
}
# "an organic differential of 80 cents per kilogram"
ORGANIC_FLOOR_DIFFERENTIAL_CENTS_PER_KG = 80
# "nothing at all for STANDARD, and 40 cents per kilogram for SPECIALTY"
QUALITY_FLOOR_DIFFERENTIAL_CENTS_PER_KG = {"STANDARD": 0, "SPECIALTY": 40}

# ---------------------------------------------------------------------------
# The community development premium (PRD 3.3, step two)
# ---------------------------------------------------------------------------

# "80 cents per kilogram for COFFEE_ARABICA, 60 cents per kilogram for COCOA,
#  and 15 cents per kilogram for BANANA."
PREMIUM_BASE_CENTS_PER_KG = {
    "COFFEE_ARABICA": 80,
    "COCOA": 60,
    "BANANA": 15,
}
# "that base rate is multiplied by 1.25, a twenty-five percent uplift"
ORGANIC_PREMIUM_MULTIPLIER = "1.25"
# "a mass-balance attribution factor of 0.9725"
MASS_BALANCE_ATTRIBUTION_FACTOR = "0.9725"
# "The shipment is first decomposed into whole one-tonne lots"
MASS_BALANCE_LOT_KG = 1000

# ---------------------------------------------------------------------------
# Premium fund and committee thresholds (PRD 3.4, 3.5)
# ---------------------------------------------------------------------------

# "the fund's balance_cents has reached at least 1,000,000 cents"
COMMITTEE_ACTIVATION_THRESHOLD_CENTS = 1_000_000
# "a mutation leaves the fund's balance_cents strictly below 200,000 cents"
COMMITTEE_RESTRICTION_THRESHOLD_CENTS = 200_000
# "quorum_pct ... defaults to 60.00 when omitted"
DEFAULT_QUORUM_PCT = 60.00
# "if approval_pct is at least 66.67 - two thirds of the ballots cast"
APPROVAL_THRESHOLD_PCT = 66.67
# "must not exceed 80 percent of the fund's total_accrued_cents"
FUND_WINDOW_CAPACITY_PCT = 80
# "member_count of elected members - at least 3"
MIN_MEMBER_COUNT = 3

# ---------------------------------------------------------------------------
# Chain structure (PRD 3.1)
# ---------------------------------------------------------------------------

# "A certified chain may not run deeper than six hops from its origin"
MAX_CHAIN_DEPTH = 6
# "conversion_ratio ... defaults to 1.000 and must lie between 0.001 and 1.000"
DEFAULT_CONVERSION_RATIO = 1.000
MIN_CONVERSION_RATIO = 0.001
MAX_CONVERSION_RATIO = 1.000

# ---------------------------------------------------------------------------
# The label licence fee schedule (PRD 3.8)
# ---------------------------------------------------------------------------

LICENSE_TIER_1_CAP_KG = 100_000
LICENSE_TIER_2_CAP_KG = 500_000
LICENSE_TIER_1_RATE_CENTS_PER_KG = "1.20"
LICENSE_TIER_2_RATE_CENTS_PER_KG = "0.80"
LICENSE_TIER_3_RATE_CENTS_PER_KG = "0.45"
# "a flat base fee of 250,000 cents"
LICENSE_BASE_FEE_CENTS = 250_000
# "The administrative surcharge is 3.5 percent of that subtotal"
LICENSE_SURCHARGE_PCT = "3.5"

# ---------------------------------------------------------------------------
# Compliance scoring and corrective action deadlines (PRD 3.6)
# ---------------------------------------------------------------------------

# "100, reduced by 40 points for each open critical finding, 15 points for each
#  open major finding and 5 points for each open minor finding"
PERFECT_COMPLIANCE_SCORE = 100
SCORE_WEIGHTS = {"CRITICAL": 40, "MAJOR": 15, "MINOR": 5, "OBSERVATION": 0}
# "one week - 7 days - for a CRITICAL finding, 30 days for a MAJOR, 90 days for
#  a MINOR and 180 days for an OBSERVATION"
CAP_BASE_ALLOWANCE_DAYS = {"CRITICAL": 7, "MAJOR": 30, "MINOR": 90, "OBSERVATION": 180}
# "A score of at least 90 earns a deadline multiplier of 1.5 and an escalation
#  grace of 14 days ..."
DEADLINE_MULTIPLIER_HIGH = "1.5"
DEADLINE_MULTIPLIER_MID = "1.0"
DEADLINE_MULTIPLIER_LOW = "0.5"
GRACE_DAYS_HIGH = 14
GRACE_DAYS_MID = 7
GRACE_DAYS_LOW = 0
# "at least 90 earns a 24-month interval, at least 70 but below 90 earns 12
#  months, and below 70 earns 6 months"
AUDIT_INTERVAL_MONTHS_HIGH = 24
AUDIT_INTERVAL_MONTHS_MID = 12
AUDIT_INTERVAL_MONTHS_LOW = 6

# ---------------------------------------------------------------------------
# Audit scheduling windows (PRD 3.6)
# ---------------------------------------------------------------------------

# "The comparison widens the existing window by a three-day travel buffer"
AUDITOR_TRAVEL_BUFFER_DAYS = 3

# ---------------------------------------------------------------------------
# Certification transitions (PRD 3.2)
# ---------------------------------------------------------------------------

# "This stamps transition_deadline_at at 90 days after the clock"
SELL_DOWN_WINDOW_DAYS = 90
# "decision_reason set to the string HOLDER_SUSPENDED"
HOLDER_SUSPENDED_REASON = "HOLDER_SUSPENDED"

# ---------------------------------------------------------------------------
# Volume reconciliation tolerances (PRD 3.9)
# ---------------------------------------------------------------------------

# "When the absolute variance is at most 2.00 percent ... MATCHED"
VARIANCE_MATCH_TOLERANCE_PCT = 2.00
# "When the absolute variance is strictly greater than 10.00 percent"
VARIANCE_HARD_CAP_PCT = 10.00

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# Tolerances used by the test suite when comparing decimal-valued fields.
MONEY_ABS_TOLERANCE = 0.0
VOLUME_ABS_TOLERANCE = 0.0005
PCT_ABS_TOLERANCE = 0.005
