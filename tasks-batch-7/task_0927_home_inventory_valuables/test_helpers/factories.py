"""Payload factories — one per resource, input fields only."""
import itertools
from typing import Any, Dict

_email_counter = itertools.count(1)
_checksum_counter = itertools.count(1)

DEFAULTS = {
    "MEMBER_NAME": "Test Member",
    "HOUSEHOLD_NAME": "Test Household",
    "ADDRESS_LABEL": "1 Test Lane",
    "ROOM_NAME": "Test Room",
    "FLOOR_LABEL": "1",
    "ITEM_NAME": "Test Item",
    "CATEGORY": "GENERAL",
    "ACQUIRED_AT": "2025-01-01T00:00:00Z",
    "CAPTURED_AT": "2026-05-01T00:00:00Z",
    "CARRIER_NAME": "Northwind Mutual",
    "POLICY_NUMBER": "NW-0001",
    "EFFECTIVE_FROM": "2026-05-01T00:00:00Z",
}


def unique_email(prefix: str = "member") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_checksum(prefix: str = "sha") -> str:
    return f"{prefix}-{next(_checksum_counter):05d}"


def create_member_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "email": overrides.pop("email", unique_email()),
        "full_name": DEFAULTS["MEMBER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_household_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": DEFAULTS["HOUSEHOLD_NAME"],
        "address_label": DEFAULTS["ADDRESS_LABEL"],
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(household_id: str, tier: str = "PLUS", **overrides) -> Dict[str, Any]:
    payload = {"household_id": household_id, "tier": tier}
    payload.update(overrides)
    return payload


def create_room_payload(household_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "name": DEFAULTS["ROOM_NAME"],
        "floor_label": DEFAULTS["FLOOR_LABEL"],
    }
    payload.update(overrides)
    return payload


def create_item_payload(household_id: str, room_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "room_id": room_id,
        "name": DEFAULTS["ITEM_NAME"],
        "category": DEFAULTS["CATEGORY"],
        "acquired_at": DEFAULTS["ACQUIRED_AT"],
    }
    payload.update(overrides)
    return payload


def create_asset_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "asset_kind": "PHOTO",
        "byte_size": 9000,
        "checksum": unique_checksum(),
        "captured_at": DEFAULTS["CAPTURED_AT"],
    }
    payload.update(overrides)
    return payload


def create_category_schedule_payload(category: str = "GENERAL", **overrides) -> Dict[str, Any]:
    payload = {
        "category": category,
        "useful_life_months": 120,
        "annual_depreciation_pct": 8.0,
        "salvage_floor_pct": 20.0,
        "blanket_sublimit_cents": 900000,
        "appraisal_scope": "GENERAL",
        "serial_required": False,
    }
    payload.update(overrides)
    return payload


def create_appraiser_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "display_name": "Test Appraiser",
        "credential_id": unique_checksum("CRED"),
        "scope_categories": ["GENERAL"],
    }
    payload.update(overrides)
    return payload


def create_appraisal_payload(item_id: str, appraiser_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "item_id": item_id,
        "appraiser_id": appraiser_id,
        "inspection_start_at": "2026-06-10T09:00:00Z",
        "inspection_end_at": "2026-06-10T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_policy_payload(household_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "policy_number": DEFAULTS["POLICY_NUMBER"],
        "deductible_cents": 0,
        "scheduled_allowance_cents": 0,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


def create_package_payload(household_id: str, policy_id: str, **overrides) -> Dict[str, Any]:
    payload = {"household_id": household_id, "policy_id": policy_id}
    payload.update(overrides)
    return payload


def create_claim_payload(
    household_id: str, package_id: str, policy_id: str, affected_room_ids, **overrides
) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "package_id": package_id,
        "policy_id": policy_id,
        "loss_date": "2026-05-01T00:00:00Z",
        "peril": "FIRE",
        "settlement_basis": "ACV",
        "affected_room_ids": list(affected_room_ids),
    }
    payload.update(overrides)
    return payload


def create_claim_line_payload(item_id: str, claimed_quantity: int = 1, **overrides) -> Dict[str, Any]:
    payload = {"item_id": item_id, "claimed_quantity": claimed_quantity}
    payload.update(overrides)
    return payload


def create_estate_plan_payload(household_id: str, executor_member_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "executor_member_id": executor_member_id,
        "valuation_mode": "GROSS",
    }
    payload.update(overrides)
    return payload


def create_allocation_payload(
    item_id: str, disposition: str, quantity: int, expected_estate_plan_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "item_id": item_id,
        "disposition": disposition,
        "quantity": quantity,
        "expected_estate_plan_version": expected_estate_plan_version,
    }
    payload.update(overrides)
    return payload


def create_share_grant_payload(household_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "scope_kind": "HOUSEHOLD",
        "recipient_ref": "agent@carrier.example",
        "redaction_level": "FULL",
        "starts_at": "2026-05-01T00:00:00Z",
        "expires_at": "2026-06-01T00:00:00Z",
        "access_cap": 10,
    }
    payload.update(overrides)
    return payload
