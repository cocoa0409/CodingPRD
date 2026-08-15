"""Entity assertions and domain invariant checkers.

Structural assertions cover only properties the PRD pins down verbatim:
identifier/timestamp shapes (PRD §2.11), status vocabularies, and field
presence. Computed values themselves are asserted in the test files where a
PRD sentence fixes the expected number.
"""
from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert_timestamp_format(data.get("created_at", ""))
    assert_timestamp_format(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """PRD §2.11: append-only records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert_timestamp_format(data.get("created_at", ""))
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_isotope_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["half_life_minutes"], (int, float))
    assert data["half_life_minutes"] > 0
    assert isinstance(data["decay_constant_per_minute"], (int, float))
    assert isinstance(data["spill_major_threshold_mbq"], (int, float))
    assert isinstance(data["release_activity_limit_mbq"], (int, float))
    assert isinstance(data["min_usable_activity_mbq"], (int, float))


def assert_license(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["max_possession_mbq"], (int, float))
    assert isinstance(data["isotope_conditions"], list)
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["current_possession_mbq"], (int, float))
    assert data["current_possession_mbq"] >= 0


def assert_authorized_user(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data["license_id"])
    assert data["scope"] in ("DIAGNOSTIC", "THERAPEUTIC", "BOTH")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["weight_kg"], (int, float)) and data["weight_kg"] > 0


def assert_imaging_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cleanup_buffer_minutes"], int)
    assert data["status"] in ("OPERATIONAL", "CONTAMINATED")


def assert_isotope_delivery(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["isotope_product_id"])
    assert is_iso8601_timestamp(data["scheduled_arrival_at"])
    assert is_iso8601_timestamp(data["reference_time_at"])
    assert isinstance(data["reference_activity_mbq"], (int, float))
    assert data["status"] in ("SCHEDULED", "RECEIVED", "FAILED")


def assert_dose_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["isotope_product_id"])
    assert is_valid_uuid(data["authorized_user_id"])
    assert data["use_type"] in ("DIAGNOSTIC", "THERAPEUTIC")
    assert isinstance(data["prescribed_activity_mbq"], (int, float))
    assert is_iso8601_timestamp(data["administration_scheduled_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in (
        "ORDERED", "DOSE_PREPARED", "ON_HOLD",
        "ADMINISTERED", "CANCELLED", "SUPERSEDED", "EXPIRED",
    )


def assert_dose_vial(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["delivery_id"])
    assert is_iso8601_timestamp(data["prepared_at"])
    assert isinstance(data["required_activity_mbq"], (int, float))
    assert data["status"] in (
        "PREPARED", "CALIBRATED", "QUARANTINED",
        "DECAYED", "ADMINISTERED", "DISPOSED",
    )


def assert_dose_administration(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["vial_id"])
    assert is_iso8601_timestamp(data["administered_at"])
    assert isinstance(data["administered_by_user_id"], str)
    assert isinstance(data["assayed_activity_exact_mbq"], (int, float))
    assert isinstance(data["assayed_activity_tabular_mbq"], (int, float))
    assert isinstance(data["within_admin_window"], bool)


def assert_procedure_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["room_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED", "AUTO_VOIDED")


def assert_waste_container(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["isotope_product_id"])
    assert is_valid_uuid(data["room_id"])
    assert data["status"] in ("FILLING", "SEALED", "CLEARED")
    assert isinstance(data["intake_activity_mbq"], (int, float))
    assert isinstance(data["current_activity_mbq"], (int, float))


def assert_radiation_survey(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["room_id"])
    assert is_iso8601_timestamp(data["surveyed_at"])
    assert isinstance(data["ambient_dose_rate_usv_h"], (int, float))
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["performed_by_user_id"], str)


def assert_spill_incident(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["isotope_product_id"])
    assert isinstance(data["estimated_activity_mbq"], (int, float))
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["classification"] in ("MINOR", "MAJOR")
    assert isinstance(data["reported_by_user_id"], str)
    assert data["status"] in ("REPORTED", "CONTAINED", "DECONTAMINATED", "CLEARED")


def assert_patient_release_instruction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["administration_id"])
    assert data["evaluation_variant"] in ("ACTIVITY_BASED", "MEASURED_RATE_BASED")
    assert data["releasable"] is True, "instructions exist only for releasable patients"
    assert data["status"] == "ISSUED", "ISSUED is the only status an instruction carries"
    assert isinstance(data["issued_by_user_id"], str)
