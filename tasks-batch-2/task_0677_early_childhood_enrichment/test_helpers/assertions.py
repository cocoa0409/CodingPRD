"""Entity assertions and domain invariant checkers.

Built on the framework's generic validators. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at present and well-formed (all entities carry these)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def _assert_versioned(data: dict):
    """updated_at + version present (entities with common_fields:true)."""
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be int, got {data.get('version')!r}"


def assert_family(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["account_email"], str) and data["account_email"]
    assert isinstance(data["primary_contact_name"], str)
    assert isinstance(data["child_count"], int) and data["child_count"] >= 0


def assert_child(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["family_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["current_level"], int)
    assert data["status"] in ("ENROLLED_ELIGIBLE", "WITHDRAWN")


def assert_membership(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["family_id"])
    assert data["tier"] in ("CORE", "PLUS", "UNLIMITED")
    assert data["status"] in ("PENDING_PAYMENT", "ACTIVE", "FROZEN", "CANCELLED")
    assert isinstance(data["makeup_credit_balance"], int) and data["makeup_credit_balance"] >= 0
    assert isinstance(data["monthly_base_fee_cents"], int)


def assert_program(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["level_index"], int) and data["level_index"] >= 0
    assert isinstance(data["min_age_months"], int)
    assert isinstance(data["max_age_months"], int)
    assert data["max_age_months"] > data["min_age_months"]
    assert isinstance(data["tuition_cents"], int) and data["tuition_cents"] >= 0


def assert_room(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["physical_capacity"], int) and data["physical_capacity"] >= 1


def assert_instructor(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certified_level_indices"], list)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_class_session(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in ("SCHEDULED", "HELD", "CANCELLED")


def assert_enrollment(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["child_id"])
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["membership_id"])
    assert data["kind"] in ("TRIAL", "RECURRING")
    assert data["status"] in ("ENROLLED", "WAITLISTED", "CANCELLED")


def assert_attendance_record(data: dict):
    """common_fields:false — only id + created_at are guaranteed system fields."""
    _assert_common(data)
    assert data["outcome"] in ("PRESENT", "ABSENT", "EXCUSED")


def assert_makeup_credit(data: dict):
    """common_fields:false — only id + created_at are guaranteed system fields."""
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "REDEEMED", "EXPIRED")


def assert_facility_booking(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["family_id"])
    assert data["booking_type"] in ("BIRTHDAY_PARTY", "OPEN_GYM")
    assert data["status"] in ("CONFIRMED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["membership_id"])
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["sibling_discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] >= 0, "total_cents is floored at 0"
    assert data["status"] in ("OPEN", "PAID", "VOID")
