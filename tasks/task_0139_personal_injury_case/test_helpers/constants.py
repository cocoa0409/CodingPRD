"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter defaults to 10 when not provided, has a
# minimum permitted value of 1, and a maximum permitted value of 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Statute of Limitations base years — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "California auto cases use 2 years, California medical-
# malpractice cases use 3 years, California slip-and-fall, product-
# liability, premises, and dog-bite cases each use 2 years, New York
# auto, slip-and-fall, product-liability, premises, and dog-bite cases
# each use 3 years, New York medical-malpractice cases use 2 years, and
# Texas cases of every type use 2 years."
SOL_BASE_YEARS = {
    ("CA", "AUTO"): 2,
    ("CA", "MEDICAL_MALPRACTICE"): 3,
    ("CA", "SLIP_FALL"): 2,
    ("CA", "PRODUCT_LIABILITY"): 2,
    ("CA", "PREMISES"): 2,
    ("CA", "DOG_BITE"): 2,
    ("NY", "AUTO"): 3,
    ("NY", "MEDICAL_MALPRACTICE"): 2,
    ("NY", "SLIP_FALL"): 3,
    ("NY", "PRODUCT_LIABILITY"): 3,
    ("NY", "PREMISES"): 3,
    ("NY", "DOG_BITE"): 3,
    ("TX", "AUTO"): 2,
    ("TX", "MEDICAL_MALPRACTICE"): 2,
    ("TX", "SLIP_FALL"): 2,
    ("TX", "PRODUCT_LIABILITY"): 2,
    ("TX", "PREMISES"): 2,
    ("TX", "DOG_BITE"): 2,
}

# PRD §3.2: "California's minor tail is 2 years, New York's is 3 years,
# and Texas's is 2 years".
SOL_MINOR_TAIL_YEARS = {
    "CA": 2,
    "NY": 3,
    "TX": 2,
}

# PRD §3.2: "the system computes is_minor_at_incident on the client by
# asking whether the elapsed years between the client's date of birth
# and the case's incident_date is less than 18 years"
ADULT_AGE_YEARS: int = 18


# ---------------------------------------------------------------------------
# Records / Demand thresholds — PRD §3.3, §3.5
# ---------------------------------------------------------------------------
# PRD §3.3: "the case's sol_deadline is more than 30 days into the future
# at the moment of the request — paralegals cannot start records work on
# a case whose statute will mature within the next month"
RECORDS_MIN_SOL_DAYS: int = 30

# PRD §3.5: "its response_due_at is stamped at exactly 30 calendar days
# after sent_at"
DEMAND_RESPONSE_DUE_DAYS: int = 30


# ---------------------------------------------------------------------------
# Contingency fee bps — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "the three rate fields pre_suit_rate_bps, post_suit_rate_bps,
# and trial_rate_bps (each defaulting respectively to 3333, 4000, and
# 4500, each greater than 0 and at most 5000)"
DEFAULT_PRE_SUIT_RATE_BPS: int = 3333
DEFAULT_POST_SUIT_RATE_BPS: int = 4000
DEFAULT_TRIAL_RATE_BPS: int = 4500
MIN_RATE_BPS_EXCLUSIVE: int = 0  # PRD §3.1: "each greater than 0"
MAX_RATE_BPS: int = 5000  # PRD §3.1: "and at most 5000"
BPS_DENOMINATOR: int = 10000  # PRD §3.9: "divided by ten thousand"


# ---------------------------------------------------------------------------
# Damages — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "when the method is MULTIPLIER, the payload must supply
# multiplier_value (a decimal in the closed range 1.0 to 5.0, defaulting
# to 1.5 and stored to one decimal place)"
MULTIPLIER_MIN: float = 1.0
MULTIPLIER_MAX: float = 5.0
MULTIPLIER_DEFAULT: float = 1.5


# ---------------------------------------------------------------------------
# Court event constraints — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "duration_minutes (an integer between 15 and 480 inclusive,
# used for calendar-conflict math)"
COURT_EVENT_MIN_DURATION_MINUTES: int = 15
COURT_EVENT_MAX_DURATION_MINUTES: int = 480

# PRD §3.7: "with a 15-minute travel buffer added to each side"
ATTORNEY_CALENDAR_BUFFER_MINUTES: int = 15

# PRD §3.7: "strictly before the case's sol_deadline plus five years (a
# sanity bound on stale calendaring)"
COURT_EVENT_SOL_SANITY_YEARS: int = 5


# ---------------------------------------------------------------------------
# Lien priority — PRD §3.10
# ---------------------------------------------------------------------------
# PRD §3.10: "The priority order by lien_type is MEDICARE first, then
# MEDICAID, then ERISA, then CHILD_SUPPORT, then HOSPITAL_STATUTORY,
# then ATTORNEY_PRIOR_COUNSEL, then PROVIDER_NEGOTIATED."
LIEN_PRIORITY_RANK = {
    "MEDICARE": 1,
    "MEDICAID": 2,
    "ERISA": 3,
    "CHILD_SUPPORT": 4,
    "HOSPITAL_STATUTORY": 5,
    "ATTORNEY_PRIOR_COUNSEL": 6,
    "PROVIDER_NEGOTIATED": 7,
}

# PRD §3.10: "if the lien's lien_type is MEDICARE, MEDICAID, ERISA, or
# CHILD_SUPPORT and negotiated_amount_cents is null, the system applies
# the statutory ratable-reduction formula"
STATUTORY_LIEN_TYPES = {"MEDICARE", "MEDICAID", "ERISA", "CHILD_SUPPORT"}

# PRD §3.8: "Liens of type PROVIDER_NEGOTIATED, HOSPITAL_STATUTORY, or
# ATTORNEY_PRIOR_COUNSEL are negotiable"
NEGOTIABLE_LIEN_TYPES = {
    "PROVIDER_NEGOTIATED",
    "HOSPITAL_STATUTORY",
    "ATTORNEY_PRIOR_COUNSEL",
}


# ---------------------------------------------------------------------------
# Reasonable test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "client_full_name": "Test Plaintiff",
    "client_dob_adult": "1990-01-01",
    "client_dob_minor": "2010-01-15",
    "client_email": "test+plaintiff@example.com",
    "client_state": "CA",
    "case_incident_date": "2024-01-15",
    "case_jurisdiction": "CA",
    "case_incident_type": "AUTO",
    "provider_name": "Test Hospital",
    "service_start": "2024-01-16",
    "service_end": "2024-02-15",
    "demand_amount_cents": 5_000_000,
    "offer_amount_cents": 5_000_000,
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "SOL_BASE_YEARS",
    "SOL_MINOR_TAIL_YEARS",
    "ADULT_AGE_YEARS",
    "RECORDS_MIN_SOL_DAYS",
    "DEMAND_RESPONSE_DUE_DAYS",
    "DEFAULT_PRE_SUIT_RATE_BPS",
    "DEFAULT_POST_SUIT_RATE_BPS",
    "DEFAULT_TRIAL_RATE_BPS",
    "MIN_RATE_BPS_EXCLUSIVE",
    "MAX_RATE_BPS",
    "BPS_DENOMINATOR",
    "MULTIPLIER_MIN",
    "MULTIPLIER_MAX",
    "MULTIPLIER_DEFAULT",
    "COURT_EVENT_MIN_DURATION_MINUTES",
    "COURT_EVENT_MAX_DURATION_MINUTES",
    "ATTORNEY_CALENDAR_BUFFER_MINUTES",
    "COURT_EVENT_SOL_SANITY_YEARS",
    "LIEN_PRIORITY_RANK",
    "STATUTORY_LIEN_TYPES",
    "NEGOTIABLE_LIEN_TYPES",
    "TEST_DEFAULTS",
]
