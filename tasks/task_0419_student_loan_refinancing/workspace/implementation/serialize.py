"""Serializers: convert internal records to the public JSON resource shape.

Field names come verbatim from scaffold §1.1 entity tables and the PRD. The
internal record stores datetime helper fields (e.g. expires_at_dt) that are not
exposed; the public form carries the ISO-string fields the PRD declares.

Common fields (PRD §2.4): Borrower, AbsPool, Application, Offer, Cosigner, Loan,
Disbursement, Payment, ForbearancePlan carry id, created_at, updated_at, version.
RateGridEntry and AuditEvent carry only id + created_at (no updated_at/version).
"""

_COMMON = ["id", "created_at", "updated_at", "version"]
_LIGHT = ["id", "created_at"]


def _pick(record, fields):
    return {f: record.get(f) for f in fields}


def borrower(r):
    return _pick(r, _COMMON + [
        "email", "full_name", "annual_income_cents", "fico_band", "member_tier",
    ])


def abs_pool(r):
    return _pick(r, _COMMON + [
        "pool_code", "max_principal_cents", "min_fico_band", "allowed_rate_type",
        "committed_principal_cents", "status",
    ])


def rate_grid_entry(r):
    return _pick(r, _LIGHT + [
        "rate_type", "term_months", "min_fico_band", "base_apr_bps", "index_apr_bps",
    ])


def application(r):
    return _pick(r, _COMMON + [
        "borrower_id", "requested_principal_cents", "requested_term_months",
        "requested_rate_type", "soft_pull_fico_band", "dti_ratio", "status",
        "approved_underwriter_id",
    ])


def offer(r):
    return _pick(r, _COMMON + [
        "application_id", "rate_grid_entry_index", "term_months", "rate_type",
        "estimated_apr_bps", "locked_apr_bps", "autopay_elected", "status",
        "expires_at",
    ])


def cosigner(r):
    return _pick(r, _COMMON + [
        "application_id", "cosigner_email", "cosigner_annual_income_cents",
        "consent_status", "on_time_streak",
    ])


def loan(r):
    return _pick(r, _COMMON + [
        "application_id", "offer_id", "abs_pool_id", "original_principal_cents",
        "principal_balance_cents", "accrued_interest_cents", "last_accrual_at",
        "locked_apr_bps", "term_months", "repayment_status", "cosigner_release_status",
    ])


def disbursement(r):
    return _pick(r, _COMMON + [
        "loan_id", "prior_servicer_name", "payoff_amount_cents", "status",
    ])


def payment(r):
    return _pick(r, _COMMON + [
        "loan_id", "amount_cents", "due_date", "paid_at", "on_time",
        "interest_portion_cents", "principal_portion_cents",
    ])


def forbearance_plan(r):
    return _pick(r, _COMMON + [
        "loan_id", "reason_code", "months_requested", "interest_capitalized_cents",
        "status",
    ])


def audit_event(r):
    return _pick(r, _LIGHT + [
        "subject_type", "subject_id", "action", "actor_role", "actor_user_id",
    ])
