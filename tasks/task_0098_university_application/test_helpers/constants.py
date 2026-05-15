"""Domain thresholds — numeric constants from PRD calculations.

Derived from verbatim PRD numbers in §2.3, §2.4, §3.4, §3.5, §3.6,
§3.7, §3.8, §3.9, §3.10.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Applicant constraints (PRD §3.1)
# ---------------------------------------------------------------------------
MIN_GPA = 0.00
MAX_GPA = 4.00
MIN_AGE_YEARS = 14  # PRD §3.1: "at least 14 years before now"


# ---------------------------------------------------------------------------
# Essay (PRD §3.4)
# ---------------------------------------------------------------------------
ESSAY_BODY_MIN_CHARS = 250
ESSAY_BODY_MAX_CHARS = 6500
MIN_CUSTOMIZATION_SCORE = 0.30  # PRD §3.4: "customization threshold for submission is 0.30"

# Draft variant weights (PRD §3.4)
DRAFT_LENGTH_WEIGHT = 0.40
DRAFT_UNI_WEIGHT = 0.20
DRAFT_PROG_WEIGHT = 0.20
DRAFT_PROMPT_WEIGHT = 0.20
DRAFT_LENGTH_DIVISOR = 500.0

# Submitted variant weights (PRD §3.4)
FINAL_LENGTH_WEIGHT = 0.35
FINAL_UNI_WEIGHT = 0.175
FINAL_PROG_WEIGHT = 0.175
FINAL_PROMPT_WEIGHT = 0.30
FINAL_LENGTH_DIVISOR = 650.0


# ---------------------------------------------------------------------------
# Recommendation (PRD §3.5)
# ---------------------------------------------------------------------------
INVITATION_VALIDITY_DAYS = 21  # PRD §3.5: "current clock plus 21 days"
WEAK_LETTER_MIN_WORDS = 200  # PRD §3.5: "below 200 ... does not count"


# ---------------------------------------------------------------------------
# Application timing (PRD §3.7)
# ---------------------------------------------------------------------------
ED_ENROLLMENT_WINDOW_DAYS = 14  # PRD §3.7: "admission_decision_at plus 14 days for EARLY_DECISION"
NON_ED_ENROLLMENT_WINDOW_DAYS = 30  # PRD §3.7: "30 days for REGULAR_DECISION or ROLLING"


# ---------------------------------------------------------------------------
# Financial Aid (PRD §3.8)
# ---------------------------------------------------------------------------
FEDERAL_LOAN_CAP_CENTS = 550_000  # PRD §3.8: "5,500 US dollars (550000 cents)"
FEDERAL_WS_CAP_CENTS = 250_000  # PRD §3.8: "2,500 US dollars (250000 cents)"
INSTITUTIONAL_GRANT_PCT = 0.70  # PRD §3.8: "institutional grant percentage of 0.70"
INSTITUTIONAL_LOAN_CAP_CENTS = 350_000  # PRD §3.8: "3,500 US dollars (350000 cents)"


# ---------------------------------------------------------------------------
# Waitlist rank score (PRD §3.9)
# ---------------------------------------------------------------------------
GPA_WEIGHT = 40.00  # PRD §3.9: "GPA weight of 40.00"
ESSAY_WEIGHT = 30.00  # PRD §3.9: "essay weight of 30.00"
TENURE_DAY_VALUE = 0.50  # PRD §3.9: "tenure day value of 0.50"
TENURE_DAY_CAP = 30  # PRD §3.9: "tenure-day cap of 30"
INTEREST_PER_PROGRAM = 5.00  # PRD §3.9: "interest-per-program value of 5.00"
INTEREST_PROGRAM_CAP = 3  # PRD §3.9: "interest program cap of 3"


# ---------------------------------------------------------------------------
# Yield offer batch sizing (PRD §3.9)
# ---------------------------------------------------------------------------
MELT_RATE_CONSTANT = 0.15  # PRD §3.9: "melt-rate constant of 0.15"
MAX_BATCH_PER_SWEEP = 50  # PRD §3.9: "maximum batch per sweep of 50"
WAITLIST_OFFER_VALIDITY_DAYS = 7  # PRD §3.9: "current clock plus 7 days"


# ---------------------------------------------------------------------------
# Test defaults — convenience values for factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "FULL_NAME": "Test Applicant",
    "HIGH_SCHOOL_GPA": 3.80,
    "HOUSEHOLD_INCOME_CENTS": 7_500_000,  # $75,000
    "FAFSA_EFC_CENTS": 2_000_000,  # $20,000
    "CSS_EFC_CENTS": 2_000_000,
    "UNIVERSITY_NAME": "Northstar University",
    "PROGRAM_NAME": "Computer Science",
    "YIELD_TARGET_COUNT": 100,
    "PROGRAM_CAPACITY": 10,
    "COST_OF_ATTENDANCE_CENTS": 8_000_000,  # $80,000
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "MIN_GPA",
    "MAX_GPA",
    "MIN_AGE_YEARS",
    "ESSAY_BODY_MIN_CHARS",
    "ESSAY_BODY_MAX_CHARS",
    "MIN_CUSTOMIZATION_SCORE",
    "DRAFT_LENGTH_WEIGHT",
    "DRAFT_UNI_WEIGHT",
    "DRAFT_PROG_WEIGHT",
    "DRAFT_PROMPT_WEIGHT",
    "DRAFT_LENGTH_DIVISOR",
    "FINAL_LENGTH_WEIGHT",
    "FINAL_UNI_WEIGHT",
    "FINAL_PROG_WEIGHT",
    "FINAL_PROMPT_WEIGHT",
    "FINAL_LENGTH_DIVISOR",
    "INVITATION_VALIDITY_DAYS",
    "WEAK_LETTER_MIN_WORDS",
    "ED_ENROLLMENT_WINDOW_DAYS",
    "NON_ED_ENROLLMENT_WINDOW_DAYS",
    "FEDERAL_LOAN_CAP_CENTS",
    "FEDERAL_WS_CAP_CENTS",
    "INSTITUTIONAL_GRANT_PCT",
    "INSTITUTIONAL_LOAN_CAP_CENTS",
    "GPA_WEIGHT",
    "ESSAY_WEIGHT",
    "TENURE_DAY_VALUE",
    "TENURE_DAY_CAP",
    "INTEREST_PER_PROGRAM",
    "INTEREST_PROGRAM_CAP",
    "MELT_RATE_CONSTANT",
    "MAX_BATCH_PER_SWEEP",
    "WAITLIST_OFFER_VALIDITY_DAYS",
    "TEST_DEFAULTS",
]
