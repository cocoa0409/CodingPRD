"""Entity assertions and domain invariant checkers.

Uses the framework's generic format validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are exactly as named in the PRD.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)


def assert_appliance(data: dict):
    _assert_common(data)
    assert isinstance(data["brand"], str) and len(data["brand"]) > 0
    assert isinstance(data["model"], str) and len(data["model"]) > 0
    assert data["recall_status"] in ("CLEAR", "RECALLED")
    assert isinstance(data["completed_repair_count"], int) and data["completed_repair_count"] >= 0
    assert isinstance(data["health_score"], int)
    assert 0 <= data["health_score"] <= 100, "health_score clamped to 0..100"


def assert_warranty_contract(data: dict):
    _assert_common(data)
    assert data["coverage_type"] in ("MANUFACTURER", "EXTENDED", "HOME_WARRANTY")
    assert isinstance(data["claimed_cents"], int) and data["claimed_cents"] >= 0
    assert isinstance(data["coverage_cap_cents"], int)
    assert_warranty_invariants(data)


def assert_technician(data: dict):
    _assert_common(data)
    assert data["status"] in ("ON_DUTY", "OFF_DUTY")


def assert_truck_stock_item(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["quantity_reserved"], int) and data["quantity_reserved"] >= 0
    assert isinstance(data["quantity_available"], int)
    assert_truck_stock_invariants(data)


def assert_service_request(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "INTAKE", "SCHEDULED", "DIAGNOSED", "APPROVED",
        "AWAITING_PARTS", "COMPLETED", "DECLINED", "SAFETY_HOLD",
    )
    assert data["warranty_routing"] in ("NONE", "MANUFACTURER", "EXTENDED", "HOME_WARRANTY")
    assert isinstance(data["visit_count"], int) and data["visit_count"] >= 0


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")


def assert_estimate(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_APPROVAL", "APPROVED", "DECLINED", "SUPERSEDED")
    assert isinstance(data["estimated_repair_subtotal_cents"], int)


def assert_parts_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("ORDERED", "BACKORDERED", "RECEIVED", "CANCELLED")


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] == "RECORDED"
    assert data["method"] in ("CARD", "CHECK", "CASH")


def assert_recall_notice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "ACTIVE", "RESCINDED")


# ─── Domain invariant checkers ─────────────────────────────────────────────
def assert_truck_stock_invariants(data: dict):
    """quantity_available is always quantity_on_hand minus quantity_reserved (PRD §2.9)."""
    assert data["quantity_available"] == data["quantity_on_hand"] - data["quantity_reserved"], (
        "quantity_available must equal quantity_on_hand - quantity_reserved"
    )
    assert data["quantity_available"] >= 0, "quantity_available must never be negative"


def assert_warranty_invariants(data: dict):
    """remaining_coverage_cents is always coverage_cap_cents minus claimed_cents (PRD §2.9)."""
    assert data["remaining_coverage_cents"] == data["coverage_cap_cents"] - data["claimed_cents"], (
        "remaining_coverage_cents must equal coverage_cap_cents - claimed_cents"
    )
