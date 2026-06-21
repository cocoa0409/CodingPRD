"""Payload factories — one per entity, input fields only.

Each factory provides PRD-required input fields with sensible defaults and
accepts **overrides for fields a test needs to control.
"""
from .constants import (
    BASE_POINTS_PER_WEEK,
    BASE_ANNUAL_FEE_CENTS_PER_1000,
)


def create_resort_payload(**overrides) -> dict:
    """POST /resorts. Optional governance fields are omitted so the server
    applies its declared defaults unless explicitly overridden."""
    defaults = {
        "name": "Test Resort",
        "points_per_week_base": BASE_POINTS_PER_WEEK,
        "annual_fee_cents_per_1000_points": BASE_ANNUAL_FEE_CENTS_PER_1000,
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(resort_id, **overrides) -> dict:
    """POST /owners."""
    defaults = {
        "resort_id": resort_id,
        "full_name": "Test Owner",
        "email": "owner@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_unit_payload(resort_id, **overrides) -> dict:
    """POST /inventory-units."""
    defaults = {
        "resort_id": resort_id,
        "unit_label": "Villa 1",
        "week_number": 10,
        "season": "GOLD",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(resort_id, owner_id, **overrides) -> dict:
    """POST /contracts. Defaults to a DEEDED POINTS contract."""
    defaults = {
        "resort_id": resort_id,
        "owner_id": owner_id,
        "ownership_type": "DEEDED",
        "inventory_model": "POINTS",
        "annual_points_allotment": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(contract_id, inventory_unit_id, use_year,
                               expected_points_account_version, **overrides) -> dict:
    """POST /reservations."""
    defaults = {
        "contract_id": contract_id,
        "inventory_unit_id": inventory_unit_id,
        "use_year": use_year,
        "expected_points_account_version": expected_points_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(contract_id, use_year, due_date, **overrides) -> dict:
    """POST /invoices. Defaults to an ANNUAL invoice."""
    defaults = {
        "contract_id": contract_id,
        "source_type": "ANNUAL",
        "use_year": use_year,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(contract_id, amount_cents, **overrides) -> dict:
    """POST /payments."""
    defaults = {
        "contract_id": contract_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_special_assessment_payload(resort_id, total_amount_cents, use_year, **overrides) -> dict:
    """POST /special-assessments."""
    defaults = {
        "resort_id": resort_id,
        "reason": "Roof replacement",
        "total_amount_cents": total_amount_cents,
        "use_year": use_year,
    }
    defaults.update(overrides)
    return defaults


def create_resale_transfer_payload(source_contract_id, buyer_owner_id, transfer_use_year,
                                   transfer_day_of_year, **overrides) -> dict:
    """POST /resale-transfers."""
    defaults = {
        "source_contract_id": source_contract_id,
        "buyer_owner_id": buyer_owner_id,
        "sale_price_cents": 5_000_000,
        "transfer_use_year": transfer_use_year,
        "transfer_day_of_year": transfer_day_of_year,
    }
    defaults.update(overrides)
    return defaults


def bank_points_payload(points, expected_points_account_version, **overrides) -> dict:
    """POST /points-accounts/{id}/bank."""
    defaults = {
        "points": points,
        "expected_points_account_version": expected_points_account_version,
    }
    defaults.update(overrides)
    return defaults


def deposit_exchange_payload(exchange_network, **overrides) -> dict:
    """POST /reservations/{id}/deposit-exchange."""
    defaults = {"exchange_network": exchange_network}
    defaults.update(overrides)
    return defaults


def levy_payload(due_date, **overrides) -> dict:
    """POST /special-assessments/{id}/levy."""
    defaults = {"due_date": due_date}
    defaults.update(overrides)
    return defaults


def set_clock_payload(resort_id, to_iso8601) -> dict:
    """POST /_clock/set_current_utc."""
    return {"resort_id": resort_id, "to_iso8601": to_iso8601}
