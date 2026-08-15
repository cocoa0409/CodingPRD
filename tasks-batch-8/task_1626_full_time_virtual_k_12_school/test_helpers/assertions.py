"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Every resource carries the standard
system-managed properties (id, created_at, updated_at, version) described in
the PRD common-resource-properties section.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ENROLLMENT_STATUSES = ["APPLIED", "ELIGIBLE", "ENROLLED", "WITHDRAWN",
                        "REENROLL_PENDING"]
_TERM_STATUSES = ["ACTIVE", "WITHDRAWN", "COMPLETED"]
_ISSUE_STATUSES = ["REQUESTED", "ISSUED", "RETURN_REQUESTED", "RETURNED",
                   "FORFEITED"]
_ATTENDANCE_STATUSES = ["PRESENT", "PARTIAL", "ABSENT_UNEXCUSED",
                        "ABSENT_EXCUSED"]
_WINDOW_STATUSES = ["SCHEDULED", "OPEN", "CLOSED"]
_PROCTOR_STATUSES = ["BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED"]
_DELIVERY_STATUSES = ["SCHEDULED", "DELIVERED", "MISSED", "CANCELLED"]
_TEACHER_ASSIGNMENT_STATUSES = ["ASSIGNED", "ENDED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_district(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["funding_rate_cents"], int) and data["funding_rate_cents"] >= 1
    assert isinstance(data["enrollment_cap"], int) and data["enrollment_cap"] >= 0


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["grade_level"], int) and 0 <= data["grade_level"] <= 12
    assert is_valid_uuid(data["district_of_residence_id"])
    assert isinstance(data["special_education_flag"], bool)
    assert data["enrollment_status"] in _ENROLLMENT_STATUSES
    assert data["residency_verified_at"] is None or \
        is_iso8601_timestamp(data["residency_verified_at"])
    assert isinstance(data["funding_days_claimed"], int) and data["funding_days_claimed"] >= 0
    assert isinstance(data["funding_claim_cents"], int) and data["funding_claim_cents"] >= 0
    assert isinstance(data["truancy_flag"], bool)
    assert isinstance(data["truancy_unexcused_count"], int) and data["truancy_unexcused_count"] >= 0


def assert_enrollment_term(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["term_start_date"], str) and data["term_start_date"]
    assert data["term_end_date"] is None or isinstance(data["term_end_date"], str)
    assert data["term_status"] in _TERM_STATUSES
    assert data["proration_mode"] is None or \
        data["proration_mode"] in ["DAILY_ATTENDANCE", "CALENDAR_ELAPSED"]
    assert isinstance(data["claimable_days"], int) and data["claimable_days"] >= 0


def assert_device_stipend(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["stipend_type"] in ["DEVICE", "INTERNET"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["issue_status"] in _ISSUE_STATUSES
    assert data["issued_at"] is None or isinstance(data["issued_at"], str)
    assert data["return_due_date"] is None or isinstance(data["return_due_date"], str)
    assert isinstance(data["clawback_cents"], int) and data["clawback_cents"] >= 0


def assert_teacher(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["certification_state_codes"], list)
    assert all(isinstance(c, str) and len(c) == 2
               for c in data["certification_state_codes"])
    assert isinstance(data["caseload_cap"], int) and data["caseload_cap"] >= 1
    assert isinstance(data["current_caseload"], int) and data["current_caseload"] >= 0
    assert data["current_caseload"] <= data["caseload_cap"], \
        "current_caseload must never exceed caseload_cap"
    assert data["teacher_status"] in ["ACTIVE", "INACTIVE"]


def assert_teacher_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["teacher_id"])
    assert is_valid_uuid(data["student_id"])
    assert data["subject"] in ["ELA", "MATH", "SCIENCE", "SOCIAL_STUDIES",
                               "SPECIAL_ED"]
    assert data["assignment_status"] in _TEACHER_ASSIGNMENT_STATUSES
    assert isinstance(data["assigned_at"], str) and data["assigned_at"]
    assert data["ended_at"] is None or isinstance(data["ended_at"], str)


def assert_attendance_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["attendance_date"], str) and data["attendance_date"]
    assert isinstance(data["synchronous_minutes"], int) and data["synchronous_minutes"] >= 0
    assert isinstance(data["engagement_check_ins"], int) and data["engagement_check_ins"] >= 0
    assert data["attendance_status"] in _ATTENDANCE_STATUSES
    assert data["excused_reason"] is None or isinstance(data["excused_reason"], str)


def assert_assessment_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["assessment_name"], str) and data["assessment_name"]
    assert data["subject"] in ["ELA", "MATH", "SCIENCE"]
    assert isinstance(data["window_start"], str) and data["window_start"]
    assert isinstance(data["window_end"], str) and data["window_end"]
    assert data["window_status"] in _WINDOW_STATUSES


def assert_test_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["seats_booked"], int) and data["seats_booked"] >= 0
    assert data["seats_booked"] <= data["seat_capacity"], \
        "seats_booked must never exceed seat_capacity"


def assert_proctor_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["assessment_window_id"])
    assert is_valid_uuid(data["test_site_id"])
    assert data["assignment_status"] in _PROCTOR_STATUSES
    assert isinstance(data["booked_at"], str) and data["booked_at"]
    assert data["completed_at"] is None or isinstance(data["completed_at"], str)


def assert_service_delivery(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["service_type"] in ["SPEECH_THERAPY", "OCCUPATIONAL_THERAPY",
                                    "COUNSELING", "RESOURCE_ROOM"]
    assert isinstance(data["scheduled_at"], str) and data["scheduled_at"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 15
    assert is_valid_uuid(data["provider_id"])
    assert data["delivery_status"] in _DELIVERY_STATUSES
    assert data["delivered_at"] is None or isinstance(data["delivered_at"], str)


def assert_funding_totals_consistent(student: dict, terms: list,
                                     funding_rate_cents: int):
    """PRD funding pipeline: funding_days_claimed is the sum of claimable_days
    across all of the student's terms, and funding_claim_cents is computed per
    term first (claimable_days * district rate), then summed."""
    expected_days = sum(t["claimable_days"] for t in terms)
    expected_cents = sum(t["claimable_days"] * funding_rate_cents for t in terms)
    assert student["funding_days_claimed"] == expected_days, (
        f"funding_days_claimed {student['funding_days_claimed']} != "
        f"sum of claimable_days {expected_days}")
    assert student["funding_claim_cents"] == expected_cents, (
        f"funding_claim_cents {student['funding_claim_cents']} != "
        f"per-term-then-summed total {expected_cents}")
