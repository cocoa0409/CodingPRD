"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validate response shape against the PRD contract.
LedgerEntry and RedemptionLeg are immutable audit records — they carry only id and
created_at (no updated_at, no version), so their assertions never demand those fields.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_LIFECYCLE_STATES = ["INACTIVE", "ACTIVE", "VOIDED", "EXPIRED", "EXHAUSTED"]
_RISK_STATES = ["CLEAR", "FLAGGED", "FROZEN_RISK"]


def _assert_common(data: dict):
    """id/created_at/updated_at/version present for full common-field entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be int >= 1"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["reload_min_cents"], int)
    assert isinstance(data["reload_max_balance_cents"], int)
    assert isinstance(data["outstanding_liability_cents"], int)
    assert isinstance(data["breakage_recognized_cents"], int)
    assert isinstance(data["escheat_liability_cents"], int)


def assert_state_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["expiration_allowed"], bool)
    assert isinstance(data["dormancy_fee_allowed"], bool)
    assert data["breakage_policy"] in ("RECOGNIZE", "ESCHEAT")


def assert_campaign(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "ENDED")


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["is_corporate"], bool)


def assert_gift_card(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in _LIFECYCLE_STATES, \
        f"unexpected lifecycle_status: {data.get('lifecycle_status')}"
    assert data["risk_status"] in _RISK_STATES, \
        f"unexpected risk_status: {data.get('risk_status')}"
    assert data["form_factor"] in ("DIGITAL", "PHYSICAL")
    assert isinstance(data["settled_balance_cents"], int)
    assert isinstance(data["pending_hold_cents"], int)
    assert isinstance(data["available_balance_cents"], int)
    # PRD §2.5: available = settled - pending_hold.
    assert data["available_balance_cents"] == \
        data["settled_balance_cents"] - data["pending_hold_cents"], \
        "available_balance_cents must equal settled_balance_cents - pending_hold_cents"


def assert_authorization_hold(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CAPTURED", "RELEASED", "EXPIRED")
    assert isinstance(data["amount_cents"], int)


def assert_redemption(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SETTLED", "VOIDED")
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["card_id_order"], list)


def assert_bulk_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "CONFIRMED", "ACTIVATED", "CANCELLED")
    assert isinstance(data["card_count"], int)
    assert isinstance(data["face_value_cents"], int)


def assert_replacement_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "APPROVED", "REJECTED")
    assert data["reason"] in ("FRAUD", "LOST", "DAMAGED")


def assert_refund_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "NEEDS_REVISION", "APPLIED", "DENIED")
    assert isinstance(data["requested_refund_cents"], int)


def assert_dormancy_waiver(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_ledger_entry(data: dict):
    """Immutable audit record — only id + created_at; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "LedgerEntry must not carry a version field"
    assert "updated_at" not in data, "LedgerEntry must not carry an updated_at field"
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_redemption_leg(data: dict):
    """Immutable audit record — only id + created_at; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "RedemptionLeg must not carry a version field"
    assert "updated_at" not in data, "RedemptionLeg must not carry an updated_at field"
    assert isinstance(data["leg_amount_cents"], int)
