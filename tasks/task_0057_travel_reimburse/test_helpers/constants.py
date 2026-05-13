"""Domain thresholds for the Travel Reimburse API.

All numeric constants are derived from explicit PRD statements:
- AMOUNT_DEPT_THRESHOLD / AMOUNT_GM_THRESHOLD (PRD §3.2 required-chain rules)
- BUDGET_OVERRUN_FACTOR (PRD §3.3 budget pre-allocation)
- MAX_PAYMENT_ATTEMPTS (PRD §3.9 payment retry exhaustion)
- DECLARED_HOLIDAYS (PRD §3.1 / §3.4 / §3.8)
- Pagination defaults (PRD §2.3)
"""
from __future__ import annotations
from typing import List


# Required-approval-chain thresholds (PRD §3.2)
AMOUNT_DEPT_THRESHOLD = 5_000.00   # > 5,000 → DEPT_HEAD added (when DOMESTIC)
AMOUNT_GM_THRESHOLD = 30_000.00    # > 30,000 → GM added (when DOMESTIC)

# Budget pre-allocation cap (PRD §3.3)
BUDGET_OVERRUN_FACTOR = 1.20

# Payment retry exhaustion (PRD §3.9)
MAX_PAYMENT_ATTEMPTS = 3

# Declared holidays (PRD §3.1, §3.4, §3.8)
DECLARED_HOLIDAYS: List[str] = ["2025-01-01", "2025-05-01", "2025-10-01"]

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


THRESHOLDS = {
    "AMOUNT_DEPT_THRESHOLD": AMOUNT_DEPT_THRESHOLD,
    "AMOUNT_GM_THRESHOLD": AMOUNT_GM_THRESHOLD,
    "BUDGET_OVERRUN_FACTOR": BUDGET_OVERRUN_FACTOR,
    "MAX_PAYMENT_ATTEMPTS": MAX_PAYMENT_ATTEMPTS,
}

__all__ = [
    "AMOUNT_DEPT_THRESHOLD",
    "AMOUNT_GM_THRESHOLD",
    "BUDGET_OVERRUN_FACTOR",
    "MAX_PAYMENT_ATTEMPTS",
    "DECLARED_HOLIDAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "THRESHOLDS",
]
