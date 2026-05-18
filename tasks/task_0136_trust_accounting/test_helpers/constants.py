"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# GST — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "The simplified per-trust lifetime GST exemption limit is
# 13,610,000.00 USD; the GST tax rate applied to amounts beyond
# exemption is 40%."
GST_EXEMPTION_LIMIT: float = 13_610_000.00
GST_TAX_RATE: float = 0.40

# PRD §3.2 (beneficiary skip-person rule): "the beneficiary is a skip
# person when that age difference is at least 37.5 years. ... an age
# difference of exactly 37.5 years qualifies as a skip person; 37.49
# does not."
GST_GENERATION_GAP_YEARS: float = 37.5


# ---------------------------------------------------------------------------
# Trust income tax — PRD §3.8 compressed-trust marginal brackets
# ---------------------------------------------------------------------------
# PRD §3.8: "The first band covers taxable income from 0.00 up to
# 3,100.00 at a marginal rate of 10%. The second band covers the range
# above 3,100.00 up to 11,150.00 at 24%. The third band covers the
# range above 11,150.00 up to 15,200.00 at 35%. The fourth band covers
# everything above 15,200.00 at 37%."
BRACKET_1_TOP: float = 3_100.00
BRACKET_2_TOP: float = 11_150.00
BRACKET_3_TOP: float = 15_200.00
BRACKET_1_RATE: float = 0.10
BRACKET_2_RATE: float = 0.24
BRACKET_3_RATE: float = 0.35
BRACKET_4_RATE: float = 0.37


# ---------------------------------------------------------------------------
# Monetary precision — PRD §2.7
# ---------------------------------------------------------------------------
# PRD §2.7: "All monetary fields are denominated in United States
# dollars and carry exactly 2 decimal places."
MONEY_DECIMALS: int = 2


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter has a default of 10, a minimum of 1,
# and a maximum of 100; the offset parameter has a default of 0 and a
# minimum of 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — convenient values that are inside every PRD-allowed
# range and stay away from boundary edges unless a test wants them.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "TRUST_NAME": "Test Family Trust",
    "SITUS_STATE": "NY",
    "INCEPTION_DATE": "2026-01-01",
    "INCEPTION_YEAR": 2026,
    "BENEFICIARY_BIRTH_DATE": "1990-06-01",
    "BENEFICIARY_NAME": "Jane Doe",
    "TRUSTEE_FULL_NAME": "Alice Trustee",
    "ASSET_BOOK_VALUE": 100_000.00,
    "ORDINARY_INCOME": 10_000.00,
}


__all__ = [
    "GST_EXEMPTION_LIMIT",
    "GST_TAX_RATE",
    "GST_GENERATION_GAP_YEARS",
    "BRACKET_1_TOP",
    "BRACKET_2_TOP",
    "BRACKET_3_TOP",
    "BRACKET_1_RATE",
    "BRACKET_2_RATE",
    "BRACKET_3_RATE",
    "BRACKET_4_RATE",
    "MONEY_DECIMALS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
