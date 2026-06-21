"""Entity assertions and domain invariant checkers.

These validate the shape and field types of returned resources against the PRD's
entity model, using the framework's generic validators internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """First-class records carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_immutable_common_fields(data: dict):
    """Immutable records carry only id + created_at (PRD §2.4); no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_guardian(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["home_zip"], str)


def assert_child(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["guardian_id"], str)
    assert isinstance(data["first_name"], str)
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1


def assert_emergency_contact(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["child_id"], str)
    assert isinstance(data["contact_name"], str)
    assert isinstance(data["contact_phone"], str)
    assert isinstance(data["relationship"], str)


def assert_authorization_form(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["child_id"], str)
    assert data["form_type"] in ("MEDICAL", "PICKUP")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REVOKED")


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["program_type"] in ("AFTERSCHOOL", "CAMP")
    assert isinstance(data["min_age"], int)
    assert isinstance(data["max_age"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")


def assert_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["age_group_min"], int)
    assert isinstance(data["age_group_max"], int)
    assert isinstance(data["weekly_capacity"], int) and data["weekly_capacity"] >= 1
    assert isinstance(data["base_weekly_tuition_cents"], int) and data["base_weekly_tuition_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")


def assert_weekly_offering(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["week_start"], str)
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0
    assert data["capacity_state"] in ("AVAILABLE", "FULL")
    assert data["weather_state"] in ("NORMAL", "RAIN_ACTIVATED")


def assert_scholarship_award(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["child_id"], str)
    assert data["tier"] in ("NONE", "PARTIAL", "FULL")
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "REVOKED")
    assert 0 <= data["approved_discount_pct"] <= 1


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["child_id"], str)
    assert isinstance(data["weekly_offering_id"], str)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "WAITLISTED", "WITHDRAWN")
    assert isinstance(data["provisional_tuition_cents"], int) and data["provisional_tuition_cents"] >= 0
    assert isinstance(data["final_tuition_cents"], int) and data["final_tuition_cents"] >= 0


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["guardian_id"], str)
    assert isinstance(data["billing_period"], str)
    assert data["status"] in ("DRAFT", "FINALIZED", "PAID", "VOID")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["sibling_discount_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_payment(data: dict):
    _assert_immutable_common_fields(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["method"] in ("CARD", "ACH", "WALLET")
    # Immutable record: no version / updated_at.
    assert "version" not in data, "Payment is immutable and must not expose a version field"
    assert "updated_at" not in data, "Payment is immutable and must not expose an updated_at field"


def assert_weather_event(data: dict):
    _assert_immutable_common_fields(data)
    assert isinstance(data["weekly_offering_id"], str)
    assert isinstance(data["moved_enrollment_count"], int) and data["moved_enrollment_count"] >= 0
    assert "version" not in data, "WeatherEvent is immutable and must not expose a version field"
    assert "updated_at" not in data, "WeatherEvent is immutable and must not expose an updated_at field"


def assert_invoice_total_floor(data: dict):
    """PRD §3.6: total_due_cents is the subtotal minus sibling discount, floored at 0."""
    assert data["total_due_cents"] >= 0, "total_due_cents must be floored at 0"
    assert data["total_due_cents"] == max(0, data["subtotal_cents"] - data["sibling_discount_cents"]), (
        "total_due_cents must equal max(0, subtotal_cents - sibling_discount_cents)"
    )
