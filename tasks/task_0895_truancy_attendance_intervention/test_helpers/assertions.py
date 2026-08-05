"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID (no type prefix)"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_school(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for f in ("tier1_unexcused_threshold", "tier2_unexcused_threshold",
              "tier3_unexcused_threshold", "court_unexcused_threshold",
              "required_instructional_days"):
        assert isinstance(data[f], int)
    assert isinstance(data["chronic_absence_pct_threshold"], (int, float))


def assert_staff(data: dict):
    _assert_common(data)
    assert data["role_type"] in ("CASE_MANAGER", "OFFICER", "COUNSELOR")
    assert isinstance(data["max_caseload"], int)
    assert isinstance(data["active_caseload"], int) and data["active_caseload"] >= 0


def assert_student(data: dict):
    _assert_common(data)
    assert data["enrollment_status"] in ("ENROLLED", "WITHDRAWN", "GRADUATED")
    for c in ("present_count", "tardy_count", "excused_count", "unexcused_count"):
        assert isinstance(data[c], int) and data[c] >= 0
    assert isinstance(data["chronic_absent"], bool)
    for r in ("attendance_rate_recorded", "attendance_rate_official"):
        assert data[r] is None or isinstance(data[r], (int, float))


def assert_attendance_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("PRESENT", "TARDY", "EXCUSED", "UNEXCUSED", "VOIDED")
    assert isinstance(data["attendance_date"], str)


def assert_case(data: dict):
    _assert_common(data)
    assert data["tier"] in ("NONE", "TIER_1", "TIER_2", "TIER_3", "COURT_REFERRED")
    assert data["status"] in ("OPEN", "MONITORING", "RESOLVED", "CLOSED")
    assert isinstance(data["breach_count"], int) and data["breach_count"] >= 0


def assert_conference(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "HELD", "NO_SHOW", "CANCELLED")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "ACTIVE", "BREACHED", "FULFILLED", "CANCELLED")
    for s in ("compliance_score_actual", "compliance_score_projected"):
        assert data[s] is None or isinstance(data[s], (int, float))


def assert_service_referral(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("MENTOR", "COUNSELING", "HEALTH", "OTHER")
    assert data["status"] in ("REFERRED", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "DECLINED")
    assert isinstance(data["auto_created"], bool)


def assert_court_citation(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "HEARD", "DISMISSED", "WITHDRAWN")


def assert_compliance_check_shape(data: dict):
    """ComplianceCheck is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only ComplianceCheck must not expose version"
    assert "updated_at" not in data, "append-only ComplianceCheck must not expose updated_at"
    assert data["result"] in ("COMPLIANT", "NON_COMPLIANT")
