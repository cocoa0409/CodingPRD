"""Business constants drawn verbatim from the PRD.

Every literal below is quoted from the specification narrative so that a test
can name the rule it exercises instead of hard-coding a bare number.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------

#: "the logical clock starts at exactly 2026-08-01T00:00:00Z"
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

#: "A day is exactly 86,400 seconds"
SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Envelope (PRD section 2.2 / 2.3)
# ---------------------------------------------------------------------------

API_REQUEST_ID_PREFIX = "req_"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

ISOS = ["CAISO", "ERCOT", "PJM", "MISO"]
SETTLEMENT_POINT_TYPES = ["HUB", "NODE"]

CREDIT_RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "NR"]
RATING_AGENCIES = ["SP", "MOODYS", "FITCH", "NONE"]
DISCLOSURE_FRAMEWORKS = ["CDP_AND_TCFD", "TCFD_ONLY", "CDP_ONLY", "NONE"]
QUALIFICATION_STATUSES = ["DRAFT", "UNDER_REVIEW", "QUALIFIED", "CONDITIONAL",
                          "REJECTED", "WATCHLIST"]
CREDIT_SCORE_VARIANTS = ["STANDALONE", "GUARANTOR_SUPPORTED"]
CREDIT_TIERS = ["PRIME", "STANDARD", "SUBPRIME", "DECLINED"]

TECHNOLOGIES = ["SOLAR", "WIND", "STORAGE_HYBRID"]
PROJECT_STATUSES = ["PRE_DEVELOPMENT", "PERMITTED", "INTERCONNECTION_APPROVED",
                    "NTP_ISSUED", "OPERATIONAL"]

PRODUCT_TYPES = ["PHYSICAL_DELIVERY", "VIRTUAL_CFD", "AGGREGATED"]
SETTLEMENT_FREQUENCIES = ["HOURLY", "MONTHLY"]
SHAPE_PRODUCTS = ["AS_GENERATED", "SOLAR_SHAPED_16X5", "BASELOAD_FIRM"]
BASIS_RESPONSIBILITIES = ["SELLER", "SHARED", "BUYER"]
DEAL_STATUSES = ["DRAFT", "TERM_SHEET_ISSUED", "UNDER_NEGOTIATION",
                 "TERMS_AGREED", "EXECUTED", "EFFECTIVE", "TERMINATED"]
DEAL_CREDIT_STATUSES = ["NOT_SUBMITTED", "SUBMITTED", "APPROVED", "DECLINED",
                        "SUPPORT_SHORTFALL"]
PRICE_TIERS = ["LOW", "MID", "HIGH"]

ALLOCATION_STATUSES = ["PROPOSED", "CONFIRMED", "WITHDRAWN"]
ROUND_STATUSES = ["OPEN", "COUNTERED", "ACCEPTED", "EXPIRED"]
ROUND_PROPOSERS = ["DEVELOPER", "OFFTAKER"]

INSTRUMENT_TYPES = ["LETTER_OF_CREDIT", "PARENT_GUARANTEE", "CASH_COLLATERAL"]
INSTRUMENT_PURPOSES = ["PERFORMANCE_SECURITY", "DEVELOPMENT_SECURITY"]
INSTRUMENT_STATUSES = ["PROPOSED", "POSTED", "RELEASED", "DRAWN", "EXPIRED"]

CP_TYPES = ["PERMITTING", "INTERCONNECTION", "NOTICE_TO_PROCEED",
            "REGISTRY_ACCOUNT"]
CP_STATUSES = ["PENDING", "SATISFIED", "WAIVED", "FAILED"]
CP_RESOLUTIONS = ["SATISFY", "WAIVE", "FAIL", "RECURE"]

TERMINATION_REASONS = ["CP_FAILURE", "BUYER_DEFAULT", "SELLER_DEFAULT",
                       "COD_DEADLINE_MISSED", "EXTENDED_FORCE_MAJEURE"]

SETTLEMENT_PERIOD_STATUSES = ["OPEN", "CALCULATED", "INVOICED", "SETTLED",
                              "DISPUTED"]
PERIOD_ADVANCE_ACTIONS = ["INVOICE", "SETTLE", "DISPUTE"]
CURTAILMENT_FLAGS = ["NONE", "ECONOMIC", "GRID_EMERGENCY", "BUYER_REQUESTED"]

REGISTRIES = ["WREGIS", "MRETS", "NAR"]
BATCH_STATUSES = ["MINTED", "TRANSFERRED", "RETIRED", "CANCELLED"]
CLAIM_SUBSTANTIATION_STATUSES = ["UNSUBSTANTIATED", "SUBSTANTIATED"]

RISK_EVENT_TYPES = ["CHANGE_IN_LAW", "FORCE_MAJEURE", "CURTAILMENT"]
RISK_STATUSES = ["CLAIMED", "ACCEPTED", "REJECTED"]
RISK_CLAIMANTS = ["DEVELOPER", "OFFTAKER"]
ALLOCATION_OUTCOMES = ["SELLER_BEARS", "SHARED", "BUYER_BEARS"]

# ---------------------------------------------------------------------------
# Credit scoring (PRD section 3.2)
# ---------------------------------------------------------------------------

#: "AAA scores 100, AA 92, A 84, BBB 72, BB 55, B 38, CCC 20, and NR 10"
RATING_POINTS = {"AAA": 100, "AA": 92, "A": 84, "BBB": 72,
                 "BB": 55, "B": 38, "CCC": 20, "NR": 10}

#: "CDP_AND_TCFD scores 100, TCFD_ONLY 80, CDP_ONLY 70 and NONE 30"
DISCLOSURE_POINTS = {"CDP_AND_TCFD": 100, "TCFD_ONLY": 80,
                     "CDP_ONLY": 70, "NONE": 30}

#: "0.55 on the rating component, 0.30 on leverage and 0.15 on disclosure"
WEIGHT_RATING = 0.55
WEIGHT_LEVERAGE = 0.30
WEIGHT_DISCLOSURE = 0.15

#: "a score of exactly 62.00 is STANDARD and 61.99 is SUBPRIME"
TIER_THRESHOLD_PRIME = 80.0
TIER_THRESHOLD_STANDARD = 62.0
TIER_THRESHOLD_SUBPRIME = 45.0

#: tier cap and EBITDA share limbs of the unsecured limit
TIER_LIMIT_CAP_USD = {"PRIME": 25000000.00, "STANDARD": 10000000.00,
                      "SUBPRIME": 2000000.00, "DECLINED": 0.00}
TIER_EBITDA_SHARE = {"PRIME": 0.05, "STANDARD": 0.02,
                     "SUBPRIME": 0.005, "DECLINED": 0.0}

#: additive sustainability components
SUSTAINABILITY_SBT_POINTS = 40
SUSTAINABILITY_RE100_POINTS = 30
SUSTAINABILITY_NEAR_TERM_POINTS = 20
SUSTAINABILITY_FRAMEWORK_POINTS = 10
SUSTAINABILITY_NEAR_TERM_YEAR = 2030

#: "lifts the rating component to the greater of its own and the guarantor's
#: rating component less eight points"
GUARANTOR_RATING_PENALTY = 8

#: qualification decision floors
QUALIFY_MIN_SUSTAINABILITY = 70.0
CONDITIONAL_MIN_SUSTAINABILITY = 40.0

# ---------------------------------------------------------------------------
# Pricing and volume (PRD section 3.4)
# ---------------------------------------------------------------------------

#: "0.28 for SOLAR, 0.42 for WIND, 0.35 for STORAGE_HYBRID"
CAPACITY_FACTOR = {"SOLAR": 0.28, "WIND": 0.42, "STORAGE_HYBRID": 0.35}
HOURS_PER_YEAR = 8760

PRICE_TIER_LOW_CEILING = 40.0
PRICE_TIER_MID_CEILING = 60.0

#: shape premium keyed by shape product and price tier
SHAPE_PREMIUM = {
    "AS_GENERATED": {"LOW": 0.00, "MID": 0.00, "HIGH": 0.00},
    "SOLAR_SHAPED_16X5": {"LOW": 2.00, "MID": 3.10, "HIGH": 4.00},
    "BASELOAD_FIRM": {"LOW": 4.50, "MID": 6.25, "HIGH": 8.00},
}

#: basis adder keyed by basis responsibility
BASIS_ADDER = {"SELLER": 1.50, "SHARED": 0.75, "BUYER": 0.00}

PRICE_BASE_YEAR = 2026
TERM_YEARS_MIN = 5
TERM_YEARS_MAX = 25
FIRST_DELIVERY_YEAR_MIN = 2026
FIRST_DELIVERY_YEAR_MAX = 2040
ESCALATION_MIN = 0.0
ESCALATION_MAX = 5.0

# ---------------------------------------------------------------------------
# Credit support (PRD sections 2.6 and 3.7)
# ---------------------------------------------------------------------------

#: "rounded up to the next whole 250,000 increment"
COLLATERAL_INCREMENT_USD = 250000.00

#: "AAA, AA and A all take 0.00, BBB takes 10.00 and BB takes 35.00"
LC_HAIRCUT_PCT = {"AAA": 0.00, "AA": 0.00, "A": 0.00, "BBB": 10.00, "BB": 35.00}
LC_ELIGIBLE_RATINGS = ["AAA", "AA", "A", "BBB", "BB"]

#: "PRIME 0.00, STANDARD 25.00 and SUBPRIME 60.00"
PG_HAIRCUT_PCT = {"PRIME": 0.00, "STANDARD": 25.00, "SUBPRIME": 60.00}

CASH_HAIRCUT_PCT = 0.00

#: "at least three hundred and sixty-five whole days"
MIN_INSTRUMENT_TENOR_DAYS = 365

# ---------------------------------------------------------------------------
# Day counts (PRD section 2.10)
# ---------------------------------------------------------------------------

ROUND_RESPONSE_DAYS = 14
SUPPORT_CURE_DAYS = 10
CP_CURE_DAYS = 15
WAIVER_COD_EXTENSION_DAYS = 30
FORCE_MAJEURE_TERMINATION_DAYS = 180
CP_PERMITTING_DAYS = 270
CP_INTERCONNECTION_DAYS = 540
CP_NOTICE_TO_PROCEED_DAYS = 720
CP_REGISTRY_ACCOUNT_DAYS = 60

#: "a claim_year no earlier than the batch's vintage year and no later than
#: the year after it"
CLAIM_YEAR_WINDOW_YEARS = 1

# ---------------------------------------------------------------------------
# Risk events (PRD section 3.9)
# ---------------------------------------------------------------------------

#: "nothing at all when the outcome is SELLER_BEARS, one half when it is
#: SHARED, and the whole shortfall when it is BUYER_BEARS"
DEEMED_SHARE = {"SELLER_BEARS": 0.0, "SHARED": 0.5, "BUYER_BEARS": 1.0}

#: buyer's share of the basis leg
BASIS_BUYER_SHARE = {"SELLER": 0.0, "SHARED": 0.5, "BUYER": 1.0}

PRICE_ADJUSTMENT_MIN = -10.00
PRICE_ADJUSTMENT_MAX = 10.00

# ---------------------------------------------------------------------------
# Identifiers that no row ever carries, used for the 404 ladder
# ---------------------------------------------------------------------------

UNKNOWN_UUIDS = {
    "project": "00000000-0000-4000-8000-0000000000c1",
    "offtaker": "00000000-0000-4000-8000-0000000000c2",
    "pricing_node": "00000000-0000-4000-8000-0000000000c3",
    "deal": "00000000-0000-4000-8000-0000000000d1",
    "allocation": "00000000-0000-4000-8000-0000000000d2",
    "round": "00000000-0000-4000-8000-0000000000d3",
    "credit_support": "00000000-0000-4000-8000-0000000000d4",
    "condition_precedent": "00000000-0000-4000-8000-0000000000d5",
    "settlement_period": "00000000-0000-4000-8000-0000000000d6",
    "attribute_batch": "00000000-0000-4000-8000-0000000000d7",
    "risk_event": "00000000-0000-4000-8000-0000000000d8",
    "guarantor": "00000000-0000-4000-8000-0000000000e1",
    "spare": "00000000-0000-4000-8000-000000000009",
}
