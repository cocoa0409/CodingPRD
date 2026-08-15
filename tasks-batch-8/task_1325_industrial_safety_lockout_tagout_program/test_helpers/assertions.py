"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_instant_equal(actual: str, expected: str):
    """Clock-stamped instants compare by value, not by string format.

    The PRD pins three fractional digits only for api_request_timestamp,
    created_at, and updated_at (§2.2, §2.5); domain fields stamped from the
    logical clock (activated_at, started_at, expires_at, ...) carry no declared
    string format, so equality is evaluated on the parsed instant.
    """
    def _parse(v):
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC timestamp"
    assert _parse(actual) == _parse(expected), f"{actual!r} != {expected!r} as instants"


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_optional_timestamp(data: dict, field: str):
    if data.get(field) is not None:
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601 when set"


def assert_machine(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["area"], str) and data["area"]
    assert data["risk_window_policy"] in ["ROLLING_12MO", "SINCE_PROCEDURE_ACTIVATION"]
    assert data["status"] in ["IN_SERVICE", "OUT_OF_SERVICE"]
    assert isinstance(data["risk_score"], int) and data["risk_score"] >= 0
    assert data["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["open_session_count"], int) and data["open_session_count"] >= 0


def assert_machine_modification(data: dict):
    # Append-only log (PRD §2.5): only id and created_at of the common fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "modifications carry no updated_at field"
    assert "version" not in data, "modifications carry no version field"
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    assert isinstance(data["description"], str) and data["description"]
    assert data["review_status"] in ["UNREVIEWED", "REVIEWED"]


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_no"], str) and data["employee_no"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["qualification"] in ["AFFECTED", "AUTHORIZED"]
    assert data["status"] == "ACTIVE"
    assert isinstance(data["is_currently_qualified"], bool)
    assert isinstance(data["outstanding_lock_count"], int) \
        and data["outstanding_lock_count"] >= 0


def assert_energy_survey(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    assert isinstance(data["surveyed_by_employee_id"], str) \
        and data["surveyed_by_employee_id"]
    assert isinstance(data["energy_sources"], list) and len(data["energy_sources"]) >= 1
    for source in data["energy_sources"]:
        for key in ("source_type", "magnitude", "isolation_point", "dissipation_method"):
            assert key in source, f"energy source missing {key}"
    assert data["isolation_point_count"] == len(data["energy_sources"])
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]


def assert_lockout_procedure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    assert isinstance(data["survey_id"], str) and data["survey_id"]
    assert isinstance(data["steps"], list) and len(data["steps"]) >= 1
    for step in data["steps"]:
        for key in ("step_no", "action", "isolation_point"):
            assert key in step, f"procedure step missing {key}"
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert isinstance(data["isolation_point_count"], int) \
        and data["isolation_point_count"] >= 1
    assert data["status"] in ["DRAFT", "ACTIVE", "UNDER_REVISION", "SUPERSEDED", "RETIRED"]
    _assert_optional_timestamp(data, "activated_at")
    _assert_optional_timestamp(data, "last_completed_audit_at")
    _assert_optional_timestamp(data, "audit_due_at")


def assert_training_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert data["course_code"] in [
        "LOTO_AUTHORIZED_INITIAL", "LOTO_AUTHORIZED_REFRESH", "LOTO_AFFECTED"]
    assert data["delivery_mode"] in ["IN_PERSON", "ONLINE"]
    assert is_iso8601_timestamp(data["assigned_at"])
    assert is_iso8601_timestamp(data["due_at"])
    _assert_optional_timestamp(data, "completed_at")
    _assert_optional_timestamp(data, "expires_at")
    assert data["status"] in ["ASSIGNED", "COMPLETED"]


def assert_lockout_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    assert isinstance(data["procedure_id"], str) and data["procedure_id"]
    assert isinstance(data["procedure_revision_no"], int) \
        and data["procedure_revision_no"] >= 1
    assert isinstance(data["max_locks"], int) and data["max_locks"] >= 1
    assert data["session_type"] in ["INDIVIDUAL", "GROUP", "CONTRACTOR"]
    assert isinstance(data["primary_employee_id"], str) and data["primary_employee_id"]
    assert isinstance(data["zero_energy_verified"], bool)
    assert isinstance(data["applied_lock_count"], int) and data["applied_lock_count"] >= 0
    _assert_optional_timestamp(data, "started_at")
    _assert_optional_timestamp(data, "ended_at")
    assert data["status"] in ["SETUP", "LOCKED", "CLEARED", "RELEASED", "CANCELLED"]


def assert_employee_lock(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["session_id"], str) and data["session_id"]
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert isinstance(data["lock_no"], str) and data["lock_no"]
    assert isinstance(data["tag_no"], str) and data["tag_no"]
    _assert_optional_timestamp(data, "applied_at")
    _assert_optional_timestamp(data, "removed_at")
    assert data.get("removal_reason") is None or isinstance(data["removal_reason"], str)
    assert data["status"] in ["ISSUED", "APPLIED", "REMOVED", "FORCE_REMOVED", "VOIDED"]


def assert_procedure_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["procedure_id"], str) and data["procedure_id"]
    assert isinstance(data["auditor_employee_id"], str) and data["auditor_employee_id"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert is_iso8601_timestamp(data["period_start"])
    if data.get("result") is not None:
        assert data["result"] in ["PASS", "FAIL"]
    _assert_optional_timestamp(data, "completed_at")
    assert data["status"] in ["SCHEDULED", "COMPLETED"]


def assert_incident_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    if data.get("session_id") is not None:
        assert isinstance(data["session_id"], str)
    assert data["kind"] in ["NEAR_MISS", "FIRST_AID", "INJURY", "PROPERTY_DAMAGE"]
    assert is_iso8601_timestamp(data["occurred_at"])
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    _assert_optional_timestamp(data, "linked_at")
    assert data["status"] in ["REPORTED", "LINKED", "DISMISSED"]


def assert_contractor_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["coordinator_employee_id"], str) \
        and data["coordinator_employee_id"]
    assert is_iso8601_timestamp(data["insurance_valid_until"])
    _assert_optional_timestamp(data, "coordination_meeting_at")
    assert data["status"] in ["REQUESTED", "APPROVED", "ACTIVE", "CLOSED", "REJECTED"]


def assert_minor_servicing_exception(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    assert isinstance(data["requested_by_employee_id"], str) \
        and data["requested_by_employee_id"]
    assert isinstance(data["task_description"], str) and data["task_description"]
    for flag in ("routine_repetitive", "integral_to_production",
                 "alternative_measures_effective"):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"
    assert isinstance(data["estimated_duration_min"], int) \
        and data["estimated_duration_min"] >= 1
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    if data.get("determination") is not None:
        assert data["determination"] in ["ELIGIBLE", "NOT_ELIGIBLE"]
    assert data["status"] in ["PENDING", "DETERMINED", "REVOKED"]
