"""Entity assertions and domain invariant checkers.

Each assert_<entity> validates the common envelope fields the PRD guarantees on
every persisted resource (id UUID; created_at/updated_at ISO 8601; integer
version) plus the entity's own declared fields. The audit trail is the
exception: it carries only id and created_at (PRD §2.5).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_school(data: dict):
    _assert_common(data)
    assert isinstance(data["school_name"], str) and data["school_name"]
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert isinstance(data["home_state_code"], str) and len(data["home_state_code"]) == 2
    assert isinstance(data["pass_rate_threshold_bps"], int)
    assert 0 <= data["pass_rate_threshold_bps"] <= 10000
    assert isinstance(data["director_user_id"], str) and data["director_user_id"]
    assert data["status"] in ["PROVISIONAL", "LICENSED", "SUSPENDED", "REVOKED"]
    assert data["posture"] in ["GOOD_STANDING", "PROBATION"]
    assert isinstance(data["last_evaluation_attempt_count"], int)
    assert data["last_evaluation_first_attempt_pass_rate_bps"] is None or \
        isinstance(data["last_evaluation_first_attempt_pass_rate_bps"], int)


def assert_course(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["course_type"] in ["PRE_LICENSING", "CONTINUING_ED"]
    assert isinstance(data["required_seat_minutes"], int) and data["required_seat_minutes"] > 0
    assert isinstance(data["tuition_cents"], int) and data["tuition_cents"] >= 0
    assert isinstance(data["pass_score_pct"], int) and 1 <= data["pass_score_pct"] <= 100
    assert isinstance(data["max_exam_attempts"], int) and data["max_exam_attempts"] >= 1
    assert isinstance(data["completion_deadline_days"], int) and data["completion_deadline_days"] >= 1
    assert data["ce_credit_hours"] >= 0
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_course_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["application_round"], int) and data["application_round"] >= 1
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "EXPIRING",
                              "RENEWAL_PENDING", "EXPIRED"]
    for f in ("valid_from", "valid_until", "decided_at"):
        assert data.get(f) is None or isinstance(data[f], str)


def assert_instructor(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_instructor_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("instructor_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["application_round"], int) and data["application_round"] >= 1
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "EXPIRING",
                              "RENEWAL_PENDING", "EXPIRED"]


def assert_offering(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert is_valid_uuid(data.get("instructor_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["delivery_mode"] in ["IN_PERSON", "DISTANCE"]
    assert data["status"] in ["DRAFT", "PUBLISHED", "IN_SESSION", "COMPLETED", "CANCELLED"]
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["seats_available"], int)


def assert_student(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["license_goal_state"], str)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("offering_id", ""))
    assert data["academic_status"] in ["ENROLLED", "IN_PROGRESS", "SEAT_TIME_MET",
                                       "EXAM_PASSED", "COMPLETED", "WITHDRAWN",
                                       "FAILED", "EXPIRED"]
    assert data["payment_status"] in ["PENDING", "PAID", "PARTIALLY_REFUNDED",
                                      "REFUNDED", "VOIDED"]
    assert isinstance(data["scholarship_cents"], int) and data["scholarship_cents"] >= 0
    assert isinstance(data["charge_total_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["retained_cents"], int)
    assert isinstance(data["verified_seat_minutes"], int)
    assert isinstance(data["creditable_seat_minutes"], int)
    assert isinstance(data["completion_fraction_bps"], int)
    assert isinstance(data["exam_attempts_used"], int)
    assert isinstance(data["deadline_date"], str) and data["deadline_date"]
    assert is_iso8601_timestamp(data.get("enrolled_at", ""))
    assert data.get("withdrawn_at") is None or isinstance(data["withdrawn_at"], str)
    assert data.get("withdrawal_reason") in (None, "VOLUNTARY", "ADMINISTRATIVE",
                                             "SCHOOL_CANCELLED")


def assert_attendance_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["session_date"], str) and data["session_date"]
    assert isinstance(data["minutes"], int) and 1 <= data["minutes"] <= 1440
    assert isinstance(data["recorded_by_instructor_id"], str)
    assert data["status"] in ["VERIFIED", "VOID"]


def assert_exam_attempt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert isinstance(data["scheduled_at"], str) and data["scheduled_at"]
    assert is_valid_uuid(data.get("proctor_instructor_id", ""))
    assert data["status"] in ["SCHEDULED", "PROCTORED", "SCORED", "NO_SHOW", "INVALIDATED"]
    assert data.get("score_pct") is None or isinstance(data["score_pct"], int)
    assert data.get("outcome") in (None, "PASSED", "FAILED")
    assert data.get("invalidation_reason") is None or isinstance(data["invalidation_reason"], str)
    assert data.get("verified_at") is None or isinstance(data["verified_at"], str)
    assert data.get("scored_at") is None or isinstance(data["scored_at"], str)


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert data["credit_hours_pinned"] >= 0
    assert isinstance(data["issue_date"], str) and data["issue_date"]
    assert data["status"] in ["ACTIVE", "REVOKED"]
    assert data.get("revoked_reason") is None or isinstance(data["revoked_reason"], str)
    assert data.get("revoked_at") is None or isinstance(data["revoked_at"], str)


def assert_refund_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["reason"] in ["VOLUNTARY", "ADMINISTRATIVE", "SCHOOL_CANCELLED"]
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "PAID"]
    assert isinstance(data["completion_fraction_bps_at_withdrawal"], int)
    assert isinstance(data["scheduled_refund_cents"], int)
    assert isinstance(data["statutory_refund_cents"], int)
    assert isinstance(data["granted_refund_cents"], int)
    assert data.get("denial_reason") is None or isinstance(data["denial_reason"], str)
    assert data.get("decided_at") is None or isinstance(data["decided_at"], str)
    assert data.get("paid_at") is None or isinstance(data["paid_at"], str)


def assert_credit_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert data.get("amendment_of_id") is None or isinstance(data["amendment_of_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACKNOWLEDGED", "REJECTED"]
    assert isinstance(data["line_items"], list)
    assert isinstance(data["total_credit_hours"], (int, float))
    assert isinstance(data["reporting_deadline_date"], str) and data["reporting_deadline_date"]
    assert data.get("submitted_at") is None or isinstance(data["submitted_at"], str)
    assert isinstance(data["late_days"], int) and data["late_days"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0


def assert_equivalency_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["home_state_code"], str) and len(data["home_state_code"]) == 2
    assert isinstance(data["recognized_state_code"], str) and len(data["recognized_state_code"]) == 2
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REVOKED", "SUPERSEDED"]


def assert_audit_event(data: dict):
    """The audit trail carries only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "audit events are immutable and omit updated_at"
    assert "version" not in data, "audit events are immutable and omit version"
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str)
    assert isinstance(data.get("detail", {}), dict)


# --- Domain invariants ---

def assert_seat_invariant(offering: dict):
    """capacity always equals enrolled seats plus available seats (PRD §3.5)."""
    assert offering["capacity"] == offering["enrolled_count"] + offering["seats_available"], \
        (f"seat invariant broken: capacity {offering['capacity']} != "
         f"enrolled_count {offering['enrolled_count']} + "
         f"seats_available {offering['seats_available']}")


def assert_money_conservation(enrollment: dict, granted_refund_cents: int):
    """paid amount always equals retained plus granted (PRD §3.9)."""
    assert enrollment["paid_cents"] == enrollment["retained_cents"] + granted_refund_cents, \
        (f"money conservation broken: paid {enrollment['paid_cents']} != "
         f"retained {enrollment['retained_cents']} + granted {granted_refund_cents}")
