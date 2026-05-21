"""Domain thresholds — numeric constants from PRD calculations.

All monetary values are integer cents (PRD §2.9: "All monetary values
are stored and computed as integer cents - never as floats.").
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Fee rate / threshold constants — PRD §2.9
# ---------------------------------------------------------------------------
SEARCH_RATE_CENTS_PER_HOUR: int = 4500    # $45.00/hr
REVIEW_RATE_CENTS_PER_HOUR: int = 6000    # $60.00/hr (commercial-only)
COPY_RATE_CENTS_PER_PAGE: int = 10        # $0.10/page
FREE_PAGES: int = 100
FREE_SEARCH_HOURS: int = 2
FREE_THRESHOLD_CENTS: int = 1400          # $14.00
FINAL_CAP_MULTIPLIER_TIMES_100: int = 125  # 1.25x cap on growth from estimate


# ---------------------------------------------------------------------------
# Deadline / clock constants — PRD §2.7
# ---------------------------------------------------------------------------
RESPONSE_DAYS: int = 20
MAX_TOLL_DAYS: int = 30
THIRD_PARTY_DAYS: int = 10
APPEAL_DECIDE_WINDOW_DAYS: int = 20

# Seed holidays — PRD §2.7: "The minimal seeded holiday list contains
# January 1, July 4, and December 25 of the current calendar year".
SEED_HOLIDAYS_MMDD: tuple = (
    (1, 1),
    (7, 4),
    (12, 25),
)


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Allowed enumeration sets (mirrored from PRD §3) — kept as Python sets so
# factories can use membership checks readily.
# ---------------------------------------------------------------------------
GLOMAR_ALLOWED_BASES: set = {"B1", "B6", "B7C"}
EXEMPTION_CODES: set = {
    "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9",
}

REQUESTER_TIERS: set = {
    "COMMERCIAL", "EDUCATIONAL_NONCOMMERCIAL", "PUBLIC_INTEREST",
}

# ---------------------------------------------------------------------------
# Field-length caps — PRD §3.1, §3.2, §3.6, §3.9
# ---------------------------------------------------------------------------
MAX_FULL_NAME_LEN: int = 200
MAX_TIER_JUSTIFICATION_LEN: int = 1000
MAX_SUBJECT_SUMMARY_LEN: int = 2000
MAX_RECORD_TITLE_LEN: int = 200
MAX_RATIONALE_LEN: int = 1000
MAX_APPEAL_GROUNDS_LEN: int = 4000


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "REQUESTER_FULL_NAME": "Casey Test Requester",
    "REQUESTER_EMAIL": "casey@example.test",
    "REQUESTER_TIER": "COMMERCIAL",
    "REQUEST_SUBJECT_SUMMARY": "Records related to a recent policy review.",
    "RECORD_TITLE": "Policy memo draft",
    "EXEMPTION_RATIONALE": "Information falls within statutory exemption.",
    "APPEAL_GROUNDS": "We disagree with the determination as issued.",
    "OBJECTION_GROUNDS": "Disclosure would harm our commercial interests.",
    "TOLLING_REASON": "Awaiting clarification from requester.",
}


__all__ = [
    "SEARCH_RATE_CENTS_PER_HOUR",
    "REVIEW_RATE_CENTS_PER_HOUR",
    "COPY_RATE_CENTS_PER_PAGE",
    "FREE_PAGES",
    "FREE_SEARCH_HOURS",
    "FREE_THRESHOLD_CENTS",
    "FINAL_CAP_MULTIPLIER_TIMES_100",
    "RESPONSE_DAYS",
    "MAX_TOLL_DAYS",
    "THIRD_PARTY_DAYS",
    "APPEAL_DECIDE_WINDOW_DAYS",
    "SEED_HOLIDAYS_MMDD",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "GLOMAR_ALLOWED_BASES",
    "EXEMPTION_CODES",
    "REQUESTER_TIERS",
    "MAX_FULL_NAME_LEN",
    "MAX_TIER_JUSTIFICATION_LEN",
    "MAX_SUBJECT_SUMMARY_LEN",
    "MAX_RECORD_TITLE_LEN",
    "MAX_RATIONALE_LEN",
    "MAX_APPEAL_GROUNDS_LEN",
    "TEST_DEFAULTS",
]
