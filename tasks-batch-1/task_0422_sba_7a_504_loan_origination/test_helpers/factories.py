"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "naics_code": "236220",
    "tangible_net_worth_cents": 1_000_000_000,
    "avg_net_income_cents": 300_000_000,
    "affiliate_employee_count": 50,
    "requested_amount_cents": 50_000_000,
    "guaranty_pct": 0.75,
    "maturity_months": 240,
    "appraised_value_cents": 70_000_000,
    "dscr": 1.35,
    "risk_rating": 3,
}


def create_lender_payload(**overrides) -> dict:
    payload = {"name": "Test CDC", "program": "7A"}
    payload.update(overrides)
    return payload


def create_borrower_payload(lender_id: str, **overrides) -> dict:
    payload = {
        "lender_id": lender_id,
        "legal_name": "Test LLC",
        "naics_code": DEFAULTS["naics_code"],
        "tangible_net_worth_cents": DEFAULTS["tangible_net_worth_cents"],
        "avg_net_income_cents": DEFAULTS["avg_net_income_cents"],
        "affiliate_employee_count": DEFAULTS["affiliate_employee_count"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(borrower_id: str, **overrides) -> dict:
    payload = {
        "borrower_id": borrower_id,
        "requested_amount_cents": DEFAULTS["requested_amount_cents"],
        "guaranty_pct": DEFAULTS["guaranty_pct"],
        "maturity_months": DEFAULTS["maturity_months"],
    }
    payload.update(overrides)
    return payload


def create_proceeds_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "use_category": "REAL_ESTATE",
        "amount_cents": DEFAULTS["requested_amount_cents"],
    }
    payload.update(overrides)
    return payload


def create_collateral_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "asset_type": "REAL_ESTATE",
        "appraised_value_cents": DEFAULTS["appraised_value_cents"],
    }
    payload.update(overrides)
    return payload


def create_form_package_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "form_1919_complete": True,
        "form_1920_complete": True,
        "character_cleared": True,
    }
    payload.update(overrides)
    return payload


def create_credit_memo_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "dscr": DEFAULTS["dscr"],
        "risk_rating": DEFAULTS["risk_rating"],
        "recommendation": "APPROVE",
    }
    payload.update(overrides)
    return payload


def create_disbursement_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "amount_cents": DEFAULTS["requested_amount_cents"],
        "tranche_label": "Initial",
        "draw_window_start_day": 0,
        "draw_window_end_day": 30,
    }
    payload.update(overrides)
    return payload


def create_guaranty_sale_payload(application_id: str, sold_principal_cents: int, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "investor_user_id": "inv-9",
        "sold_principal_cents": sold_principal_cents,
        "premium_bps": 350,
    }
    payload.update(overrides)
    return payload


def create_servicing_report_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "period_index": 0,
        "period_start_month": 0,
        "period_end_month": 0,
        "principal_paid_cents": 0,
        "interest_paid_cents": 100_000,
        "days_past_due": 0,
    }
    payload.update(overrides)
    return payload


def create_liquidation_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "recovery_cents": 24_000_000,
        "expense_cents": 4_000_000,
    }
    payload.update(overrides)
    return payload


def create_guaranty_purchase_payload(application_id: str, claimed_principal_cents: int, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "claimed_principal_cents": claimed_principal_cents,
        "repair_pct": 0,
    }
    payload.update(overrides)
    return payload
