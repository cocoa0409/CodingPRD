"""Entity assertions and domain invariant checkers (PRD sections 2.4, 3.x)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

RISK_BANDS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
EPISODE_STATUSES = ["OPEN", "EXHAUSTED", "REFERRED_OUT", "CLOSED", "REOPENED"]
SESSION_STATUSES = ["SCHEDULED", "HELD", "COMPLETED", "CANCELLED_TIMELY",
                    "CANCELLED_LATE", "NO_SHOW_CHARGED", "NO_SHOW_EXCUSED"]
PROGRAM_STATUSES = ["DRAFT", "OPEN", "RUNNING", "COMPLETED", "CANCELLED"]
ENROLLMENT_STATUSES = ["ENROLLED", "WAITLISTED", "DROPPED", "REMOVED_RISK"]
SHIFT_STATUSES = ["UNCLAIMED", "CLAIMED", "RELEASED", "COVERED"]
VISIT_STATUSES = ["QUEUED", "IN_ROOM", "STABILIZED", "ESCALATED", "DISPOSITIONED"]
REFERRAL_STATUSES = ["PENDING", "MATCHED", "ACCEPTED", "DECLINED",
                     "COMPLETED", "LAPSED"]
POLICY_STATUSES = ["DRAFT", "PUBLISHED", "RETIRED"]
POSTURES = ["CLEAR", "RESTRICTED", "SUSPENDED"]


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be an ISO 8601 timestamp"
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        # PRD section 2.4: the four light resources never carry these fields.
        assert "updated_at" not in data, \
            "updated_at must be absent from this append-only resource"
        assert "version" not in data, \
            "version must be absent from this append-only resource"


def assert_student(data: dict):
    """Clinical view of a student (counseling roles)."""
    _assert_common(data)
    assert isinstance(data["student_number"], str) and data["student_number"]
    assert data["enrollment_status"] in [
        "ENROLLED", "LEAVE_OF_ABSENCE", "WITHDRAWN", "GRADUATED"]
    assert data["funding_model"] in ["STUDENT_FEE", "INSURANCE", "SPLIT"]
    assert isinstance(data["no_show_strike_count"], int)
    assert data["booking_posture"] in POSTURES


def assert_counselor(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str) and data["license_id"]
    assert isinstance(data["weekly_individual_capacity"], int)
    assert data["weekly_individual_capacity"] >= 1
    assert isinstance(data["max_caseload_risk_points"], int)
    assert data["max_caseload_risk_points"] >= 1


def assert_intake_assessment(data: dict):
    _assert_common(data, with_version=False)
    assert isinstance(data["phq9_score"], int) and 0 <= data["phq9_score"] <= 27
    assert isinstance(data["gad7_score"], int) and 0 <= data["gad7_score"] <= 21
    assert isinstance(data["risk_points"], int)
    assert data["risk_band"] in RISK_BANDS
    assert data["disposition"] in [
        "PENDING", "SHORT_TERM_CARE", "COMMUNITY_REFERRAL", "CRISIS_PROTOCOL"]


def assert_care_episode(data: dict):
    _assert_common(data)
    assert data["status"] in EPISODE_STATUSES
    assert isinstance(data["session_limit"], int) and data["session_limit"] >= 2
    assert isinstance(data["sessions_consumed"], int)
    assert data["sessions_consumed"] >= 0
    assert isinstance(data["exemption_granted"], bool)


def assert_session(data: dict):
    _assert_common(data)
    assert data["status"] in SESSION_STATUSES
    assert data["duration_minutes"] in [30, 45, 60]
    assert isinstance(data["billed_amount_cents"], int)
    assert data["billed_amount_cents"] >= 0


def assert_group_program(data: dict):
    _assert_common(data)
    assert data["status"] in PROGRAM_STATUSES
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert 1 <= data["weeks"] <= 16
    assert data["risk_band_ceiling"] in ["LOW", "MODERATE", "HIGH"]


def assert_group_enrollment(data: dict):
    _assert_common(data, with_version=False)
    assert data["status"] in ENROLLMENT_STATUSES


def assert_crisis_shift(data: dict):
    _assert_common(data)
    assert data["status"] in SHIFT_STATUSES
    assert data["shift_kind"] in ["WALK_IN", "AFTER_HOURS"]


def assert_crisis_visit(data: dict):
    _assert_common(data)
    assert data["status"] in VISIT_STATUSES
    assert data["presenting_risk_band"] in RISK_BANDS
    assert data["disposition"] in [
        "NONE", "RETURN_TO_CARE", "COMMUNITY_REFERRAL", "EMERGENCY_TRANSPORT"]


def assert_community_referral(data: dict):
    _assert_common(data)
    assert data["status"] in REFERRAL_STATUSES
    assert isinstance(data["rematch_count"], int) and data["rematch_count"] >= 0
    assert isinstance(data["required_specialty"], str)


def assert_outcome_measure(data: dict):
    _assert_common(data, with_version=False)
    assert data["instrument"] in ["PHQ9", "GAD7", "CCAPS"]
    assert data["phase"] in ["BASELINE", "MID", "DISCHARGE"]
    assert isinstance(data["score"], int) and data["score"] >= 0


def assert_semester_policy(data: dict):
    _assert_common(data)
    assert data["policy_status"] in POLICY_STATUSES
    assert isinstance(data["base_session_limit"], int)
    assert data["base_session_limit"] >= 0
    assert isinstance(data["no_show_strike_limit"], int)
    assert data["no_show_strike_limit"] >= 1
    assert isinstance(data["late_cancel_window_hours"], int)
    assert data["late_cancel_window_hours"] >= 0


def assert_clinical_note(data: dict):
    _assert_common(data, with_version=False)
    assert isinstance(data["body"], str)
