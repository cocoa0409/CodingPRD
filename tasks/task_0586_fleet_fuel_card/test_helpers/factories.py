"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_PLATE_SEQ = {"n": 0}


def _next_plate() -> str:
    _PLATE_SEQ["n"] += 1
    return f"PLT{_PLATE_SEQ['n']:04d}"


def set_clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc (PRD §2.4)."""
    return {"to_iso8601": to_iso8601}


def create_fleet_account_payload(**overrides) -> dict:
    """POST /fleet-accounts (PRD §3.1). rebate_tiers and status are optional."""
    payload = {
        "company_name": "Test Fleet Co",
        "base_jurisdiction": "CA",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(fleet_account_id: str, **overrides) -> dict:
    """POST /vehicles (PRD §3.1). starting_odometer is optional (defaults to 0)."""
    payload = {
        "fleet_account_id": fleet_account_id,
        "plate": _next_plate(),
        "tank_capacity_gallons": TEST_DEFAULTS["TANK_CAPACITY_GALLONS"],
        "expected_mpg_min": 1,
        "expected_mpg_max": 50,
        "home_jurisdiction": "CA",
        "starting_odometer": 0,
    }
    payload.update(overrides)
    return payload


def create_driver_payload(fleet_account_id: str, **overrides) -> dict:
    """POST /drivers (PRD §3.1). status is optional (defaults to ACTIVE)."""
    payload = {
        "fleet_account_id": fleet_account_id,
        "full_name": "Test Driver",
        "pin": "1234",
    }
    payload.update(overrides)
    return payload


def create_fuel_card_payload(fleet_account_id: str, **overrides) -> dict:
    """POST /fuel-cards (PRD §3.2). The hour window fields are optional."""
    payload = {
        "fleet_account_id": fleet_account_id,
        "last4": "1111",
        "allowed_products": ["DIESEL"],
        "daily_dollar_limit_cents": TEST_DEFAULTS["DAILY_LIMIT_CENTS"],
        "per_txn_gallon_limit": TEST_DEFAULTS["PER_TXN_GALLON_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_card_assignment_payload(card_id: str, vehicle_id: str, driver_id: str,
                                   expected_card_version: int, **overrides) -> dict:
    """POST /card-assignments (PRD §3.3). effective_to is optional (null = open-ended)."""
    payload = {
        "card_id": card_id,
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "expected_card_version": expected_card_version,
    }
    payload.update(overrides)
    return payload


def authorize_transaction_payload(card_id: str, **overrides) -> dict:
    """POST /transactions/authorize (PRD §3.4)."""
    payload = {
        "card_id": card_id,
        "product": "DIESEL",
        "gallons": 10,
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "odometer": 10,
        "jurisdiction": "CA",
    }
    payload.update(overrides)
    return payload


def create_telematics_fault_payload(vehicle_id: str, **overrides) -> dict:
    """POST /telematics-faults (PRD §3.7). The window bounds are required only
    when severity is CRITICAL."""
    payload = {
        "vehicle_id": vehicle_id,
        "fault_code": "P0301",
        "severity": "WARN",
    }
    payload.update(overrides)
    return payload


def create_ifta_report_payload(fleet_account_id: str, quarter: str = "2026-Q1", **overrides) -> dict:
    """POST /ifta-reports (PRD §3.9)."""
    payload = {"fleet_account_id": fleet_account_id, "quarter": quarter}
    payload.update(overrides)
    return payload


def resolution_note_payload(note: str = "analyst note") -> dict:
    """Optional body for confirm/dismiss/reopen on a fraud alert (PRD §3.6)."""
    return {"resolution_note": note}
