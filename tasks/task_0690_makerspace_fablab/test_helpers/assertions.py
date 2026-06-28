"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Append-only WalletEntry carries only id + created_at
(no updated_at, no version), per PRD §2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_membership_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert data["billing_mode"] in ("DAYPASS", "MONTHLY")
    for f in ("monthly_fee_cents", "daypass_fee_cents", "prepaid_machine_minutes", "locker_free_liters"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative int"
    assert 0 <= data["discount_bps"] <= 10000
    assert isinstance(data["unsupervised_allowed"], bool)


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert data["subscription_status"] in (
        "PENDING_WAIVER", "ACTIVE", "SUSPENDED", "CANCELLED",
    )
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["prepaid_minutes_remaining"], int) and data["prepaid_minutes_remaining"] >= 0
    assert isinstance(data["daypass_count_window"], int) and data["daypass_count_window"] >= 0


def assert_machine(data: dict):
    _assert_common(data)
    assert data["machine_class"] in ("LASER", "CNC", "PRINTER_3D")
    assert data["operational_status"] in ("AVAILABLE", "OUT_OF_SERVICE")
    for f in ("hourly_rate_cents", "setup_fee_cents", "min_billing_minutes", "cooldown_minutes"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_certification(data: dict):
    _assert_common(data)
    assert data["machine_class"] in ("LASER", "CNC", "PRINTER_3D")
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data.get("granted_at", "")), "granted_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert 0.0 <= data["readiness_score"] <= 1.0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["occupancy_status"] in (
        "HELD", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert data["billing_status"] in ("UNBILLED", "HOLD_PLACED", "SETTLED", "REFUNDED")
    assert data["supervision_mode"] in ("SUPERVISED", "UNSUPERVISED")
    assert isinstance(data["reserved_minutes"], int)


def assert_locker(data: dict):
    _assert_common(data)
    assert data["status"] in ("ASSIGNED", "RELEASED")
    assert isinstance(data["capacity_liters"], int) and data["capacity_liters"] >= 0
    assert isinstance(data["used_liters"], int) and data["used_liters"] >= 0


def assert_material_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0


def assert_material_purchase(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "BILLED", "VOIDED")
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1


def assert_workshop(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "FULL", "RUNNING", "COMPLETED", "CANCELLED")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_workshop_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW", "WITHDRAWN")


def assert_wallet_entry(data: dict):
    """Append-only audit record: id + created_at only (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in (
        "TOPUP", "DEBIT", "REFUND", "DAYPASS", "SUBSCRIPTION", "MATERIAL", "OVERAGE",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)
