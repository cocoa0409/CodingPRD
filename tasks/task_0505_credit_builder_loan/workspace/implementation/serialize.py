"""Serialize internal entity dicts to API output shape.

Strips internal bookkeeping fields (those starting with '_') and emits the
field set described by the PRD/SCAFFOLD entity tables.
"""


def _public(entity, fields):
    out = {"id": entity["id"], "created_at": entity["created_at"]}
    if "version" in entity:
        out["updated_at"] = entity["updated_at"]
        out["version"] = entity["version"]
    for f in fields:
        out[f] = entity.get(f)
    return out


ACCOUNT_FIELDS = [
    "email", "full_name", "state_code", "kyc_status", "disclosure_status",
    "posture", "status", "wallet_cents",
]
DISCLOSURE_FIELDS = [
    "account_id", "product_kind", "apr_bps", "admin_fee_cents", "status",
    "signed_by_compliance_user_id", "acknowledged_at",
]
LOAN_FIELDS = [
    "account_id", "disclosure_id", "principal_cents", "term_months", "apr_bps",
    "monthly_payment_cents", "funded_at", "principal_paid_cents",
    "interest_paid_cents", "outstanding_principal_cents", "lifecycle_status",
    "delinquency_status", "on_time_streak", "missed_count",
    "funded_by_servicer_user_id",
]
SCHEDULE_FIELDS = [
    "loan_id", "period_index", "due_date", "amount_due_cents",
    "principal_component_cents", "interest_component_cents",
    "amount_paid_cents", "status",
]
PAYMENT_FIELDS = [
    "loan_id", "amount_cents", "source", "applied_principal_cents",
    "applied_interest_cents", "applied_fee_cents", "posted_at", "status",
]
CARD_FIELDS = [
    "account_id", "disclosure_id", "deposit_cents", "credit_limit_cents",
    "balance_cents", "status", "graduation_eligible",
]
DEPOSIT_FIELDS = ["secured_card_id", "amount_cents", "status", "released_at"]
AUTOPAY_FIELDS = ["loan_id", "day_of_month", "funding_wallet", "status"]
BUREAU_FIELDS = [
    "loan_id", "tradeline_kind", "cycle_label", "payment_rating",
    "reported_balance_cents", "bureaus",
]
SNAPSHOT_FIELDS = ["account_id", "cycle_label", "simulated_score", "score_delta"]
QUOTE_FIELDS = [
    "loan_id", "quote_as_of", "payoff_amount_cents", "scheduled_remaining_cents",
    "interest_savings_cents", "status",
]


def account(e):
    return _public(e, ACCOUNT_FIELDS)


def disclosure(e):
    return _public(e, DISCLOSURE_FIELDS)


def loan(e):
    return _public(e, LOAN_FIELDS)


def schedule(e):
    return _public(e, SCHEDULE_FIELDS)


def payment(e):
    return _public(e, PAYMENT_FIELDS)


def card(e):
    return _public(e, CARD_FIELDS)


def deposit(e):
    return _public(e, DEPOSIT_FIELDS)


def autopay(e):
    return _public(e, AUTOPAY_FIELDS)


def bureau(e):
    # BureauReport is append-only: id + created_at only (no version/updated_at).
    return _public(e, BUREAU_FIELDS)


def snapshot(e):
    # ScoreSnapshot is append-only: id + created_at only.
    return _public(e, SNAPSHOT_FIELDS)


def quote(e):
    return _public(e, QUOTE_FIELDS)
