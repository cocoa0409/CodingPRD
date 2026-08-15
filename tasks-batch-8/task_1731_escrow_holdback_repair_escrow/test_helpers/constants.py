"""Domain thresholds and shared test data (PRD §2.3, §2.4, §2.9, §3.1, §3.6)."""

# Contingency percentage bounds, inclusive (PRD §3.1).
CONTINGENCY_MIN_PCT = 10
CONTINGENCY_MAX_PCT = 25

# Extension grant caps (PRD §3.6).
MAX_TOTAL_EXTENSION_DAYS = 45
WEATHER_PER_REQUEST_CAP_DAYS = 21
NON_WEATHER_PER_REQUEST_CAP_DAYS = 7

# Requested-days input range (PRD §3.6).
REQUESTED_DAYS_MIN = 1
REQUESTED_DAYS_MAX = 45

# Pagination defaults (PRD §2.3).
DEFAULT_PAGE_LIMIT = 10
PAGE_LIMIT_MAX = 100

# Logical clock default before any explicit set (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"

# Standard party identifiers used across scenarios (opaque user ids, PRD §2.1).
PARTIES = {
    "officer": "officer_1",
    "buyer": "buyer_1",
    "seller": "seller_1",
    "lender": "lender_1",
    "insurer": "insurer_1",
    "contractor": "contr_1",
    "contractor_b": "contr_2",
    "inspector": "insp_1",
    "inspector_b": "insp_2",
}

# Standard scenario values reused by fixtures and tests.
STANDARD = {
    "property_address": "1 Harbor Way",
    "closing_date": "2026-08-01",
    "repair_scope": "Roof and gutter repair",
    "repair_estimate_cents": 200000,
    "contingency_pct": 15,
    "funding_source": "SELLER_PROCEEDS",
    "overrun_responsibility": "BUYER",
    "expiration_terms": "RETURN_TO_SELLER",
    "work_deadline_date": "2026-09-15",
    "hard_stop_date": "2026-10-15",
    "exterior_work_flag": True,
    "bid_amount_cents": 210000,
    "bid_scope_text": "Full tear-off and reshingle",
    # 200000 scaled by contingency 15 -> 230000 (PRD §3.1 sizing rule).
    "holdback_amount_cents": 230000,
    # 210000 scaled by contingency 15 -> 241500 (PRD §3.3 commitment basis).
    "commitment_basis_cents": 241500,
}

# Commonly used logical-clock readings (PRD §2.4).
CLOCK_SETUP = "2026-08-10T00:00:00Z"
CLOCK_ON_DEADLINE = "2026-09-15T12:00:00Z"
CLOCK_PAST_DEADLINE = "2026-09-16T00:00:00Z"
