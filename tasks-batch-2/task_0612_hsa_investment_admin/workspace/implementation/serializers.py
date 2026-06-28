"""Public serializers — emit exactly the fields each entity declares
(SCAFFOLD §1.1 + common fields PRD §2.4).

Internal-only bookkeeping fields (e.g. limit_variant) are NOT emitted.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(obj, fields):
    return {f: obj.get(f) for f in fields}


def accountholder(o):
    return _pick(o, _COMMON + [
        "full_name", "email", "date_of_birth", "turns_55_or_older_in_plan_year",
    ])


def employer(o):
    return _pick(o, _COMMON + ["name", "payroll_contributions_enabled"])


def payroll_period(o):
    return _pick(o, _COMMON + [
        "employer_id", "period_start_day", "period_end_day", "status",
    ])


def account(o):
    return _pick(o, _COMMON + [
        "accountholder_id", "employer_id", "plan_year",
        "lifecycle_status", "contribution_posture",
        "cash_balance_cents", "invested_balance_cents",
        "contributions_ytd_cents", "applicable_limit_cents",
        "excess_contribution_cents",
        "invest_threshold_cents", "sweep_increment_cents",
        "verification_token",
    ])


def coverage_period(o):
    return _pick(o, _COMMON + [
        "account_id", "coverage_tier", "effective_month", "end_month", "status",
    ])


def contribution(o):
    return _pick(o, _COMMON + [
        "account_id", "channel", "amount_cents", "contribution_kind",
        "status", "posted_at",
    ])


def investment_sweep(o):
    return _pick(o, _COMMON + [
        "account_id", "requested_amount_cents", "swept_amount_cents", "status",
    ])


def distribution(o):
    return _pick(o, _COMMON + [
        "account_id", "method", "amount_cents", "card_id",
        "substantiation_status", "status", "receipt_id", "cleared_by_user_id",
    ])


def receipt(o):
    return _pick(o, _COMMON + [
        "account_id", "distribution_id", "merchant", "service_date",
        "amount_cents", "is_qualified_medical", "status",
    ])


def debit_card(o):
    return _pick(o, _COMMON + ["account_id", "last_four", "status"])


def excess_correction(o):
    return _pick(o, _COMMON + [
        "account_id", "requested_amount_cents", "corrected_amount_cents", "status",
    ])


def tax_form(o):
    # TaxForm carries only id + created_at (no updated_at / version) — PRD §2.4.
    return _pick(o, ["id", "created_at"] + [
        "account_id", "form_type", "tax_year",
        "gross_amount_cents", "nonqualified_amount_cents", "fair_market_value_cents",
    ])
