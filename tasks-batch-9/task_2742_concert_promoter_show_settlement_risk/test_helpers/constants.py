"""Domain constants for the concert promoter show settlement and risk service.

Every value here is stated explicitly in the PRD. Nothing is inferred.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# The service clock starts at exactly this instant and never falls back to
# wall-clock time.
DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK_BARE = "2026-08-01T00:00:00Z"

CLOCK_SET_PATH = "/_clock/set_current_utc"
HOUSEKEEPING_PATH = "/_ops/run"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_TALENT_BUYER = "TalentBuyer"
ROLE_ARTIST_REP = "ArtistRep"
ROLE_VENUE_OPERATOR = "VenueOperator"
ROLE_TOUR_ACCOUNTANT = "TourAccountant"
ROLE_RISK_OFFICER = "RiskOfficer"

ALL_ROLES = [
    ROLE_TALENT_BUYER,
    ROLE_ARTIST_REP,
    ROLE_VENUE_OPERATOR,
    ROLE_TOUR_ACCOUNTANT,
    ROLE_RISK_OFFICER,
]

# The two roles whose X-User-ID must equal a specific resource id.
ENTITY_BACKED_ROLES = [ROLE_ARTIST_REP, ROLE_VENUE_OPERATOR]

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Money and percentage handling
# ---------------------------------------------------------------------------

MONEY_DECIMALS = 0  # all money is integer cents
PERCENT_DECIMALS = 2

# ---------------------------------------------------------------------------
# Receipts waterfall
# ---------------------------------------------------------------------------

# A card-processing charge of 2.5 percent, applied post-ticket-tax but before
# the facility fee is taken out.
CREDIT_CARD_FEE_PCT = 2.50

# ---------------------------------------------------------------------------
# Budget variance banding
# ---------------------------------------------------------------------------

# At most 10.00 percent leaves the line WITHIN_TOLERANCE.
VARIANCE_TOLERANCE_PCT = 10.00
# Above 10.00 and at most 25.00 needs a TourAccountant; above 25.00 needs a
# RiskOfficer.
VARIANCE_ESCALATION_PCT = 25.00

# ---------------------------------------------------------------------------
# Comp allowance
# ---------------------------------------------------------------------------

# 3 percent of the show's total allocation across every tier, DRAFT included,
# rounded half up to whole tickets.
COMP_ALLOWANCE_PCT = 3.00

# ---------------------------------------------------------------------------
# Marketing co-op contribution
# ---------------------------------------------------------------------------

# Share leg: half of recognised marketing expense.
COOP_SHARE_PCT = 50.00
# Cap leg: 5 percent of artist_base_earnings_cents.
COOP_CAP_PCT_OF_BASE = 5.00

# ---------------------------------------------------------------------------
# Market risk posture bands (read against the ROUNDED utilisation percentage)
# ---------------------------------------------------------------------------

POSTURE_OPEN_MAX_PCT = 70.00       # <= 70.00 is OPEN
POSTURE_WATCH_MAX_PCT = 90.00      # > 70.00 and <= 90.00 is WATCH
POSTURE_RESTRICTED_MAX_PCT = 100.00  # > 90.00 and < 100.00 is RESTRICTED
                                     # >= 100.00 is FROZEN

# The show-scoped exposure override may not exceed twice the market limit.
EXPOSURE_OVERRIDE_MAX_MULTIPLE = 2

# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------

INSURANCE_POLICY_CAP_CENTS = 25_000_000
INSURANCE_DEDUCTIBLE_CENTS = 500_000
INSURANCE_CLAIM_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Routing, negotiation and offer expiry
# ---------------------------------------------------------------------------

# Absolute distance between two event_at instants of the same act.
ARTIST_REST_BUFFER_HOURS = 36
# submit / re-submit sets expires_at exactly this far out.
OFFER_TTL_HOURS = 72
# Neither a counter nor a re-submission may proceed once round_index is 3.
NEGOTIATION_ROUND_LIMIT = 3

# ---------------------------------------------------------------------------
# Settlement payment
# ---------------------------------------------------------------------------

# With payment_method CASH the settlement's payment_due_cents may not exceed
# 1,000,000 cents.
CASH_PAYMENT_LIMIT_CENTS = 1_000_000

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

RISK_POSTURES = ["OPEN", "WATCH", "RESTRICTED", "FROZEN"]
ARTIST_TIERS = ["CLUB", "THEATER", "ARENA", "HEADLINE"]
SHOW_STATUSES = [
    "PLANNED",
    "CONFIRMED",
    "ON_SALE",
    "PERFORMED",
    "SETTLED",
    "CANCELLED",
    "POSTPONED",
    "RESCHEDULED",
]
SALES_STATUSES = ["PRE_SALE", "SELLING", "PAUSED", "CLOSED"]
VENUE_ARRANGEMENTS = ["RENTAL", "CO_PROMOTE"]
BUDGET_POSTURES = ["ON_BUDGET", "VARIANCE_PENDING", "OVER_BUDGET"]
DEAL_STRUCTURES = ["FLAT_GUARANTEE", "VERSUS", "GUARANTEE_PLUS_BACKEND"]
OFFER_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "COUNTERED",
    "ACCEPTED",
    "WITHDRAWN",
    "SUPERSEDED",
    "EXPIRED",
]
BUDGET_CATEGORIES = ["PRODUCTION", "MARKETING", "STAFFING", "HOSPITALITY"]
VARIANCE_STATUSES = [
    "WITHIN_TOLERANCE",
    "PENDING_APPROVAL",
    "APPROVED",
    "REJECTED",
]
REQUIRED_APPROVER_ROLES = ["NONE", "TOUR_ACCOUNTANT", "RISK_OFFICER"]
BUDGET_LINE_STATUSES = ["ACTIVE", "SETTLED", "VOID"]
VENDOR_INVOICE_STATUSES = [
    "SUBMITTED",
    "VERIFIED",
    "APPROVED",
    "DISPUTED",
    "REJECTED",
]
TICKET_TIER_STATUSES = ["DRAFT", "ON_SALE", "PAUSED", "CLOSED"]
HOLD_KINDS = ["COMP", "ARTIST_HOLD", "PRODUCTION_HOLD", "PROMOTER_HOLD"]
HOLD_STATUSES = ["HELD", "RELEASED", "CONVERTED", "EXPIRED"]
SETTLEMENT_STATUSES = [
    "DRAFT",
    "CALCULATED",
    "ARTIST_SIGNED",
    "PAID",
    "DISPUTED",
    "REOPENED",
]
PAYMENT_METHODS = ["WIRE", "CHECK", "CASH"]
CANCELLATION_KINDS = ["CANCELLED", "POSTPONED"]
CANCELLATION_STATUSES = [
    "OPENED",
    "REFUNDS_PROCESSED",
    "CLAIM_FILED",
    "CLAIM_SETTLED",
    "CLAIM_DENIED",
    "RESCHEDULED",
]
VALUATIONS = ["TRAILING_SETTLED", "MARK_TO_MARKET"]

# ---------------------------------------------------------------------------
# Fields shared by every resource
# ---------------------------------------------------------------------------

COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
PAGINATION_META_FIELDS = ["limit", "offset", "total_count", "has_more"]
