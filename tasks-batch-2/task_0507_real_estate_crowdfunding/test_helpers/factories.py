"""Payload factories — one per create endpoint, input fields only (PRD §4 / §3)."""
import itertools

from .constants import BIG_INCOME_CENTS, BIG_NET_WORTH_CENTS

_email_counter = itertools.count(1)


def unique_email(prefix: str = "inv") -> str:
    """A unique investor email per call (email is globally unique, PRD §3.3)."""
    return f"{prefix}{next(_email_counter)}@example.com"


def create_fund_payload(**overrides) -> dict:
    """Input fields for POST /funds (name, vehicle_type, gross/liabilities)."""
    payload = {
        "name": "Test Fund",
        "vehicle_type": "REIT",
        "gross_asset_value_cents": 0,
        "total_liabilities_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_share_class_payload(**overrides) -> dict:
    """Input fields for POST /funds/{id}/share-classes.
    accredited_only and drip_eligible are optional (defaults false / true, PRD §3.2)."""
    payload = {
        "class_code": "A",
        "min_investment_cents": 100_000,
        "mgmt_fee_bps": 100,
    }
    payload.update(overrides)
    return payload


def create_project_payload(**overrides) -> dict:
    """Input fields for POST /funds/{id}/projects."""
    payload = {
        "name": "Test Project",
        "acquisition_cost_cents": 1_000_000,
        "appraised_value_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def create_investor_payload(**overrides) -> dict:
    """Input fields for POST /investors. accredited_status optional (defaults NON_ACCREDITED).
    Defaults to an accredited, high-income investor so generic setups are not cap-limited."""
    payload = {
        "email": unique_email(),
        "full_name": "Test Investor",
        "accredited_status": "ACCREDITED",
        "annual_income_cents": BIG_INCOME_CENTS,
        "net_worth_cents": BIG_NET_WORTH_CENTS,
    }
    payload.update(overrides)
    return payload


def create_valuation_payload(**overrides) -> dict:
    """Input fields for POST /funds/{id}/valuations."""
    payload = {
        "period_label": "2026-Q1",
        "gross_asset_value_cents": 1_000_000,
        "total_liabilities_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_distribution_payload(**overrides) -> dict:
    """Input fields for POST /funds/{id}/distributions."""
    payload = {
        "period_label": "2026-Q1",
        "dividend_per_share_cents": 1.5,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(investor_id, share_class_id, funded_amount_cents,
                                expected_fund_version, **overrides) -> dict:
    """Input fields for POST /subscriptions. drip_elected optional (defaults false).
    expected_fund_version is required (OCC guard, PRD §2.6)."""
    payload = {
        "investor_id": investor_id,
        "share_class_id": share_class_id,
        "funded_amount_cents": funded_amount_cents,
        "expected_fund_version": expected_fund_version,
    }
    payload.update(overrides)
    return payload


def create_redemption_request_payload(holding_id, shares_requested,
                                      expected_holding_version, **overrides) -> dict:
    """Input fields for POST /redemption-requests. expected_holding_version required (OCC, §2.6)."""
    payload = {
        "holding_id": holding_id,
        "shares_requested": shares_requested,
        "expected_holding_version": expected_holding_version,
    }
    payload.update(overrides)
    return payload


def create_tax_document_payload(fund_id, tax_year, **overrides) -> dict:
    """Input fields for POST /investors/{id}/tax-documents."""
    payload = {
        "fund_id": fund_id,
        "tax_year": tax_year,
    }
    payload.update(overrides)
    return payload
