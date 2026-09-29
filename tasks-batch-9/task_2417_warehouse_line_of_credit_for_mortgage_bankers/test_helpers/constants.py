"""Domain thresholds and constants stated in the PRD."""

# ─── Sizing and valuation constants ───────────────────────────────────────────

#: "the rate is replaced by the smaller of itself and the orphan ceiling of 0.85"
ORPHAN_RATE_CEILING = 0.85

#: "the minimum advance size of 1,000,000 cents — ten thousand dollars"
MIN_ADVANCE_CENTS = 1_000_000

#: "the de-minimis floor of 5,000,000,000 cents — fifty million dollars"
DE_MINIMIS_CONCENTRATION_FLOOR_CENTS = 5_000_000_000

#: "the document-exception haircut of 0.05"
EXCEPTION_HAIRCUT = 0.05

#: "complete twenty-four-hour periods — each of 86,400 seconds"
SECONDS_PER_DAY = 86_400

#: "the facility spread of 0.0225"
FACILITY_SPREAD = 0.0225

#: "divided by a day-count basis of 360"
DAY_COUNT_BASIS = 360

#: "sized at one tenth of `outstanding_principal_cents`"
COVENANT_BREACH_PAYDOWN_PCT = 0.10

#: "`deadline_at` is ten days after it"
DEMAND_DEADLINE_DAYS = 10

#: "an optional `cure_days` which defaults to 2"
DEFAULT_CURE_DAYS = 2

#: "When the facility holds at least three such priors" the variant is TTM_ROLLING.
TTM_PRIOR_THRESHOLD = 3

#: "When the breach brings `consecutive_breach_count` to two"
CONSECUTIVE_BREACH_SUSPEND_THRESHOLD = 2

#: "A proposed window is widened by two days on each side"
COMMITMENT_WINDOW_BUFFER_DAYS = 2


# ─── Declared field defaults and input bounds ─────────────────────────────────

#: "`committed_amount_cents`, which must be at least 100,000,000 cents"
MIN_COMMITTED_AMOUNT_CENTS = 100_000_000

#: "`bailee_period_days` ... defaults to 30 and must be at least 1 and at most 90"
DEFAULT_BAILEE_PERIOD_DAYS = 30
MIN_BAILEE_PERIOD_DAYS = 1
MAX_BAILEE_PERIOD_DAYS = 90

#: "That deadline defaults to 72 hours and must be at least 1 and at most 240 hours"
DEFAULT_WET_RECEIPT_DEADLINE_HOURS = 72
MIN_WET_RECEIPT_DEADLINE_HOURS = 1
MAX_WET_RECEIPT_DEADLINE_HOURS = 240

#: "`wet_haircut` ... defaults to 0.02"
DEFAULT_WET_HAIRCUT = 0.02

#: "`aging_step_days` ... defaults to 15"
DEFAULT_AGING_STEP_DAYS = 15

#: "`curtailment_step_rate` ... defaults to 0.005"
DEFAULT_CURTAILMENT_STEP_RATE = 0.005

#: "`wet_funding_allowed` says whether wet funding is permitted ... defaults to true"
DEFAULT_WET_FUNDING_ALLOWED = True

#: "`dwell_limit_days` ... must be at least 1 and at most 365"
MIN_DWELL_LIMIT_DAYS = 1
MAX_DWELL_LIMIT_DAYS = 365

#: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100"
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100


# ─── Logical clock ────────────────────────────────────────────────────────────

#: "The server's mandatory default clock value before any call is
#: `2026-08-01T00:00:00Z`."
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"


# ─── Canonical scenario values used across fixtures ───────────────────────────

TEST_DEFAULTS = {
    "BORROWER_LEGAL_NAME": "Meridian Mortgage Bankers LLC",
    "COMMITTED_AMOUNT_CENTS": 20_000_000_000,
    "WET_SUBLIMIT_CENTS": 20_000_000_000,
    "AGED_SUBLIMIT_CENTS": 2_000_000_000,
    "SCRATCH_AND_DENT_SUBLIMIT_CENTS": 1_000_000_000,
    "MIN_TANGIBLE_NET_WORTH_CENTS": 1_500_000_000,
    "MIN_LIQUIDITY_CENTS": 500_000_000,
    "MIN_TTM_NET_INCOME_CENTS": 100_000_000,
    "MAX_INVESTOR_CONCENTRATION_PCT": 0.35,
    "UNUSED_LINE_FEE_RATE": 0.0025,
    "SETTLEMENT_ACCOUNT_LAST4": "4417",
    "CUSTODIAN_NAME": "First Doc Custody NA",
    "WET_RECEIPT_DEADLINE_HOURS": 48,
    "INVESTOR_NAME": "Alpha Aggregator",
    "COUNTERPARTY_RATING": "A",
    "CONCENTRATION_LIMIT_PCT": 0.60,
    "COMMITMENT_AMOUNT_CENTS": 5_000_000_000,
    "PRICE_PCT": 1.0125,
    "EFFECTIVE_ON": "2026-08-01",
    "EXPIRES_ON": "2026-12-31",
    "LOAN_AMOUNT_CENTS": 2_000_000_000,
    "NOTE_RATE": 0.0650,
    "PAYEE_NAME": "Summit Title & Escrow",
    "PAYEE_ACCOUNT_LAST4": "4417",
    "PAYEE_ROUTING_LAST4": "0021",
    "CONFORMING_ADVANCE_RATE": 0.98,
    "CONFORMING_DWELL_LIMIT_DAYS": 30,
    "CONFORMING_PRODUCT_SUBLIMIT_CENTS": 15_000_000_000,
}

#: Opaque operator identifiers. The PRD says that for the three lender-side
#: roles ``X-User-ID`` is "an opaque operator identifier not tied to any
#: persisted entity", so any distinct strings satisfy the four-eyes rules.
OPERATOR_IDS = {
    "CREDIT_OFFICER_PRIMARY": "co_1",
    "CREDIT_OFFICER_SECOND": "co_2",
    "COLLATERAL_ANALYST_PRIMARY": "ca_1",
    "COLLATERAL_ANALYST_SECOND": "ca_2",
    "WIRE_OPERATOR_PRIMARY": "wo_1",
    "WIRE_OPERATOR_SECOND": "wo_2",
}
