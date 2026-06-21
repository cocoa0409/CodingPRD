"""Entity serializers — emit exactly the contract fields per entity.

Full-lifecycle resources carry id/created_at/updated_at/version (PRD 2.4).
Append-only audit records (SubstantiationReceipt, LedgerEntry) carry only
id/created_at (PRD 2.4). The internal _seq bookkeeping field is never emitted.
"""

_COMMON = ("id", "created_at", "updated_at", "version")
_AUDIT_COMMON = ("id", "created_at")


def _pick(entity, common, fields):
    out = {}
    for k in common:
        out[k] = entity.get(k)
    for k in fields:
        out[k] = entity.get(k)
    return out


def sponsor(e):
    return _pick(e, _COMMON, (
        "name", "ein", "minimum_grant_cents", "inactivity_quarters",
        "admin_fee_bps_default", "current_quarter_index",
    ))


def pool(e):
    return _pick(e, _COMMON, (
        "sponsor_id", "name", "risk_tier", "nav_per_unit_cents", "fee_bps", "status",
    ))


def nav_period(e):
    return _pick(e, _COMMON, (
        "investment_pool_id", "from_quarter", "to_quarter",
        "nav_per_unit_cents", "status",
    ))


def charity(e):
    return _pick(e, _COMMON, (
        "sponsor_id", "legal_name", "ein", "ntee_code",
        "is_private_foundation", "status", "vetting_note",
    ))


def account(e):
    return _pick(e, _COMMON, (
        "sponsor_id", "account_name", "primary_advisor_user_id",
        "cash_balance_cents", "invested_value_cents", "committed_grants_cents",
        "admin_fee_accrued_cents", "grantable_balance_cents",
        "last_grant_paid_quarter", "status",
    ))


def contribution(e):
    return _pick(e, _COMMON, (
        "donor_account_id", "asset_type", "cash_amount_cents", "ticker",
        "quantity_milli", "high_price_cents", "low_price_cents",
        "closing_price_cents", "spot_price_cents", "thinly_traded",
        "fair_market_value_cents", "status",
    ))


def receipt(e):
    return _pick(e, _AUDIT_COMMON, (
        "contribution_id", "donor_account_id", "receipt_number",
        "deductible_value_cents", "asset_description", "issued_quarter_index",
    ))


def allocation(e):
    return _pick(e, _COMMON, (
        "donor_account_id", "investment_pool_id", "units_micro",
        "target_pct_bps", "status",
    ))


def grant(e):
    return _pick(e, _COMMON, (
        "donor_account_id", "charity_id", "amount_cents", "is_anonymous",
        "purpose", "recurrence", "effective_from_quarter", "effective_to_quarter",
        "recommended_by_user_id", "approved_by_user_id", "paid_quarter_index",
        "status",
    ))


def succession_plan(e):
    return _pick(e, _COMMON, (
        "donor_account_id", "plan_type", "beneficiaries", "status",
    ))


def rebalance_order(e):
    return _pick(e, _COMMON, (
        "donor_account_id", "source_pool_id", "target_pool_id", "amount_cents",
        "source_units_redeemed_micro", "target_units_bought_micro", "status",
    ))


def ledger_entry(e):
    return _pick(e, _AUDIT_COMMON, (
        "donor_account_id", "entry_type", "signed_amount_cents",
        "ref_entity", "ref_id", "quarter_index",
    ))
