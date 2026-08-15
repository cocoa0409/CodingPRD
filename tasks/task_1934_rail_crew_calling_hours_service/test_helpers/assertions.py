"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["craft"] in ["CONDUCTOR", "ENGINEER", "BRAKEMAN", "YARDMASTER"]
    assert data["availability_status"] in [
        "AVAILABLE", "MARKED_OFF", "ON_LEAVE", "ON_ASSIGNMENT", "ON_REST", "SUSPENDED",
    ]
    assert isinstance(data["cumulative_duty_minutes_month"], int)
    assert data["cumulative_duty_minutes_month"] >= 0
    assert isinstance(data["fatigue_score"], (int, float))
    assert 0 <= data["fatigue_score"] <= 100
    assert isinstance(data["home_terminal"], str) and data["home_terminal"]


def assert_extra_board(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["board_code"], str) and data["board_code"]
    assert data["craft"] in ["CONDUCTOR", "ENGINEER", "BRAKEMAN", "YARDMASTER"]
    assert isinstance(data["terminal"], str) and data["terminal"]
    assert isinstance(data["guaranteed_slots"], int) and data["guaranteed_slots"] >= 0


def assert_extra_board_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("board_id", "")), "board_id must be a valid UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a valid UUID"
    assert isinstance(data["standing_position"], int) and data["standing_position"] >= 1
    assert data["slot_status"] in ["ACTIVE", "FROZEN", "VACATED"]


def assert_job(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["job_symbol"], str) and data["job_symbol"]
    assert data["craft"] in ["CONDUCTOR", "ENGINEER", "BRAKEMAN", "YARDMASTER"]
    assert isinstance(data["origin_terminal"], str) and data["origin_terminal"]
    assert isinstance(data["crew_required"], int) and data["crew_required"] >= 1
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data["job_status"] in ["BULLETINED", "CALLING", "FILLED"]


def assert_call(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", "")), "job_id must be a valid UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a valid UUID"
    assert data["call_status"] in [
        "OFFERED", "ACCEPTED", "DECLINED", "NO_ANSWER", "EXPIRED", "RESCINDED",
    ]
    assert is_iso8601_timestamp(data.get("offered_at", "")), "offered_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", "")), "job_id must be a valid UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a valid UUID"
    assert is_valid_uuid(data.get("call_id", "")), "call_id must be a valid UUID"
    assert data["assignment_status"] in [
        "MARKED_UP", "ON_DUTY", "TIE_UP_PENDING", "COMPLETED", "LAID_OFF", "RECREWED",
    ]
    assert isinstance(data["deadhead_minutes"], int) and data["deadhead_minutes"] >= 0
    assert data["deadhead_mode"] in ["NONE", "TAXI", "COMPANY_VEHICLE", "TRAIN"]


def assert_rest_period(data: dict):
    """RestPeriod is append-only: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "RestPeriod must not carry updated_at"
    assert "version" not in data, "RestPeriod must not carry version"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("rest_start", "")), "rest_start must be ISO 8601"
    assert data["rest_status"] in ["OPEN", "SATISFIED", "DISTURBED"]


def assert_leave_bid(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a valid UUID"
    assert data["leave_type"] in ["VACATION", "PERSONAL_DAY"]
    assert is_iso8601_timestamp(data.get("start_date", "")), "start_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_date", "")), "end_date must be ISO 8601"
    assert data["bid_status"] in ["SUBMITTED", "AWARDED", "DENIED", "CANCELLED"]


def assert_pay_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a valid UUID"
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert isinstance(data["claimed_minutes"], int) and data["claimed_minutes"] >= 0
    assert isinstance(data["claimed_deadhead_minutes"], int)
    assert data["claimed_deadhead_minutes"] >= 0
    assert data["record_status"] in ["DRAFT", "SUBMITTED", "DISPUTED", "FINALIZED"]


def assert_crew_shortage(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("job_id", "")), "job_id must be a valid UUID"
    assert isinstance(data["craft"], str) and data["craft"]
    assert data["shortage_status"] in ["OPEN", "RECREWING", "RESOLVED", "ESCALATED"]
    assert is_iso8601_timestamp(data.get("opened_at", "")), "opened_at must be ISO 8601"
