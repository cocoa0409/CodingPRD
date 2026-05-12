"""Domain thresholds and unit constants for the Fund Sales and Clearing test
suite.

All values are taken directly from PRD prose -- no scaffold leakage. Tests
import these constants by name so boundary assertions track PRD changes
explicitly rather than relying on magic numbers.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Money / share / NAV unit denominators (PRD §2.6, §2.7)
# ---------------------------------------------------------------------------
SHARE_UNIT_DENOM = 10_000           # 1e-4 share unit (10000 = 1 whole share)
MICROS_PER_CNY = 1_000_000          # nav_per_share_micros: 1_000_000 = 1 CNY
BPS_DENOM = 10_000                  # 10000 bps = 100%
DAYS_PER_YEAR = 365                 # daily-prorated fee accrual divisor


# ---------------------------------------------------------------------------
# NAV (PRD §3.4)
# ---------------------------------------------------------------------------
INITIAL_NAV_MICROS = 1_000_000      # PRD §3.4: when shares_outstanding == 0


# ---------------------------------------------------------------------------
# Confirmation cycle table (PRD §3.2: shelf approval table)
# ---------------------------------------------------------------------------
CONFIRMATION_CYCLE_DAYS = {
    "EQUITY": 2,
    "HYBRID": 2,
    "BOND": 1,
    "MONEY_MARKET": 0,
    "QDII": 3,
}


# ---------------------------------------------------------------------------
# Large-redemption threshold default (PRD §3.2)
# ---------------------------------------------------------------------------
DEFAULT_LARGE_REDEMPTION_THRESHOLD_PCT_BPS = 1_000  # i.e., 10%


# ---------------------------------------------------------------------------
# Acceptance window cutoff (PRD §3.3)
# ---------------------------------------------------------------------------
ACCEPTANCE_CUTOFF_HOUR_UTC = 15      # 15:00 UTC


# ---------------------------------------------------------------------------
# Suitability index ordering (PRD §3.3 / §2.10 priority 10)
# ---------------------------------------------------------------------------
RISK_TOLERANCE_INDEX = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "C5": 5}
RISK_RATING_INDEX = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}


# ---------------------------------------------------------------------------
# AuditLog actions (PRD §2.8)
# ---------------------------------------------------------------------------
AUDIT_ACTIONS = (
    "ORDER_STATUS_CHANGE",
    "NAV_PUBLISHED",
    "NAV_ADJUSTED",
    "DIVIDEND_EXECUTED",
    "RECONCILIATION_RESOLVED",
    "FUND_SHELF_CHANGE",
)


# ---------------------------------------------------------------------------
# Test defaults (deliberately sized for arithmetic clarity in tests)
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # An investor seeded with this much cash can take part in the standard
    # SUBSCRIBE-confirm-REDEEM workflows without hitting ERR_INSUFFICIENT_CASH.
    "INVESTOR_INITIAL_CASH_CENTS": 100_000_000,
    # 100_000 cents = 1000 CNY -- a comfortable single-order size.
    "DEFAULT_SUBSCRIBE_GROSS_CENTS": 100_000,
    # 1.0 CNY/share == 1_000_000 micros per share, the value emitted by the
    # initial-NAV path in PRD §3.4.
    "DEFAULT_NAV_MICROS": 1_000_000,
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "SHARE_UNIT_DENOM",
    "MICROS_PER_CNY",
    "BPS_DENOM",
    "DAYS_PER_YEAR",
    "INITIAL_NAV_MICROS",
    "CONFIRMATION_CYCLE_DAYS",
    "DEFAULT_LARGE_REDEMPTION_THRESHOLD_PCT_BPS",
    "ACCEPTANCE_CUTOFF_HOUR_UTC",
    "RISK_TOLERANCE_INDEX",
    "RISK_RATING_INDEX",
    "AUDIT_ACTIONS",
    "TEST_DEFAULTS",
]
