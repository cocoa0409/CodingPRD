"""Domain thresholds and constants from PRD §3 calculations.

Every constant here is named in the PRD prose; values are pinned for
benchmark determinism.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Monthly accrual rates — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the monthly interest rate (locked at 0.006667 for benchmark
# determinism, which corresponds to roughly eight percent on an annual basis)"
MONTHLY_INTEREST_RATE: float = 0.006667

# PRD §3.2: "one half of one percent (0.005) when the liability is OPEN"
MONTHLY_FTP_RATE_NON_IA: float = 0.005

# PRD §3.2: "exactly one quarter of one percent (0.0025) ... when the
# liability is IN_AGREEMENT"
MONTHLY_FTP_RATE_IA: float = 0.0025

# PRD §3.2: "zero when the liability is CNC"
MONTHLY_FTP_RATE_CNC: float = 0.0


# ---------------------------------------------------------------------------
# CSED — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The baseline window is exactly ten years long, anchored at
# the assessment_date"
CSED_STATUTORY_YEARS: int = 10


# ---------------------------------------------------------------------------
# Installment-agreement type gating — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "whenever the aggregate covered debt exceeds 2,500,000 cents
# (which is $25,000), the payment_method must be DDIA"
DDIA_THRESHOLD_CENTS: int = 2_500_000

# PRD §3.4: "the aggregate covered debt is at most 5,000,000 cents
# (which is $50,000)"
LONG_TERM_DEBT_MAX_CENTS: int = 5_000_000

# PRD §3.4: "the spread from activation to projected payoff must not
# exceed 180 days"
SHORT_TERM_MAX_DAYS: int = 180


# ---------------------------------------------------------------------------
# Payoff projection — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "if after 120 simulated months (which is exactly ten years)"
PAYOFF_MAX_PROJECTION_MONTHS: int = 120


# ---------------------------------------------------------------------------
# RCP — PRD §3.9
# ---------------------------------------------------------------------------
# PRD §3.9: "if the proposed payoff schedule is at most five monthly
# installments, the factor is 12"
RCP_LUMP_SUM_FACTOR: int = 12

# PRD §3.9: "if the schedule is at most twenty-four monthly installments,
# the factor is 24"
RCP_PERIODIC_FACTOR: int = 24


# ---------------------------------------------------------------------------
# OIC — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "a Payment of payment_kind OIC_DEPOSIT exists for the offer
# with amount_cents at least equal to twenty percent of offer_amount_cents,
# rounded up to the next whole cent"
OIC_DEPOSIT_PERCENT: float = 0.20


# ---------------------------------------------------------------------------
# Federal Tax Lien — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "the aggregate debt across the lien's liabilities is at most
# 2,500,000 cents (which is $25,000) — the so-called DDIA streamlined
# withdrawal"
LIEN_WITHDRAWAL_DEBT_MAX_CENTS: int = 2_500_000


# ---------------------------------------------------------------------------
# CNC — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "the taxpayer's monthly_disposable_income_cents must be at
# most zero (inclusive — exactly zero is eligible, but one cent of
# disposable income fails the check)"
CNC_MAX_MDI_CENTS: int = 0

# PRD §3.11: "review_due_date is pinned at the effective date plus 24
# months"
CNC_REVIEW_DUE_MONTHS: int = 24


# ---------------------------------------------------------------------------
# Default / next-due — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the server pins next_due_date to activation date plus 30
# days"
NEXT_DUE_DAYS: int = 30

# PRD §3.4: "When missed_payment_count reaches three or more"
MISSED_PAYMENT_DEFAULT_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Test defaults — used by factories
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "TAXPAYER_FILING_STATUS": "SINGLE",
    "TAXPAYER_MDI_CENTS": 200_000,                    # $2,000 / month
    "LIABILITY_BALANCE_CENTS": 1_000_000,             # $10,000
    "TAX_YEAR_DEFAULT": 2019,
    "ASSESSMENT_DATE_DEFAULT": "2020-01-01T00:00:00.000Z",
    "AGREEMENT_MONTHLY_CENTS": 200_000,
    "OIC_OFFER_CENTS": 1_500_000,
    "OIC_DEPOSIT_CENTS": 300_000,
    "OIC_SCHEDULE_MONTHS_LUMP": 5,
    "OIC_SCHEDULE_MONTHS_PERIODIC": 24,
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "MONTHLY_INTEREST_RATE",
    "MONTHLY_FTP_RATE_NON_IA",
    "MONTHLY_FTP_RATE_IA",
    "MONTHLY_FTP_RATE_CNC",
    "CSED_STATUTORY_YEARS",
    "DDIA_THRESHOLD_CENTS",
    "LONG_TERM_DEBT_MAX_CENTS",
    "SHORT_TERM_MAX_DAYS",
    "PAYOFF_MAX_PROJECTION_MONTHS",
    "RCP_LUMP_SUM_FACTOR",
    "RCP_PERIODIC_FACTOR",
    "OIC_DEPOSIT_PERCENT",
    "LIEN_WITHDRAWAL_DEBT_MAX_CENTS",
    "CNC_MAX_MDI_CENTS",
    "CNC_REVIEW_DUE_MONTHS",
    "NEXT_DUE_DAYS",
    "MISSED_PAYMENT_DEFAULT_THRESHOLD",
    "TEST_DEFAULTS",
]
