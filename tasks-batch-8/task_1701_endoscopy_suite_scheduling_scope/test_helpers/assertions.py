"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_instants_equal(actual, expected_iso, label="timestamp"):
    """Compare timestamps by instant, tolerant of fractional-digit formatting."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict):
    """PRD §2.5 primary-resource fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_patient(data: dict):
    assert_common_fields(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert "contact_phone" in data


def assert_provider(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["specialty"] in ("GASTROENTEROLOGY", "COLORECTAL_SURGERY")
    assert data["credential_status"] in ("ACTIVE", "SUSPENDED")


def assert_procedure_type(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["base_duration_minutes"] > 0
    assert data["prep_protocol"] in ("NONE", "CLEAR_LIQUIDS", "SPLIT_DOSE")
    assert isinstance(data["colonoscopy_family"], bool)
    assert isinstance(data["adr_relevant"], bool)
    assert data["required_scope_type"] in ("COLONOSCOPE", "GASTROSCOPE", "SIGMOIDOSCOPE")


def assert_room(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["room_class"] in ("STANDARD", "ERCP_CAPABLE")
    assert isinstance(data["supports_anesthesia"], bool)
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_anesthesia_provider(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["credential_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["scheduled_minutes"], int) and data["scheduled_minutes"] >= 0


def assert_scope(data: dict):
    assert_common_fields(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["scope_type"] in ("COLONOSCOPE", "GASTROSCOPE", "SIGMOIDOSCOPE")
    assert data["status"] in (
        "AVAILABLE", "IN_USE", "AWAITING_REPROCESS", "REPROCESSING",
        "QUARANTINED", "OUT_OF_SERVICE",
    )
    assert isinstance(data["use_count"], int) and data["use_count"] >= 0
    assert isinstance(data["is_storage_current"], bool)


def assert_booking(data: dict):
    assert_common_fields(data)
    for field in ("patient_id", "provider_id", "procedure_type_id", "room_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must reference a UUID"
    assert data["status"] in (
        "SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", "CANCELLED",
        "NO_SHOW", "RESCHEDULED", "ABORTED_PREP_INADEQUATE",
    )
    assert data["prep_status"] in (
        "PREP_PENDING", "PREP_CONFIRMED", "PREP_ADEQUATE", "PREP_INADEQUATE",
    )
    assert data["indication"] in ("SCREENING", "SURVEILLANCE", "DIAGNOSTIC")
    assert data["anesthesia_type"] in ("NONE", "MAC", "GENERAL")
    assert isinstance(data["procedure_minutes"], int) and data["procedure_minutes"] > 0
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert is_iso8601_timestamp(data.get("room_block_end", ""))
    assert isinstance(data["notification_flag"], bool)


def assert_scope_usage(data: dict):
    assert_common_fields(data)
    for field in ("booking_id", "scope_id", "patient_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must reference a UUID"
    assert data["status"] in ("ACTIVE", "VOID")
    assert isinstance(data["exposure_flagged"], bool)
    assert is_iso8601_timestamp(data.get("used_at", ""))


def assert_reprocessing_cycle(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("scope_id", ""))
    assert data["status"] in (
        "INITIATED", "PRECLEANED", "CLEANED", "DISINFECTED", "DRIED",
        "COMPLETE", "FAILED",
    )
    assert isinstance(data["is_reculture"], bool)
    assert isinstance(data["requires_extended_soak"], bool)
    assert is_iso8601_timestamp(data.get("initiated_at", ""))


def assert_culture_test(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("scope_id", ""))
    assert is_valid_uuid(data.get("reprocessing_cycle_id", ""))
    assert data["status"] in ("PENDING", "RESULTED")
    assert is_iso8601_timestamp(data.get("sampled_at", ""))


def assert_quarantine_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("scope_id", ""))
    assert is_valid_uuid(data.get("triggering_culture_id", ""))
    assert data["status"] in ("OPEN", "RECULTURING", "RELEASED", "SCOPE_RETIRED")
    assert is_iso8601_timestamp(data.get("opened_at", ""))


def assert_specimen(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data["specimen_type"] in ("POLYP", "BIOPSY", "OTHER")
    assert isinstance(data["container_count"], int) and data["container_count"] >= 1
    assert data["status"] in (
        "COLLECTED", "LABELED", "IN_TRANSIT", "RECEIVED_BY_LAB", "RESULTED",
        "REJECTED_BY_LAB",
    )
    assert is_iso8601_timestamp(data.get("collected_at", ""))


def assert_quality_report(data: dict):
    """PRD §2.5: the report snapshot carries only id + created_at of the common set."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "report must not carry updated_at"
    assert "version" not in data, "report must not carry version"
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["metric_variant"] in ("STRICT", "EXPANDED")


def assert_anesthesia_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("anesthesia_provider_id", ""))
    assert isinstance(data["minutes"], int) and data["minutes"] > 0
    assert data["status"] in ("ASSIGNED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_rate(value, expected, label="rate"):
    """One-decimal round-half-up rate comparison."""
    assert value == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {value}"
    )
