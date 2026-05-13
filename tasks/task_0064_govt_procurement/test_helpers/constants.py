"""Domain thresholds — numeric constants from PRD calculations.

All values are quoted from PRD prose:
- §3.3 "MIN_CREDIT_SCORE, which is set to the integer 600 (so 600 passes
  and 599 fails)."
- §3.4 "weights … summing to one within a tolerance of EPSILON (1e-9)."
- §3.7 "The committee size must be an odd integer between MIN_SIZE (3)
  and MAX_SIZE (9) inclusive, so the legal sizes are 3, 5, 7, and 9."
- §3.11 "the cumulative amendment ceiling is twenty percent above the
  original award."
- §2.3 "limit defaults to 10, with a minimum of 1 and a maximum of 100;
  offset defaults to 0."
- §2.4 ClockState "initialised at first boot to 1970-01-01T00:00:00.000Z."
"""
from __future__ import annotations
from typing import Tuple


THRESHOLDS = {
    "MIN_CREDIT_SCORE": 600,             # PRD §3.3
    "WEIGHT_SUM_EPSILON": 1.0e-9,        # PRD §3.4
    "COMMITTEE_MIN_SIZE": 3,             # PRD §3.7
    "COMMITTEE_MAX_SIZE": 9,             # PRD §3.7
    "COMMITTEE_VALID_SIZES": (3, 5, 7, 9),  # PRD §3.7 ("odd integer ... legal sizes are 3, 5, 7, and 9")
    "AMENDMENT_CAP_FACTOR": 1.20,        # PRD §3.11 (20% ceiling)
    "FISCAL_YEAR_MIN": 2000,             # PRD §3.1
    "FISCAL_YEAR_MAX": 2100,             # PRD §3.1
    "CREDIT_SCORE_MIN": 0,               # PRD §3.3
    "CREDIT_SCORE_MAX": 1000,            # PRD §3.3
    "PAGINATION_DEFAULT_LIMIT": 10,      # PRD §2.3
    "PAGINATION_MIN_LIMIT": 1,           # PRD §2.3
    "PAGINATION_MAX_LIMIT": 100,         # PRD §2.3
}


TEST_DEFAULTS = {
    "AGENCY_ID": "agency-001",
    "FISCAL_YEAR": 2026,
    "PLAN_ITEM_BUDGET_CENTS": 10_000_000,        # 100,000.00 CNY
    "ESTIMATED_VALUE_CENTS": 10_000_000,
    "BID_PRICE_CENTS": 8_000_000,
    "CONTRACT_AMOUNT_CENTS": 8_000_000,
    "DEFAULT_CREDIT_SCORE": 600,                  # PRD §3.3 default
    "TEMPLATE_ID": "tmpl-001",
    "TECHNICAL_SPEC": "Standard technical specification text.",
    "COMMERCIAL_SPEC": "Net 30 payment terms; CNY; FOB destination.",
    "MAX_TECHNICAL_SCORE": 100,
    "MAX_QUALIFICATION_SCORE": 100,
    "CLOCK_ORIGIN": "1970-01-01T00:00:00.000Z",
    "CLOCK_T0": "2026-01-01T00:00:00.000Z",
}


# Affirm committee valid sizes are an ordered tuple for parametrize.
def committee_valid_sizes() -> Tuple[int, ...]:
    return THRESHOLDS["COMMITTEE_VALID_SIZES"]


__all__ = ["THRESHOLDS", "TEST_DEFAULTS", "committee_valid_sizes"]
