"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Every resource carries the standard
system-managed properties (id, created_at, updated_at, version).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_cleanroom(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert data["iso_class"] in ("ISO_5", "ISO_6", "ISO_7", "ISO_8")
    for field in ("particle_alert_limit", "particle_action_limit",
                  "viable_alert_limit", "viable_action_limit", "recert_interval_days"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["particle_action_limit"] > data["particle_alert_limit"]
    assert data["viable_action_limit"] > data["viable_alert_limit"]
    assert data["certification_status"] in (
        "UNCERTIFIED", "CERTIFIED", "CERTIFICATION_EXPIRED", "CERTIFICATION_SUSPENDED")
    assert data["certified_at"] is None or is_iso8601_timestamp(data["certified_at"])
    assert data["environment_posture"] in ("IN_CONTROL", "ALERT", "ACTION", "SHUTDOWN")
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")


def assert_personnel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["role_title"], str) and data["role_title"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_gowning_qualification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("personnel_id", ""))
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert is_iso8601_timestamp(data.get("qualified_at", ""))
    assert is_iso8601_timestamp(data.get("qualification_expires_at", ""))
    assert data["status"] in ("QUALIFIED", "EXPIRED", "REVOKED")


def assert_sampling_point(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert isinstance(data["point_code"], str) and data["point_code"]
    assert data["metric"] in ("PARTICLE", "VIABLE")
    assert data["zone_iso_class"] in ("ISO_5", "ISO_6", "ISO_7", "ISO_8")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_environmental_sample(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sampling_point_id", ""))
    assert isinstance(data["result_value"], int) and data["result_value"] >= 0
    assert is_iso8601_timestamp(data.get("sampled_at", ""))
    assert data["classification"] in ("IN_CONTROL", "ALERT_EXCEEDED", "ACTION_EXCEEDED")
    assert data["triggered_excursion_id"] is None or is_valid_uuid(
        data["triggered_excursion_id"])


def assert_excursion(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert is_valid_uuid(data.get("sampling_point_id", ""))
    assert is_valid_uuid(data.get("sample_id", ""))
    assert data["severity"] in ("ALERT", "ACTION")
    assert isinstance(data["severity_score"], (int, float))
    assert data["recurrence_of_excursion_id"] is None or is_valid_uuid(
        data["recurrence_of_excursion_id"])
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert data["status"] in ("OPEN", "UNDER_INVESTIGATION", "CLOSED")


def assert_investigation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("excursion_id", ""))
    assert isinstance(data["root_cause"], str) and len(data["root_cause"]) >= 20
    assert data["product_impact"] in ("NONE", "POTENTIAL", "CONFIRMED")
    assert data["disposition"] in ("RELEASE", "REJECT", "REWORK")
    assert isinstance(data["investigated_by_user_id"], str)
    assert data["status"] in ("DRAFT", "APPROVED", "REJECTED")


def assert_room_certification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert is_iso8601_timestamp(data.get("executed_at", ""))
    assert isinstance(data["location_mean_values"], list) and data["location_mean_values"]
    assert isinstance(data["grade_passed"], bool)
    assert data["result"] in ("PASS", "FAIL")
    assert data["supersedes_certification_id"] is None or is_valid_uuid(
        data["supersedes_certification_id"])


def assert_material_transfer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert isinstance(data["material_lot"], str) and data["material_lot"]
    assert isinstance(data["item_description"], str) and data["item_description"]
    assert is_iso8601_timestamp(data.get("staged_at", ""))
    assert isinstance(data["dwell_minutes"], int) and data["dwell_minutes"] >= 0
    assert isinstance(data["wiped_down"], bool)
    assert data["status"] in ("STAGED", "INTRODUCED", "REJECTED")


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert isinstance(data["batch_number"], str) and data["batch_number"]
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["status"] in (
        "OPEN", "IN_PROGRESS", "COMPLETE", "RELEASED", "REJECTED", "ON_HOLD")
    assert data["hold_reason"] is None or isinstance(data["hold_reason"], str)


def assert_traveler(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    assert isinstance(data["step_sequence"], int)
    assert isinstance(data["step_description"], str) and data["step_description"]
    assert data["performed_by_user_id"] is None or isinstance(
        data["performed_by_user_id"], str)
    assert data["status"] in ("PENDING", "IN_PROGRESS", "COMPLETE", "VOID")


def assert_entry_log(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("personnel_id", ""))
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert is_iso8601_timestamp(data.get("entered_at", ""))
    assert data["exited_at"] is None or is_iso8601_timestamp(data["exited_at"])


def assert_cleaning_program(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert isinstance(data["method_code"], str) and data["method_code"]
    assert isinstance(data["required_consecutive_passes"], int)
    assert data["required_consecutive_passes"] >= 1
    assert isinstance(data["consecutive_pass_count"], int)
    assert data["consecutive_pass_count"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "VALIDATED", "RE_VALIDATION_REQUIRED")


def assert_cleaning_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    assert data["result"] in ("PASS", "FAIL")
    assert data["verified_by_user_id"] is None or isinstance(
        data["verified_by_user_id"], str)
    assert data["status"] in ("RECORDED", "VERIFIED", "REJECTED")


def assert_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert is_valid_uuid(data.get("cleanroom_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CLOSED")


def assert_audit_finding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("audit_id", ""))
    assert data["severity"] in ("OBSERVATION", "MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str) and data["description"]
    assert data["status"] in ("OPEN", "CAPA_SUBMITTED", "CAPA_VERIFIED")


def assert_severity_score_value(actual, expected: float):
    """Severity scores round half-up to exactly two decimal places (PRD section
    on numeric precision)."""
    import pytest
    assert float(actual) == pytest.approx(expected, abs=1e-9), (
        f"severity_score must be {expected}, got {actual!r}")
    assert round(float(actual), 2) == float(actual), (
        f"severity_score must carry at most two decimal places, got {actual!r}")
