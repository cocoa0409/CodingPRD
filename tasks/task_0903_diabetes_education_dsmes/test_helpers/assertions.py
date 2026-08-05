"""Entity assertions and domain invariant checkers.

Assertions validate structural correctness (UUID id, ISO timestamps, field
types, enum membership) against the PRD's resource shapes.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id/created_at/updated_at/version present on common_fields entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["accreditation_body"] in ("ADA", "ADCES")
    assert data["accreditation_status"] in ("ACCREDITED", "PROBATION", "LAPSED")


def assert_curriculum(data: dict):
    assert_common_fields(data)
    assert data["diabetes_type_focus"] in ("TYPE_1", "TYPE_2", "GESTATIONAL", "PREDIABETES", "ANY")
    assert isinstance(data["required_hours"], (int, float))
    assert isinstance(data["module_count"], int)


def assert_patient(data: dict):
    assert_common_fields(data)
    assert data["diabetes_type"] in ("TYPE_1", "TYPE_2", "GESTATIONAL", "PREDIABETES")
    assert data["payer"] in ("MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY")
    assert isinstance(data["baseline_a1c"], (int, float))


def assert_dietitian(data: dict):
    assert_common_fields(data)
    assert data["credential"] in ("RD", "RN", "CDCES", "PHARMD")
    assert isinstance(data["active"], bool)


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("RECEIVED", "ASSESSED", "ENROLLED", "REJECTED")


def assert_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "COMPLETED", "WITHDRAWN")
    assert isinstance(data["provisional_hours_used"], (int, float))
    assert isinstance(data["final_hours_used"], (int, float))
    assert isinstance(data["no_show_count"], int)


def assert_session(data: dict):
    assert_common_fields(data)
    assert data["encounter_status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "SUBMITTED", "PAID", "DENIED")
    assert data["modality"] in ("INDIVIDUAL", "GROUP")


def assert_group_class(data: dict):
    assert_common_fields(data)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["seats_taken"], int)


def assert_device_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "ACTIVE", "RETURNED", "EXPIRED")
    assert data["device_type"] in ("CGM", "INSULIN_PUMP", "SMART_PEN")


def assert_device_reading(data: dict):
    """DeviceReading is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "DeviceReading must not carry version"
    assert "updated_at" not in data, "DeviceReading must not carry updated_at"


def assert_care_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "REVISED", "MET", "NOT_MET")
    assert isinstance(data["revision_count"], int)
