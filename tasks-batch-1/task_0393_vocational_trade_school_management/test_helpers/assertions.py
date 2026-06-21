"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["credential_type"] in ("DIPLOMA", "CERTIFICATE", "ASSOCIATE")
    assert isinstance(data["required_clock_hours"], int) and data["required_clock_hours"] > 0
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_cohort(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["enrolled_count"], int)
    assert data["status"] in ("FORMING", "RUNNING", "COMPLETED")


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["hs_diploma_verified"], bool)


def assert_externship_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["daily_slot_capacity"], int) and data["daily_slot_capacity"] > 0
    assert isinstance(data["active_assignment_count"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["cohort_id"], str)
    assert isinstance(data["program_id"], str)
    assert data["status"] in (
        "DRAFTED", "ENROLLED", "LEAVE_OF_ABSENCE",
        "GRADUATED", "WITHDRAWN", "CANCELLED",
    )
    assert data["sap_standing"] in ("GOOD", "WARNING", "PROBATION", "DISMISSED")
    assert isinstance(data["licensure_eligible"], bool)


def assert_attendance_entry(data: dict):
    _assert_common(data)
    assert data["kind"] in ("THEORY", "EXTERNSHIP")
    assert data["status"] in ("POSTED", "EXCUSED", "VOIDED")


def assert_sap_standing(data: dict):
    _assert_common(data)
    assert data["standing"] in ("GOOD", "WARNING", "PROBATION", "DISMISSED")
    assert data["appeal_status"] in ("NONE", "APPEALED", "APPEAL_GRANTED", "APPEAL_DENIED")


def assert_disbursement(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "RELEASED", "RETURNED", "CANCELLED")


def assert_refund_case(data: dict):
    _assert_common(data)
    assert data["method"] in ("PRO_RATA", "STATE_TABLE")
    assert data["status"] in ("COMPUTED", "SETTLED", "REVERSED")


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLACED", "IN_PROGRESS", "COMPLETED", "TERMINATED")


def assert_exam_attempt(data: dict):
    _assert_common(data)
    assert data["result"] in ("PASS", "FAIL")


def assert_placement_outcome(data: dict):
    _assert_common(data)
    assert data["outcome_type"] in (
        "EMPLOYED_IN_FIELD", "EMPLOYED_RELATED",
        "CONTINUING_EDUCATION", "NOT_PLACED",
    )
    assert isinstance(data["counts_as_placed"], bool)
