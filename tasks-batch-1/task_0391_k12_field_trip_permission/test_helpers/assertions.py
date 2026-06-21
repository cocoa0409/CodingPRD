"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates structural shape against the PRD contract using
the framework's generic format validators. Invariant checkers encode the
conserved-quantity disciplines the PRD declares (cash, seats, scholarship funds).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_TRIP_STATUSES = [
    "DRAFT", "PENDING_PRINCIPAL", "PENDING_DISTRICT", "APPROVED",
    "ROSTER_LOCKED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
]


def assert_field_trip(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in _TRIP_STATUSES, f"unexpected status {data['status']}"
    assert data["grade_band"] in ["ELEMENTARY", "MIDDLE", "HIGH"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["signed_count"], int) and data["signed_count"] >= 0
    assert isinstance(data["collected_fees_cents"], int)
    assert isinstance(data["required_chaperones"], int) and data["required_chaperones"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_permission_slip(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["signature_status"] in ["UNSIGNED", "SIGNED", "REVOKED"]
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert data["participation_status"] in ["PENDING", "CONFIRMED", "WITHDRAWN"]
    assert isinstance(data["fee_due_cents"], int)
    assert isinstance(data["scholarship_award_cents"], int)
    assert isinstance(data["net_paid_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_vehicle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["seats_reserved"], int) and data["seats_reserved"] >= 0
    assert data["seats_reserved"] <= data["seat_capacity"], "seats_reserved must not exceed capacity"


def assert_scholarship_pool(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["granted_cents"], int) and data["granted_cents"] >= 0
    assert isinstance(data["remaining_cents"], int)
    assert data["remaining_cents"] == data["total_cents"] - data["granted_cents"], (
        "remaining_cents must equal total_cents - granted_cents"
    )


def assert_chaperone(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["INVITED", "CONFIRMED", "CLEARED", "WITHDRAWN"]


def assert_transport_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["REQUESTED", "CONFIRMED", "CANCELLED"]
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1


def assert_scholarship_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "REVOKED"]
    assert isinstance(data["award_cents"], int) and data["award_cents"] >= 1


def assert_append_only_record(data: dict):
    """Records carrying ONLY id + created_at (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"
