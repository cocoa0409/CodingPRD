"""Domain thresholds and numeric constants stated in the PRD."""

# PRD 2.6 — the logical clock reads exactly this instant at startup.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

# PRD 2.6 — authorization validity horizon.
AUTH_VALIDITY_HOURS = 720

# PRD 3.5 / 3.6 — small-ticket ceiling in cents.
SMALL_TICKET_MAX_CENTS = 1500

# PRD 3.6 — cross-border component.
CROSS_BORDER_RATE_BPS = 40
CROSS_BORDER_MIN_CENTS = 15

# PRD 3.6 — step four nested clamp: cap first, then floor.
ASSESSMENT_CAP_BPS = 350
ASSESSMENT_FLOOR_CENTS = 8

# PRD 3.6 — the quarterly downgrade tripwire.
DOWNGRADE_AUDIT_TRIGGER = 3

# PRD 3.8 — volume tier breakpoints (inclusive lower bounds) and discounts.
TIER_1_FLOOR_CENTS = 5_000_000
TIER_2_FLOOR_CENTS = 20_000_000
TIER_3_FLOOR_CENTS = 50_000_000
TIER_DISCOUNT_BPS = {
    "TIER_0": 0,
    "TIER_1": 25,
    "TIER_2": 60,
    "TIER_3": 100,
}

# PRD 3.9 — misrepresentation penalty.
MISREPRESENTATION_PENALTY_BPS = 2500
MIN_PENALTY_CENTS = 5000

# PRD 3.4 — the reclassification review loop is bounded at three rounds.
MAX_REVIEW_ROUNDS = 3

# PRD 2.3 — pagination defaults and bounds.
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# PRD 3.5 — the clearing data element vocabulary.
DATA_ELEMENT_VOCABULARY = [
    "AUTH_CODE",
    "TERMINAL_ID",
    "TRANSACTION_DATE",
    "CARDHOLDER_ZIP",
    "CUSTOMER_ACCOUNT_REF",
    "TAX_AMOUNT",
]

# Reference-data literals reused across the suite.
TEST_DEFAULTS = {
    "PLATFORM_NAME": "PLAT-NA-1",
    "REGION_CODE": "NA",
    "MAX_CONCURRENT_WINDOWS": 1,
    "BLACKOUT_BUFFER_DAYS": 3,
    "ACQUIRER_NAME": "Acme Acquiring",
    "BIN_PREFIX": "411111",
    "SECOND_ACQUIRER_NAME": "Beacon Acquiring",
    "SECOND_BIN_PREFIX": "422222",
    "COUNTRY_CODE": "US",
    "SETTLEMENT_CURRENCY": "USD",
    "MERCHANT_NAME": "Corner Grocer",
    "BUSINESS_TYPE_KEY": "GROCERY",
}
