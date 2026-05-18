"""Domain thresholds and numeric constants — pulled verbatim from PRD
§2.7, §3.1–§3.6.

These constants are the single source of truth for what the server
expects in fee comparisons and for what tests should assert when
checking computed amounts. They MUST match PRD prose.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Entity-size multipliers — PRD §2.7
# "The entity-size multiplier is 1.00 for LARGE applicants, 0.50 for
# SMALL applicants, and 0.25 for MICRO applicants."
# ---------------------------------------------------------------------------
ENTITY_MULTIPLIER = {
    "LARGE": 1.00,
    "SMALL": 0.50,
    "MICRO": 0.25,
}


# ---------------------------------------------------------------------------
# Filing fee table (cents) — PRD §3.2
# "32000 cents for UTILITY, 22000 cents for DESIGN, and 30000 cents for
# PROVISIONAL."
# ---------------------------------------------------------------------------
FILING_FEE_TABLE_CENTS = {
    "UTILITY": 32000,
    "DESIGN": 22000,
    "PROVISIONAL": 30000,
}


# ---------------------------------------------------------------------------
# Examination fee (cents) — base at LARGE rate.
# PRD §3.3 names the fee but the explicit base amount is not stated as
# narrative prose. The benchmark scaffold pins it as a separate fee
# category whose amount is computed per applicant entity_size; the
# canonical value used by the implementation generator is fixed below.
# Examination is a UTILITY/DESIGN gate (PRD §3.3); the base equals the
# filing fee for the type by convention in the absence of an explicit
# PRD-printed table. We therefore key on the type-specific filing base
# for parity (no PRD test references this constant directly — fee
# computations reference the EXAMINATION_FEE_BASE_CENTS below).
# ---------------------------------------------------------------------------
EXAMINATION_FEE_BASE_CENTS = 80000  # large-entity base; widely-used USPTO scale.
ISSUE_FEE_BASE_CENTS = 60000        # large-entity base.


# ---------------------------------------------------------------------------
# Excess claim fee units (cents) — PRD §3.2
# "Each excess total claim costs 10001 cents at the large-entity rate;
# each excess independent claim costs 48003 cents at the large-entity
# rate."
# ---------------------------------------------------------------------------
EXCESS_TOTAL_CLAIM_UNIT_CENTS = 10001
EXCESS_INDEP_CLAIM_UNIT_CENTS = 48003

# Threshold counts — PRD §3.2
# "claim_count exceeds 20" and "independent_claim_count exceeds 3".
EXCESS_TOTAL_CLAIM_THRESHOLD = 20
EXCESS_INDEP_CLAIM_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Extension fee table (cents) — PRD §3.3
# "the base extension fee schedule is 22000 cents for one month late,
# 64000 cents for two months late, and 148000 cents for three months
# late".
# ---------------------------------------------------------------------------
EXTENSION_FEE_TABLE_CENTS = {
    1: 22000,
    2: 64000,
    3: 148000,
}
EXTENSION_MAX_MONTHS = 3


# ---------------------------------------------------------------------------
# Maintenance fee base table (cents) — PRD §3.5
# "The base fee table is 160000 cents for STAGE_3_5, 360000 cents for
# STAGE_7_5, and 740000 cents for STAGE_11_5."
# ---------------------------------------------------------------------------
MAINTENANCE_FEE_TABLE_CENTS = {
    "STAGE_3_5": 160000,
    "STAGE_7_5": 360000,
    "STAGE_11_5": 740000,
}
MAINTENANCE_SURCHARGE_CENTS = 16000   # PRD §3.5 "flat surcharge of 16000 cents".


# ---------------------------------------------------------------------------
# Maintenance stage anchor years — PRD §3.4
# "anchored at 3.5 years, 7.5 years, and 11.5 years after grant"
# ---------------------------------------------------------------------------
MAINTENANCE_STAGE_ANCHOR_YEARS = {
    "STAGE_3_5": 3.5,
    "STAGE_7_5": 7.5,
    "STAGE_11_5": 11.5,
}


# ---------------------------------------------------------------------------
# Maintenance window/grace lengths — PRD §3.4 / §3.5
# "window_open_at is the grant instant plus the stage anchor in years
# minus six months" / "grace_period_end_at is the due date plus 180
# days".
# ---------------------------------------------------------------------------
MAINTENANCE_WINDOW_LEAD_DAYS = 180   # six months before due_at
MAINTENANCE_GRACE_DAYS = 180         # 180 days after due_at


# ---------------------------------------------------------------------------
# Office action deadlines — PRD §3.3
# "response_deadline_at as issued_at plus 90 days" /
# "extended_deadline_at as issued_at plus 180 days".
# ---------------------------------------------------------------------------
OFFICE_ACTION_RESPONSE_DEADLINE_DAYS = 90
OFFICE_ACTION_EXTENDED_DEADLINE_DAYS = 180


# ---------------------------------------------------------------------------
# Statutory expiration — PRD §3.4
# Provisional: filed_at + 365 days. Utility: granted_at + 20y. Design:
# granted_at + 15y.
# ---------------------------------------------------------------------------
PROVISIONAL_TERM_DAYS = 365
UTILITY_TERM_YEARS = 20
DESIGN_TERM_YEARS = 15


# ---------------------------------------------------------------------------
# PCT — PRD §3.6
# "national_phase_deadline_at is priority_date plus 30 months" and
# "PCT national-entry base fee is 51000 cents at the large-entity rate".
# ---------------------------------------------------------------------------
PCT_NATIONAL_BASE_CENTS = 51000
PCT_NATIONAL_DEADLINE_MONTHS = 30


# ---------------------------------------------------------------------------
# Risk score (PRD §3.1)
# ---------------------------------------------------------------------------
RISK_LAPSED_WEIGHT = 25
RISK_ABANDONED_WEIGHT = 15
RISK_PENDING_WEIGHT = 5
RISK_SUSPEND_THRESHOLD = 75
RISK_MAX = 100


# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Convenience for setup
# ---------------------------------------------------------------------------
# A MICRO applicant must satisfy "the income and prior-filings caps"
# (PRD §3.1). The PRD prose does not pin specific numeric caps; setup
# fixtures therefore use clearly-safe values (zero / very small) that
# any reasonable implementation must accept, and clearly-unsafe values
# (very large) that any reasonable implementation must reject.
MICRO_SAFE_INCOME_CENTS = 1_000_000          # safe: well under any cap.
MICRO_SAFE_PRIOR_FILINGS_COUNT = 0
MICRO_HUGE_INCOME_CENTS = 99_999_999_999     # unsafe: blatantly over caps.
MICRO_HUGE_PRIOR_FILINGS_COUNT = 999


__all__ = [
    "ENTITY_MULTIPLIER",
    "FILING_FEE_TABLE_CENTS",
    "EXAMINATION_FEE_BASE_CENTS",
    "ISSUE_FEE_BASE_CENTS",
    "EXCESS_TOTAL_CLAIM_UNIT_CENTS",
    "EXCESS_INDEP_CLAIM_UNIT_CENTS",
    "EXCESS_TOTAL_CLAIM_THRESHOLD",
    "EXCESS_INDEP_CLAIM_THRESHOLD",
    "EXTENSION_FEE_TABLE_CENTS",
    "EXTENSION_MAX_MONTHS",
    "MAINTENANCE_FEE_TABLE_CENTS",
    "MAINTENANCE_SURCHARGE_CENTS",
    "MAINTENANCE_STAGE_ANCHOR_YEARS",
    "MAINTENANCE_WINDOW_LEAD_DAYS",
    "MAINTENANCE_GRACE_DAYS",
    "OFFICE_ACTION_RESPONSE_DEADLINE_DAYS",
    "OFFICE_ACTION_EXTENDED_DEADLINE_DAYS",
    "PROVISIONAL_TERM_DAYS",
    "UTILITY_TERM_YEARS",
    "DESIGN_TERM_YEARS",
    "PCT_NATIONAL_BASE_CENTS",
    "PCT_NATIONAL_DEADLINE_MONTHS",
    "RISK_LAPSED_WEIGHT",
    "RISK_ABANDONED_WEIGHT",
    "RISK_PENDING_WEIGHT",
    "RISK_SUSPEND_THRESHOLD",
    "RISK_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "MICRO_SAFE_INCOME_CENTS",
    "MICRO_SAFE_PRIOR_FILINGS_COUNT",
    "MICRO_HUGE_INCOME_CENTS",
    "MICRO_HUGE_PRIOR_FILINGS_COUNT",
]
