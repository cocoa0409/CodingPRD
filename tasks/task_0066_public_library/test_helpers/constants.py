"""Domain thresholds and constants pinned by PRD §3.

These values are the numeric anchors for the Library API's calculations and
state-machine rules. They are NOT inputs to mutating endpoints — they are
verifiable expectations derived from PRD prose.
"""

# ─────────────────────────────────────────────────────────────
# Fine accrual schedule by subject_category (PRD §3.6)
# ─────────────────────────────────────────────────────────────

# Per-day rates in cents
DAILY_RATE_BY_CATEGORY = {
    "GENERAL": 20,
    "REFERENCE": 50,
    "CHILDREN": 10,
    "RARE": 200,
}

# Per-copy cap in cents
FINE_CAP_BY_CATEGORY = {
    "GENERAL": 5000,
    "REFERENCE": 10000,
    "CHILDREN": 2000,
    "RARE": 50000,
}

# ─────────────────────────────────────────────────────────────
# Card schedule by card_type (PRD §3.2)
# ─────────────────────────────────────────────────────────────

MAX_LOANS_BY_CARD_TYPE = {
    "REGULAR": 5,
    "STUDENT": 8,
    "SENIOR": 4,
    "TEMPORARY": 2,
}

LOAN_DURATION_DAYS_BY_CARD_TYPE = {
    "REGULAR": 30,
    "STUDENT": 60,
    "SENIOR": 45,
    "TEMPORARY": 14,
}

MAX_RENEWALS_BY_CARD_TYPE = {
    "REGULAR": 2,
    "STUDENT": 3,
    "SENIOR": 2,
    "TEMPORARY": 0,
}

# ─────────────────────────────────────────────────────────────
# Workflow-level constants (PRD §3.4-§3.7)
# ─────────────────────────────────────────────────────────────

# Hold window for reservations: PRD §3.4 describes "the hold period of two days"
# and §3.5 echoes "the hold period of two days"; PRD §2.12 mentions "hold_expires_at".
HOLD_PERIOD_HOURS = 48
HOLD_PERIOD_DAYS = 2

# Recall grace period: PRD §3.4 "the smaller of ... and the simulated now() plus the
# recall grace period of three days".
RECALL_GRACE_DAYS = 3

# ILL: PRD §3.7 — handling fee per leg, insurance rate, and requester max loan.
ILL_HANDLING_FEE_CENTS = 300
ILL_INSURANCE_RATE_BPS = 250  # 2.50%, expressed in basis points
ILL_REQUESTER_MAX_LOAN_DAYS = 21
ILL_LEGS = 2

# Approved partner libraries (PRD §3.7).
ILL_APPROVED_PARTNERS = ("PL_A", "PL_B", "PL_C")

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ─────────────────────────────────────────────────────────────
# Test convenience defaults — not PRD-mandated values, just stable
# fixtures-side inputs.
# ─────────────────────────────────────────────────────────────

TEST_DEFAULTS = {
    "READER_FULL_NAME": "Test Reader",
    # 64-char SHA-256 hex placeholder per PRD §3.2
    "NATIONAL_ID_HASH": "a" * 64,
    "BOOK_AUTHOR": "Test Author",
    "BOOK_PUBLISHER": "Test Publisher",
    "BOOK_TITLE": "Test Bibliographic Title",
    "CLASSIFICATION_CODE": "813.54",
    "ISBN_VALID": "9780000000002",
    "ISBN_VALID_ALT": "9780000000019",
    "LOCATION_CODE": "A-12-03",
    # ISO 8601 anchors for clock/validity ranges
    "CARD_VALID_FROM": "2020-01-01T00:00:00.000Z",
    "CARD_VALID_UNTIL_FAR_FUTURE": "2099-12-31T00:00:00.000Z",
    # The acquired_at timestamp for copies must be a stable past instant.
    "COPY_ACQUIRED_AT": "2020-01-01T00:00:00.000Z",
}
