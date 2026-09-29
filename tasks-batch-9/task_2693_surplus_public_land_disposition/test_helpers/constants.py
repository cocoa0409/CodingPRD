"""Domain thresholds and named constants for the Surplus Public Land Disposition API.

Every value here is declared by the specification; tests reference these names
instead of repeating literals.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: Before any call to the clock endpoint the logical clock reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

#: One day is exactly 86400 seconds for every interval computation.
SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Appraisal
# ---------------------------------------------------------------------------

#: expires_on is the effective_date plus this many whole days.
APPRAISAL_VALIDITY_DAYS = 365

#: Hard limit on concurrent intersecting engagement intervals per appraiser.
APPRAISER_MAX_CONCURRENT_ENGAGEMENTS = 2

APPRAISAL_METHODS = ("SALES_COMPARISON", "INCOME", "COST")

# ---------------------------------------------------------------------------
# Appraisal challenge
# ---------------------------------------------------------------------------

#: The challenge window runs this many days from reported_at, inclusive.
CHALLENGE_WINDOW_DAYS = 30

#: The asserted value must differ from the appraised value by at least this share.
CHALLENGE_DELTA_MIN_FRACTION = 0.05

#: The statutory challenge deposit is this share of the appraised value.
CHALLENGE_DEPOSIT_FRACTION = 0.01

#: ... clamped into this inclusive range.
CHALLENGE_DEPOSIT_FLOOR_CENTS = 100000
CHALLENGE_DEPOSIT_CEILING_CENTS = 2500000

#: A denied challenge forfeits its deposit under this allocation basis.
ALLOCATION_BASIS_CHALLENGE_FORFEITURE = "CHALLENGE_FORFEITURE"

# ---------------------------------------------------------------------------
# Statutory notice
# ---------------------------------------------------------------------------

NOTICE_WINDOW_DEFAULT_DAYS = 60
NOTICE_WINDOW_MIN_DAYS = 60
NOTICE_WINDOW_MAX_DAYS = 90
NOTICE_RECIPIENTS_MIN = 1
NOTICE_RECIPIENTS_MAX = 20

# ---------------------------------------------------------------------------
# Preference negotiation
# ---------------------------------------------------------------------------

#: The negotiation deadline is this many days after the offer opened.
NEGOTIATION_WINDOW_DAYS = 90

#: A round answered within this many whole days is timely.
TIMELY_RESPONSE_MAX_DAYS = 15

# ---------------------------------------------------------------------------
# Good-faith score
# ---------------------------------------------------------------------------

GOOD_FAITH_PASS_SCORE = 70
GOOD_FAITH_ENGAGEMENT_POINTS = 45
GOOD_FAITH_TIMELINESS_POINTS = 30
GOOD_FAITH_CONCESSION_NEAR_POINTS = 25
GOOD_FAITH_CONCESSION_WIDE_POINTS = 12
GOOD_FAITH_ROUND_TARGET = 3
PREMATURE_IMPASSE_PENALTY = 15
INTERIM_SCORE_CAP = 75
CONCESSION_NEAR_BAND_MULTIPLIER = 1.05
CONCESSION_WIDE_BAND_MULTIPLIER = 1.20

#: An AGREED conclusion needs at least this many custodian-agency rounds.
GOOD_FAITH_MIN_CUSTODIAN_ROUNDS = 3

# ---------------------------------------------------------------------------
# Minimum price
# ---------------------------------------------------------------------------

#: Write-down applied under the affordable-housing preference variant.
AFFORDABLE_HOUSING_WRITE_DOWN = 0.35

#: Each completed re-offer cycle discounts by this share ...
REOFFER_DISCOUNT_PER_CYCLE = 0.10

#: ... capped at this share.
REOFFER_DISCOUNT_CAP = 0.20

MINIMUM_PRICE_VARIANT_MARKET_FLOOR = "MARKET_FLOOR"
MINIMUM_PRICE_VARIANT_AFFORDABLE_HOUSING = "AFFORDABLE_HOUSING_PREFERENCE"

# ---------------------------------------------------------------------------
# Re-offering
# ---------------------------------------------------------------------------

#: A failed disposition arms the re-offer clock this many days out.
REOFFER_COOLING_OFF_DAYS = 30

#: reoffer_count must be strictly below this to re-offer again.
REOFFER_LIMIT = 2

# ---------------------------------------------------------------------------
# Environmental review
# ---------------------------------------------------------------------------

#: A non-exempt circulation window must span at least this many whole days.
MIN_CIRCULATION_DAYS = 30

#: A recirculation must start at least this many days after the prior window ended.
RECIRCULATION_BUFFER_DAYS = 30

ENV_DETERMINATION_CLASSES = (
    "EXEMPT",
    "NEGATIVE_DECLARATION",
    "MITIGATED_NEG_DEC",
    "FULL_EIR",
)

# ---------------------------------------------------------------------------
# Offering and bidding
# ---------------------------------------------------------------------------

#: The required bid deposit is this share of the frozen minimum price ...
BID_DEPOSIT_FRACTION = 0.05

#: ... but never less than this floor.
BID_DEPOSIT_FLOOR_CENTS = 5000000

DISPOSITION_TYPES = ("COMPETITIVE_SALE", "NEGOTIATED_SALE", "EXCHANGE")

# ---------------------------------------------------------------------------
# Conveyance
# ---------------------------------------------------------------------------

#: Curative cost recovery is capped at this share of the provisional net proceeds.
CURATIVE_RECOVERY_CAP_FRACTION = 0.15

REVERTER_CURE_PERIOD_DEFAULT_DAYS = 180
REVERTER_CURE_PERIOD_MIN_DAYS = 30
REVERTER_CURE_PERIOD_MAX_DAYS = 730

DEED_RESTRICTIONS_MIN = 1
DEED_RESTRICTIONS_MAX = 10

# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

AGENCY_TYPES = (
    "STATE",
    "COUNTY",
    "MUNICIPAL",
    "SCHOOL_DISTRICT",
    "TRANSIT",
    "HOUSING_AUTHORITY",
    "FEDERAL",
)

PREFERENCE_CATEGORIES = (
    "AFFORDABLE_HOUSING",
    "PARK_OPEN_SPACE",
    "SCHOOL_SITE",
    "INFILL_INFRASTRUCTURE",
    "NONE",
)

BIDDER_ENTITY_TYPES = ("INDIVIDUAL", "CORPORATION", "NONPROFIT", "PARTNERSHIP")

TITLE_ITEM_TYPES = (
    "LIEN",
    "ENCROACHMENT",
    "MISSING_ACCESS_EASEMENT",
    "BOUNDARY_GAP",
    "UNRECORDED_LEASE",
)

TITLE_ITEM_RESOLUTIONS = ("CURED", "WAIVED_WITH_ENDORSEMENT", "RESERVED_AS_EASEMENT")
