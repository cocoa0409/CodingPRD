"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Standard system-managed fields carried by every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_optional_timestamp(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def _assert_iso_date(data: dict, field: str):
    value = data.get(field, "")
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a YYYY-MM-DD date, got {value!r}"
    )


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["location"], str)
    assert isinstance(data["annual_hours_worked"], int) and data["annual_hours_worked"] > 0
    assert data["safety_posture"] in ("NORMAL", "RESTRICTED", "FROZEN")
    assert data.get("current_active_plan_id") is None or is_valid_uuid(data["current_active_plan_id"])
    assert isinstance(data["issued_permit_count"], int) and data["issued_permit_count"] >= 0
    assert isinstance(data["open_deficiency_count"], int) and data["open_deficiency_count"] >= 0


def assert_safety_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    _assert_iso_date(data, "effective_date")
    assert isinstance(data["revision_notes"], str)
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    _assert_optional_timestamp(data, "activated_at")


def assert_worker(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["employer_type"] in ("DIRECT", "SUBCONTRACTOR")
    assert isinstance(data["is_supervisor"], bool)
    assert data["status"] in (
        "PENDING_ORIENTATION", "ORIENTED", "CLEARED", "SUSPENDED", "REMOVED",
    )
    _assert_optional_timestamp(data, "orientation_completed_at")


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["worker_id"])
    assert data["cert_type"] in ("OSHA_10", "OSHA_30", "FIRST_AID", "FLAGGING")
    _assert_iso_date(data, "issued_date")
    _assert_iso_date(data, "expires_date")
    assert data["status"] in ("UNVERIFIED", "VERIFIED", "EXPIRED")


def assert_subcontractor(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["trade"], str)
    assert data["standing"] in ("GOOD_STANDING", "PROBATION", "REMOVED")
    for field in ("compliance_score_realtime", "compliance_score_period_90d"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert 0 <= data[field] <= 100, f"{field} must be clamped to 0..100 (PRD §3.7)"


def assert_huddle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    _assert_iso_date(data, "huddle_date")
    assert isinstance(data["topics"], str)
    assert data["status"] in ("SCHEDULED", "CONDUCTED", "MISSED")
    assert isinstance(data["attendee_worker_ids"], list)
    _assert_optional_timestamp(data, "conducted_at")


def assert_jha(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["huddle_id"])
    assert isinstance(data["task_description"], str)
    assert data["status"] in ("DRAFT", "APPROVED", "RE_REVIEW_REQUIRED")


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["inspection_type"] in ("DAILY", "WEEKLY", "QUARTERLY_REGULATORY")
    assert data["status"] in ("DUE", "OVERDUE", "COMPLETED")
    _assert_optional_timestamp(data, "completed_at")
    assert isinstance(data["findings_summary"], str)


def assert_deficiency(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["inspection_id"])
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["description"], str)
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL", "IMMINENT_DANGER")
    assert is_iso8601_timestamp(data["due_at"]), "due_at must be ISO 8601 UTC"
    assert data["status"] in ("OPEN", "OVERDUE", "CORRECTION_SUBMITTED", "VERIFIED_CLOSED")
    assert isinstance(data["correction_notes"], str)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    if data.get("closed_disposition") is not None:
        assert data["closed_disposition"] in ("CONFIRMED", "NOT_SUB_FAULT")


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["incident_type"] in ("INJURY", "ILLNESS", "NEAR_MISS", "PROPERTY_DAMAGE")
    assert data["severity"] in ("MINOR", "SERIOUS", "CRITICAL", "FATALITY")
    assert is_iso8601_timestamp(data["occurred_at"])
    assert isinstance(data["work_related"], bool)
    assert data["status"] in (
        "REPORTED", "UNDER_INVESTIGATION", "DETERMINATION_MADE", "CLOSED",
    )
    if data.get("is_osha_recordable") is not None:
        assert isinstance(data["is_osha_recordable"], bool)


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["jha_id"])
    assert data["permit_type"] in ("FALL_PROTECTION", "EXCAVATION", "HOT_WORK")
    assert is_iso8601_timestamp(data["work_start"])
    assert is_iso8601_timestamp(data["work_end"])
    assert isinstance(data["authorized_worker_ids"], list)
    assert data["status"] in ("REQUESTED", "ISSUED", "SUSPENDED", "CLOSED", "EXPIRED")
    assert isinstance(data["suspension_reason"], str)


def assert_drug_test_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["worker_id"])
    assert data["test_type"] in ("PRE_EMPLOYMENT", "RANDOM", "POST_INCIDENT")
    assert is_iso8601_timestamp(data["collected_at"])
    assert data["status"] in ("PENDING_RESULT", "NEGATIVE", "POSITIVE")
    if data.get("window_compliant") is not None:
        assert isinstance(data["window_compliant"], bool)


def assert_osha_summary(data: dict):
    assert isinstance(data["year"], int)
    assert isinstance(data["hours_worked"], int) and data["hours_worked"] > 0
    for field in (
        "recordable_count_final", "recordable_count_provisional",
        "dart_count_final", "dart_count_provisional",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    for field in (
        "trir_final", "trir_provisional",
        "dart_rate_final", "dart_rate_provisional", "rate_spread_final",
    ):
        assert isinstance(data[field], (int, float)) and data[field] >= 0


def assert_posture_invariants(project: dict):
    """Domain invariants that must hold on any project read (PRD §2.6, §3.1)."""
    assert project["safety_posture"] in ("NORMAL", "RESTRICTED", "FROZEN")
    assert project["issued_permit_count"] >= 0
    assert project["open_deficiency_count"] >= 0
