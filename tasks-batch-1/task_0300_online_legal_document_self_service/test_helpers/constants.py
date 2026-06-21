"""Domain thresholds — numeric constants from PRD pricing and completeness rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Base document-portion price per document type (cents), PRD §3.4.
BASE_PRICE_CENTS = {
    "WILL": 4999,
    "LLC": 9999,
    "POA": 3999,
    "LEASE": 2999,
}

# Per-state surcharge (cents), PRD §3.4.
STATE_SURCHARGE_CENTS = {
    "CA": 1500,
    "NY": 1999,
    "TX": 0,
    "FL": 0,
}

# Per-extra-clause overage fee (cents), PRD §3.4.
EXTRA_CLAUSE_FEE_CENTS = 799

# Standard attorney-review surcharge before discount (cents), PRD §3.5.
REVIEW_SURCHARGE_CENTS = 7500

# Notary fee added to the final invoice when an envelope requires notary (cents), PRD §3.7.
NOTARY_FEE_CENTS = 2500

# Total required questionnaire questions per document type, PRD §3.3.
TOTAL_REQUIRED_QUESTIONS = {
    "WILL": 8,
    "LLC": 6,
    "POA": 4,
    "LEASE": 6,
}

# Reminder interval applied at SIGNED time, PRD §3.7 (days).
REMINDER_INTERVAL_DAYS = 90

# Lease turnover buffer between consecutive lease terms on the same property, PRD §3.8 (days).
LEASE_TURNOVER_BUFFER_DAYS = 7

# Pagination defaults, PRD §2.3.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100


THRESHOLDS = {
    "EXTRA_CLAUSE_FEE_CENTS": EXTRA_CLAUSE_FEE_CENTS,
    "REVIEW_SURCHARGE_CENTS": REVIEW_SURCHARGE_CENTS,
    "NOTARY_FEE_CENTS": NOTARY_FEE_CENTS,
    "REMINDER_INTERVAL_DAYS": REMINDER_INTERVAL_DAYS,
    "LEASE_TURNOVER_BUFFER_DAYS": LEASE_TURNOVER_BUFFER_DAYS,
}
