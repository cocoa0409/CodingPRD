"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import DEFAULT_ISSUED_AT, DEFAULT_DUE_AT

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Owner",
        "dmv_customer_id": _uniq("DMV"),
        "email": "owner@example.com",
        "mailing_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "plate_number": _uniq("PLT"),
        "plate_state": "CA",
        "vin": _uniq("VIN"),
    }
    defaults.update(overrides)
    return defaults


def create_hearing_officer_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Officer"}
    defaults.update(overrides)
    return defaults


def create_tow_yard_payload(**overrides) -> dict:
    defaults = {"name": "Test Yard", "capacity": 5}
    defaults.update(overrides)
    return defaults


def create_case_payload(vehicle_id: str, **overrides) -> dict:
    defaults = {"vehicle_id": vehicle_id}
    defaults.update(overrides)
    return defaults


def create_violation_payload(**overrides) -> dict:
    defaults = {
        "citation_number": _uniq("CIT"),
        "violation_type": "METER_EXPIRED",
        "fine_amount_cents": 25000,
        "issued_at": DEFAULT_ISSUED_AT,
        "due_at": DEFAULT_DUE_AT,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"reason": "I contest this citation."}
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 10000, "method": "CARD"}
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(expected_scofflaw_case_version: int, **overrides) -> dict:
    defaults = {
        "expected_scofflaw_case_version": expected_scofflaw_case_version,
        "total_amount_cents": 100000,
        "installment_count": 9,
        "down_payment_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_boot_tow_order_payload(expected_scofflaw_case_version: int, action_type: str = "BOOT",
                                  **overrides) -> dict:
    defaults = {
        "expected_scofflaw_case_version": expected_scofflaw_case_version,
        "action_type": action_type,
    }
    defaults.update(overrides)
    return defaults


def create_hardship_waiver_payload(hardship_tier: str = "TIER_1", **overrides) -> dict:
    defaults = {"hardship_tier": hardship_tier, "requested_amount_cents": 10000}
    defaults.update(overrides)
    return defaults


def create_collections_referral_payload(**overrides) -> dict:
    defaults = {"agency_name": "Test Collections Agency"}
    defaults.update(overrides)
    return defaults
