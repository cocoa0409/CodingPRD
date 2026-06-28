"""Payload factories — one per entity, input fields only."""


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": "Money Management International",
        "setup_fee_cents": 5000,
        "monthly_fee_cents": 3500,
    }
    defaults.update(overrides)
    return defaults


def create_counselor_payload(agency_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "full_name": "Cora Counselor",
        "hud_certified": False,
    }
    defaults.update(overrides)
    return defaults


def create_creditor_payload(agency_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "name": "BankOne",
        "default_concession_apr": 0.0699,
        "waives_late_fees": True,
        "min_proposed_payment_pct": 0.02,
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(agency_id, counselor_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "counselor_id": counselor_id,
        "full_name": "Dan Debtor",
        "gross_monthly_income_cents": 500000,
        "housing_payment_cents": 150000,
    }
    defaults.update(overrides)
    return defaults


def open_session_payload(counselor_id, session_type="BUDGET_INTAKE", **overrides) -> dict:
    defaults = {
        "counselor_id": counselor_id,
        "session_type": session_type,
    }
    defaults.update(overrides)
    return defaults


def create_debt_account_payload(creditor_id, **overrides) -> dict:
    defaults = {
        "creditor_id": creditor_id,
        "account_ref": "A-1",
        "original_balance_cents": 300000,
        "original_apr": 0.2499,
        "min_payment_cents": 9000,
        "proposed_monthly_payment_cents": 30000,
        "requested_concession_apr": 0.0699,
    }
    defaults.update(overrides)
    return defaults


def activate_payload(expected_client_version, **overrides) -> dict:
    defaults = {"expected_client_version": expected_client_version}
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def counter_payload(countered_concession_apr, **overrides) -> dict:
    defaults = {"countered_concession_apr": countered_concession_apr}
    defaults.update(overrides)
    return defaults


def resubmit_payload(requested_concession_apr, **overrides) -> dict:
    defaults = {"requested_concession_apr": requested_concession_apr}
    defaults.update(overrides)
    return defaults
