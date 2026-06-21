"""Payload factories — one per entity, input fields only.

Each factory returns a dict of input-source fields; overrides win. Optional input fields
(those with defaults in the PRD) are omitted unless explicitly supplied so the server's
defaulting can be exercised.
"""
import itertools

# Monotone EIN generator so independent factory calls in one test never collide.
_ein_counter = itertools.count(1)


def _next_ein() -> str:
    n = next(_ein_counter)
    return f"99-{n:07d}"


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "name": "Test DAF Program",
        "ein": _next_ein(),
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(sponsor_id: str, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "name": "Test Pool",
        "risk_tier": "BALANCED",
        "nav_per_unit_cents": 2500,
        "fee_bps": 50,
    }
    defaults.update(overrides)
    return defaults


def create_nav_period_payload(investment_pool_id: str, from_quarter: int, to_quarter: int, **overrides) -> dict:
    defaults = {
        "investment_pool_id": investment_pool_id,
        "from_quarter": from_quarter,
        "to_quarter": to_quarter,
        "nav_per_unit_cents": 2500,
    }
    defaults.update(overrides)
    return defaults


def create_charity_payload(sponsor_id: str, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "legal_name": "Test Charity",
        "ein": _next_ein(),
        "ntee_code": "A20",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(sponsor_id: str, primary_advisor_user_id: str, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "account_name": "Test Donor Fund",
        "primary_advisor_user_id": primary_advisor_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_cash_contribution_payload(donor_account_id: str, cash_amount_cents: int, **overrides) -> dict:
    defaults = {
        "donor_account_id": donor_account_id,
        "asset_type": "CASH",
        "cash_amount_cents": cash_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_securities_contribution_payload(donor_account_id: str, quantity_milli: int, **overrides) -> dict:
    defaults = {
        "donor_account_id": donor_account_id,
        "asset_type": "SECURITIES",
        "ticker": "ACME",
        "quantity_milli": quantity_milli,
    }
    defaults.update(overrides)
    return defaults


def create_crypto_contribution_payload(donor_account_id: str, quantity_milli: int, spot_price_cents: int, **overrides) -> dict:
    defaults = {
        "donor_account_id": donor_account_id,
        "asset_type": "CRYPTO",
        "ticker": "BTC",
        "quantity_milli": quantity_milli,
        "spot_price_cents": spot_price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_rebalance_order_payload(donor_account_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "donor_account_id": donor_account_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(donor_account_id: str, charity_id: str, amount_cents: int,
                         expected_account_version: int, **overrides) -> dict:
    defaults = {
        "donor_account_id": donor_account_id,
        "charity_id": charity_id,
        "amount_cents": amount_cents,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_succession_plan_payload(donor_account_id: str, plan_type: str, beneficiaries: list, **overrides) -> dict:
    defaults = {
        "donor_account_id": donor_account_id,
        "plan_type": plan_type,
        "beneficiaries": beneficiaries,
    }
    defaults.update(overrides)
    return defaults


def vet_decision_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
