"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Late fees — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "where late fees accrue at five thousand cents per late month
# — that is fifty dollars — capped at twenty-five thousand cents".
LATE_FEE_PER_MONTH_CENTS: int = 5_000
LATE_FEE_CAP_CENTS: int = 25_000


# ---------------------------------------------------------------------------
# Escrow analysis — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The projection looks forward 365 days from analysis_date."
ESCROW_PROJECTION_WINDOW_DAYS: int = 365

# PRD §3.3: "The two-month RESPA-style cushion".
ESCROW_CUSHION_MONTHS: int = 2

# PRD §3.3: "when surplus_cents strictly exceeds five thousand cents
# (i.e. exceeds fifty dollars), the system creates a new Disbursement of
# type SURPLUS_REFUND".
SURPLUS_REFUND_FLOOR_CENTS: int = 5_000

# PRD §3.3: "with amount_cents equal to surplus_cents, scheduled_date
# thirty days in the future".
SURPLUS_REFUND_OFFSET_DAYS: int = 30


# ---------------------------------------------------------------------------
# Forbearance — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "When the clock advances at least thirty days past end_date
# and cure_balance_cents is still strictly positive, the plan transitions
# to BREACHED".
FORBEARANCE_BREACH_GRACE_DAYS: int = 30

# PRD §3.4: "months (between 1 and 12 inclusive)".
FORBEARANCE_MIN_MONTHS: int = 1
FORBEARANCE_MAX_MONTHS: int = 12


# ---------------------------------------------------------------------------
# Delinquency / posture — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "When delinquency reaches at least 120 days and no ACTIVE
# plan covers the loan, the system transitions the loan from DELINQUENT
# to DEFAULT".
DEFAULT_DELINQUENCY_DAYS: int = 120


# ---------------------------------------------------------------------------
# PMI removal — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "evaluated_ltv_bps no greater than 8000 for BORROWER_REQUEST".
PMI_BORROWER_REQUEST_LTV_BPS: int = 8_000

# PRD §3.5: "no greater than 7800 for AUTO_TERMINATION".
PMI_AUTO_TERMINATION_LTV_BPS: int = 7_800

# PRD §3.5: "there is no POSTED Payment whose received_date was later
# than its scheduled due date within the last 24 scheduled months".
PMI_HISTORY_WINDOW_MONTHS: int = 24


# ---------------------------------------------------------------------------
# Foreclosure — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "The 30-day NOI window is the borrower's last opportunity to
# request pre-foreclosure mediation."
NOI_WINDOW_DAYS: int = 30

# PRD §3.6: "After the case has been on file for at least 60 days, the
# attorney may schedule an auction".
AUCTION_MIN_DAYS_AFTER_FILED: int = 60

# PRD §3.6: "The proposed auction_date must be at least 30 days in the
# future (statutory notice)".
AUCTION_MIN_NOTICE_DAYS: int = 30

# PRD §3.6: "reinstatement must be attempted strictly more than 5 days
# before auction_date".
REINSTATEMENT_CUTOFF_DAYS: int = 5


# ---------------------------------------------------------------------------
# Mediation — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "automatically when the rejection reason is BORROWER_REFUSED
# or when 60 days have elapsed since noi_sent_at".
MEDIATION_AUTO_FAIL_DAYS: int = 60

# PRD §3.7: "A MediationCase left in OPEN without an extended offer for
# 90 days since noi_sent_at is also auto-failed on clock advance."
MEDIATION_OPEN_TIMEOUT_DAYS: int = 90

# PRD §3.7: "If the recomputed value diverges from the stored
# target_payment_cents by more than 100 cents, the completion is
# rejected with ERR_HAMP_STALE_OFFER."
HAMP_STALE_OFFER_TOLERANCE_CENTS: int = 100


# ---------------------------------------------------------------------------
# Loan input constraints — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "original_principal_cents (at least 100,000, i.e. at least
# one thousand dollars)".
MIN_ORIGINAL_PRINCIPAL_CENTS: int = 100_000

# PRD §3.1: "interest_rate_bps (a fixed-rate value between 1 and 5000
# basis points)".
MIN_INTEREST_RATE_BPS: int = 1
MAX_INTEREST_RATE_BPS: int = 5_000

# PRD §3.1: "term_months (between 60 and 480 inclusive)".
MIN_TERM_MONTHS: int = 60
MAX_TERM_MONTHS: int = 480

# PRD §3.1: "full_name (non-empty, at most 200 characters)".
FULL_NAME_MAX_LEN: int = 200


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10, has a minimum of 1, and a maximum of
# 100. offset defaults to 0".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test default money values — anchored to scenario examples in PRD prose.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "ORIGINAL_PRINCIPAL_CENTS": 20_000_000,         # $200,000
    "ORIGINAL_APPRAISED_VALUE_CENTS": 25_000_000,   # $250,000
    "INTEREST_RATE_BPS": 625,                       # 6.25%
    "TERM_MONTHS": 360,                             # 30y
    "PMI_MONTHLY_CENTS": 8_000,                     # $80
}


__all__ = [
    "LATE_FEE_PER_MONTH_CENTS",
    "LATE_FEE_CAP_CENTS",
    "ESCROW_PROJECTION_WINDOW_DAYS",
    "ESCROW_CUSHION_MONTHS",
    "SURPLUS_REFUND_FLOOR_CENTS",
    "SURPLUS_REFUND_OFFSET_DAYS",
    "FORBEARANCE_BREACH_GRACE_DAYS",
    "FORBEARANCE_MIN_MONTHS",
    "FORBEARANCE_MAX_MONTHS",
    "DEFAULT_DELINQUENCY_DAYS",
    "PMI_BORROWER_REQUEST_LTV_BPS",
    "PMI_AUTO_TERMINATION_LTV_BPS",
    "PMI_HISTORY_WINDOW_MONTHS",
    "NOI_WINDOW_DAYS",
    "AUCTION_MIN_DAYS_AFTER_FILED",
    "AUCTION_MIN_NOTICE_DAYS",
    "REINSTATEMENT_CUTOFF_DAYS",
    "MEDIATION_AUTO_FAIL_DAYS",
    "MEDIATION_OPEN_TIMEOUT_DAYS",
    "HAMP_STALE_OFFER_TOLERANCE_CENTS",
    "MIN_ORIGINAL_PRINCIPAL_CENTS",
    "MIN_INTEREST_RATE_BPS",
    "MAX_INTEREST_RATE_BPS",
    "MIN_TERM_MONTHS",
    "MAX_TERM_MONTHS",
    "FULL_NAME_MAX_LEN",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
