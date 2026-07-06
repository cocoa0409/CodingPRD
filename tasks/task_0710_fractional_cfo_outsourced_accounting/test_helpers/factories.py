"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Co LLC",
    "STATE_CODE": "CA",
    "RETAINER_TIER": "GROWTH",
    "ISSUE_DATE": "2026-03-01T00:00:00Z",
    "DUE_DATE": "2026-03-31T00:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    """Input fields: legal_name, state_code, retainer_tier, covenant_floor_cents?."""
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "retainer_tier": DEFAULTS["RETAINER_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_ledger_account_payload(**overrides) -> dict:
    """Input fields: account_code, account_type, name, parent_account_id?."""
    defaults = {
        "account_code": "1000",
        "account_type": "ASSET",
        "name": "Cash",
    }
    defaults.update(overrides)
    return defaults


def create_catchup_project_payload(**overrides) -> dict:
    """Input fields: months_behind, quoted_fee_cents."""
    defaults = {
        "months_behind": 3,
        "quoted_fee_cents": 400000,
    }
    defaults.update(overrides)
    return defaults


def create_monthly_close_payload(**overrides) -> dict:
    """Input fields: period_year, period_month, txn_count?."""
    defaults = {
        "period_year": 2026,
        "period_month": 1,
        "txn_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_close_task_payload(**overrides) -> dict:
    """Input fields: name, weight."""
    defaults = {
        "name": "Reconcile",
        "weight": 1,
    }
    defaults.update(overrides)
    return defaults


def create_ar_invoice_payload(**overrides) -> dict:
    """Input fields: counterparty_name, amount_cents, issue_date, due_date."""
    defaults = {
        "counterparty_name": "Customer",
        "amount_cents": 100000,
        "issue_date": DEFAULTS["ISSUE_DATE"],
        "due_date": DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_ap_bill_payload(**overrides) -> dict:
    """Input fields: vendor_name, amount_cents, due_date."""
    defaults = {
        "vendor_name": "Vendor",
        "amount_cents": 50000,
        "due_date": DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_payroll_run_payload(monthly_close_id, **overrides) -> dict:
    """Input fields: monthly_close_id, pay_date, pay_period_start, pay_period_end,
    total_employer_cost_cents."""
    defaults = {
        "monthly_close_id": monthly_close_id,
        "pay_date": "2026-03-31T00:00:00Z",
        "pay_period_start": "2026-03-01T00:00:00Z",
        "pay_period_end": "2026-04-01T00:00:00Z",
        "total_employer_cost_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_allocation_payload(**overrides) -> dict:
    """Input fields: department_name, dept_gross_cents."""
    defaults = {
        "department_name": "Ops",
        "dept_gross_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_forecast_payload(**overrides) -> dict:
    """Input field: opening_balance_cents."""
    defaults = {
        "opening_balance_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_forecast_line_payload(**overrides) -> dict:
    """Input fields: effective_date, direction, amount_cents."""
    defaults = {
        "effective_date": "2026-04-05T00:00:00Z",
        "direction": "OUTFLOW",
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_tax_handoff_payload(**overrides) -> dict:
    """Input field: tax_year."""
    defaults = {
        "tax_year": 2025,
    }
    defaults.update(overrides)
    return defaults
