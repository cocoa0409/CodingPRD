"""Payload factories — one per entity, input fields only.

Only `source: input` fields appear here; the server mints all system/computed
fields. Defaults are sensible; tests override via keyword arguments.
"""


def create_company_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Co",
        "credit_limit_cents": 1_000_000,
        "billing_model": "CHARGE",
    }
    defaults.update(overrides)
    return defaults


def suspend_company_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def set_clock_payload(company_id, to_iso8601, **overrides) -> dict:
    defaults = {"company_id": company_id, "to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def create_spend_policy_payload(company_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "name": "Std",
        "per_transaction_limit_cents": 500_000,
        "approval_threshold_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(company_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "email": "employee@acme.com",
        "full_name": "Test Employee",
        "employee_role": "CARDHOLDER",
    }
    defaults.update(overrides)
    return defaults


def create_gl_account_payload(company_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "gl_code": "6000",
        "name": "Travel",
    }
    defaults.update(overrides)
    return defaults


def create_card_payload(company_id, employee_id, spend_policy_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "employee_id": employee_id,
        "spend_policy_id": spend_policy_id,
        "form_factor": "VIRTUAL",
        "card_limit_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def capture_transaction_payload(**overrides) -> dict:
    defaults = {
        "merchant_name": "Merchant",
        "mcc_code": "5999",
        "amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def settle_payload(settled_amount_cents, **overrides) -> dict:
    defaults = {"settled_amount_cents": settled_amount_cents}
    defaults.update(overrides)
    return defaults


def code_transaction_payload(gl_account_id, **overrides) -> dict:
    defaults = {"gl_account_id": gl_account_id}
    defaults.update(overrides)
    return defaults


def receipt_payload(amount_cents, merchant_name="Merchant", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "merchant_name": merchant_name}
    defaults.update(overrides)
    return defaults


def flag_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def approval_decision_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_reimbursement_claim_payload(company_id, employee_id, gl_account_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "employee_id": employee_id,
        "gl_account_id": gl_account_id,
        "merchant_name": "Taxi",
        "amount_cents": 9000,
        "receipt_amount_cents": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_repayment_payload(statement_id, amount_cents, expected_statement_version, **overrides) -> dict:
    defaults = {
        "statement_id": statement_id,
        "amount_cents": amount_cents,
        "expected_statement_version": expected_statement_version,
    }
    defaults.update(overrides)
    return defaults


def redeem_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_spend_authorization_payload(company_id, employee_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "scope": "EMPLOYEE",
        "employee_id": employee_id,
        "budget_cents": 50_000,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_erp_sync_batch_payload(company_id, statement_id, **overrides) -> dict:
    defaults = {"company_id": company_id, "statement_id": statement_id}
    defaults.update(overrides)
    return defaults
