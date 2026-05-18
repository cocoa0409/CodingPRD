"""Domain thresholds and defaults.

All numeric constants here are derived from the PRD's stated formulas,
deadlines, and clamping ranges (PRD §3.2 – §3.13).
"""
from __future__ import annotations


# ===========================================================================
# Deadline windows — PRD §3.2, §3.3, §3.8, §3.10
# ===========================================================================
# PRD §3.2: "deadline_day as submitted_day plus thirty — the FCRA base window."
DISPUTE_BASE_WINDOW_DAYS = 30
# PRD §3.2: "submitted_day plus forty-five — the FCRA fifteen-day extension."
DISPUTE_EXTENDED_WINDOW_DAYS = 45
# PRD §3.3: "reverification_deadline_day is set to its forwarded_day plus
# twenty-five — twenty-five logical days regardless of whether the dispute
# itself has been extended."
FURNISHER_REVERIFY_WINDOW_DAYS = 25
# PRD §3.10: "the dispute's deadline_day is reset to the current clock day
# plus thirty"
CFPB_REOPEN_WINDOW_DAYS = 30


# ===========================================================================
# Frivolous threshold — PRD §3.2
# ===========================================================================
# PRD §3.2: "if the consumer has already submitted more than three disputes
# against the same tradeline_item_id in the trailing 365 logical days, the
# submission is rejected with ERR_FRIVOLOUS_DISPUTE."
FRIVOLOUS_THRESHOLD_COUNT = 3
FRIVOLOUS_LOOKBACK_DAYS = 365


# ===========================================================================
# FICO calculation — PRD §3.5
# ===========================================================================
FICO_PAYMENT_HISTORY_WEIGHT = 0.35
FICO_UTILIZATION_WEIGHT = 0.30
FICO_AGE_WEIGHT = 0.15
FICO_MIX_WEIGHT = 0.10
FICO_RECENT_INQUIRIES_WEIGHT = 0.10
# PRD §3.5: per-tradeline nominal limit ($10,000 = 1,000,000 cents)
FICO_PER_ITEM_NOMINAL_LIMIT_CENTS = 1_000_000
# PRD §2.10 / §3.5: clamp to [300, 850].
FICO_MIN = 300
FICO_MAX = 850
# PRD §3.5: payment status → payment score.
FICO_PAYMENT_SCORE = {
    "CURRENT": 100,
    "LATE_30": 70,
    "LATE_60": 40,
    "LATE_90": 20,
    "CHARGE_OFF": 0,
    "COLLECTION": 0,
}


# ===========================================================================
# Dispute risk score — PRD §3.6, §2.10
# ===========================================================================
DISPUTE_RISK_WEIGHT_DISPUTES = 2
DISPUTE_RISK_WEIGHT_DISMISSED = 5
DISPUTE_RISK_WEIGHT_DOCS = -1
DISPUTE_RISK_WEIGHT_ESCALATED = 3
DISPUTE_RISK_MULTIPLIER = 10
# PRD §2.10: clamp to [0, 100].
DISPUTE_RISK_MIN = 0
DISPUTE_RISK_MAX = 100


# ===========================================================================
# Free-report grant — PRD §3.6
# ===========================================================================
# PRD §3.6: "the grant size is two reports for a consumer with any active
# freeze and one report otherwise"
FREE_REPORT_GRANT_DEFAULT = 1
FREE_REPORT_GRANT_FROZEN = 2
# PRD §3.6: "capped at the inclusive maximum of 12."
FREE_REPORTS_MAX = 12
# PRD §3.1: "the server initializes the consumer's free_reports_remaining
# counter to 1"
FREE_REPORTS_INITIAL = 1


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ===========================================================================
# RegulatoryComplaint narrative bounds — PRD §3.10
# ===========================================================================
# PRD §3.10: "a free-form consumer narrative between 1 and 4,000 characters
# long."
NARRATIVE_MIN_LEN = 1
NARRATIVE_MAX_LEN = 4000


# ===========================================================================
# Test-suite defaults — used by factories / fixtures to make deterministic
# choices that the PRD permits (everything here is a default, not a PRD
# constraint).
# ===========================================================================
TEST_DEFAULTS = {
    "BALANCE_CENTS_DEFAULT": 500_000,        # $5,000
    "BALANCE_CENTS_LATE": 500_000,
    "ORIGINAL_DOFD_DAY_DEFAULT": 100,
    "BUREAU_DEFAULT": "EQUIFAX",
    "PAYMENT_STATUS_DEFAULT": "LATE_90",
    "REQUESTED_ACTION_DEFAULT": "CORRECT_BALANCE",
    "REQUESTED_PAYLOAD_DEFAULT": {"new_balance_cents": 100},
    "CHANNEL_DEFAULT": "ONLINE",
    "ECOA_CODE_DEFAULT": "1",
    "AGENCY_DEFAULT": "CFPB",
}


__all__ = [
    "DISPUTE_BASE_WINDOW_DAYS",
    "DISPUTE_EXTENDED_WINDOW_DAYS",
    "FURNISHER_REVERIFY_WINDOW_DAYS",
    "CFPB_REOPEN_WINDOW_DAYS",
    "FRIVOLOUS_THRESHOLD_COUNT",
    "FRIVOLOUS_LOOKBACK_DAYS",
    "FICO_PAYMENT_HISTORY_WEIGHT",
    "FICO_UTILIZATION_WEIGHT",
    "FICO_AGE_WEIGHT",
    "FICO_MIX_WEIGHT",
    "FICO_RECENT_INQUIRIES_WEIGHT",
    "FICO_PER_ITEM_NOMINAL_LIMIT_CENTS",
    "FICO_MIN",
    "FICO_MAX",
    "FICO_PAYMENT_SCORE",
    "DISPUTE_RISK_WEIGHT_DISPUTES",
    "DISPUTE_RISK_WEIGHT_DISMISSED",
    "DISPUTE_RISK_WEIGHT_DOCS",
    "DISPUTE_RISK_WEIGHT_ESCALATED",
    "DISPUTE_RISK_MULTIPLIER",
    "DISPUTE_RISK_MIN",
    "DISPUTE_RISK_MAX",
    "FREE_REPORT_GRANT_DEFAULT",
    "FREE_REPORT_GRANT_FROZEN",
    "FREE_REPORTS_MAX",
    "FREE_REPORTS_INITIAL",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "NARRATIVE_MIN_LEN",
    "NARRATIVE_MAX_LEN",
    "TEST_DEFAULTS",
]
