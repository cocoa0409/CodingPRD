"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Basis points divisor — PRD §2.7
# ---------------------------------------------------------------------------
# PRD §2.7: "The constant divisor used in the basis-points conversion is
# ten thousand."
BPS_DIVISOR: int = 10000

# PRD §2.7: "constrained to lie between 0 and 10000 inclusive (so 2000
# represents twenty percent and 10000 represents one hundred percent)."
COINSURANCE_RATE_BPS_MIN: int = 0
COINSURANCE_RATE_BPS_MAX: int = 10000


# ---------------------------------------------------------------------------
# Bad-debt write-off threshold — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "the elapsed time since billed_at must be at least 90 days …
# the boundary is inclusive, so a day count of exactly 90 passes and a
# day count of 89 does not."
MIN_DAYS_SINCE_BILLED: int = 90
MILLISECONDS_PER_DAY: int = 86_400_000


# ---------------------------------------------------------------------------
# Patient-responsibility reason codes — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "when denial_reason_code equals one of the patient-
# responsibility reason codes (PR-1, PR-2, or PR-3), the unallowed
# portion bypasses the deductible / coinsurance / OOP waterfall entirely
# and flows into patient_responsibility_cents in full."
PATIENT_RESPONSIBILITY_CODES = frozenset({"PR-1", "PR-2", "PR-3"})


# ---------------------------------------------------------------------------
# Patient MRN bounds — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "The mrn must be unique across all patients and must be
# between 8 and 12 alphanumeric characters in length."
MRN_MIN_LENGTH: int = 8
MRN_MAX_LENGTH: int = 12


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter caps the number of items returned and,
# when omitted, defaults to 10; the accepted range is a minimum of 1 and
# a maximum of 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # PRD §3.1 — sensible default policy benefit values.
    "DEDUCTIBLE_CENTS": 100_000,
    "COINSURANCE_RATE_BPS": 2000,  # 20%
    "OOP_MAX_CENTS": 200_000,
    "PLAN_YEAR": 2026,
    # PRD §3.4 — sensible default charge values.
    "CPT_CODE_PRIMARY": "99213",
    "CPT_CODE_SECONDARY": "99214",
    "CHARGE_UNIT_PRICE_CENTS": 150_000,
    "CHARGE_QUANTITY": 1,
    # PRD §3.6 — sensible default coding values.
    "PRIMARY_ICD10": "J18.9",
    "DEFAULT_CODER_ID": "coder-001",
    # PRD §2.11 — sensible default clock anchor inside plan_year 2026.
    "CLOCK_ANCHOR_2026": "2026-02-01T00:00:00.000Z",
}


__all__ = [
    "BPS_DIVISOR",
    "COINSURANCE_RATE_BPS_MIN",
    "COINSURANCE_RATE_BPS_MAX",
    "MIN_DAYS_SINCE_BILLED",
    "MILLISECONDS_PER_DAY",
    "PATIENT_RESPONSIBILITY_CODES",
    "MRN_MIN_LENGTH",
    "MRN_MAX_LENGTH",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
