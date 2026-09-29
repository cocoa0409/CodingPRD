"""Payload factories — one per resource, input fields only.

Every factory returns a fresh dict of the request-body fields the PRD declares
for that operation, and accepts `**overrides` so tests can pin the one value
they care about. Passing `field=None` removes the field entirely, which is how
required-field-omission probes are built.
"""

from .constants import TEST_DEFAULTS


def _apply(defaults: dict, overrides: dict) -> dict:
    """Merge overrides; a value of None removes the key entirely."""
    payload = dict(defaults)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


def create_student_payload(**overrides) -> dict:
    return _apply(
        {
            "student_number": "S-0001",
            "full_name": "Ada Lin",
            "grade_level": 7,
            "campus_code": "MS-01",
        },
        overrides,
    )


def student_enrollment_payload(enrollment_status: str = "WITHDRAWN") -> dict:
    return {"enrollment_status": enrollment_status}


# ---------------------------------------------------------------------------
# Teacher
# ---------------------------------------------------------------------------


def create_teacher_payload(**overrides) -> dict:
    return _apply(
        {
            "full_name": "Tara Ng",
            "employee_number": "E-1001",
            "credential_areas": ["MATH", "ELA"],
            "grade_bands": ["MIDDLE", "HIGH"],
            "max_weekly_caseload_minutes": 1200,
            "clearance_expires_on": "2027-06-30",
        },
        overrides,
    )


def teacher_clearance_payload(**overrides) -> dict:
    return _apply(
        {
            "safety_clearance_status": "CLEARED",
            "clearance_expires_on": "2027-06-30",
            "home_visit_eligible": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Entitlement rule
# ---------------------------------------------------------------------------


def create_entitlement_rule_payload(**overrides) -> dict:
    return _apply(
        {
            "grade_band": "MIDDLE",
            "delivery_mode": "IN_HOME",
            "base_weekly_minutes": 360,
            "cap_weekly_minutes": 480,
            "min_session_minutes": 30,
            "max_session_minutes": 120,
            "max_daily_minutes": 240,
            "min_gap_minutes": 15,
            "travel_buffer_minutes": 30,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Homebound case
# ---------------------------------------------------------------------------


def create_case_payload(student_id: str = None, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "referral_date": TEST_DEFAULTS["REFERRAL_DATE"],
        "delivery_mode": "IN_HOME",
    }
    if student_id is None:
        defaults.pop("student_id")
    return _apply(defaults, overrides)


def deny_case_payload(**overrides) -> dict:
    return _apply({"deny_note": "No qualifying medical documentation"}, overrides)


def close_case_payload(**overrides) -> dict:
    return _apply({"close_reason": "WITHDRAWN"}, overrides)


# ---------------------------------------------------------------------------
# Physician certification
# ---------------------------------------------------------------------------


def create_certification_payload(
    case_id: str = None, expected_case_version: int = None, **overrides
) -> dict:
    defaults = {
        "case_id": case_id,
        "physician_npi": TEST_DEFAULTS["PHYSICIAN_NPI"],
        "diagnosis_category": "MEDICAL_ACUTE",
        "certified_start_date": TEST_DEFAULTS["CERTIFIED_START_DATE"],
        "certified_end_date": TEST_DEFAULTS["CERTIFIED_END_DATE"],
        "expected_absence_days": TEST_DEFAULTS["EXPECTED_ABSENCE_DAYS"],
        "signature_date": TEST_DEFAULTS["SIGNATURE_DATE"],
        "expected_case_version": expected_case_version,
    }
    if case_id is None:
        defaults.pop("case_id")
    if expected_case_version is None:
        defaults.pop("expected_case_version")
    return _apply(defaults, overrides)


def review_certification_payload(decision: str = "ACCEPT", **overrides) -> dict:
    return _apply({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Teacher assignment
# ---------------------------------------------------------------------------


def create_assignment_payload(
    case_id: str = None, role: str = "PRIMARY", teacher_id: str = None, **overrides
) -> dict:
    defaults = {"case_id": case_id, "role": role}
    if case_id is None:
        defaults.pop("case_id")
    if teacher_id is not None:
        defaults["teacher_id"] = teacher_id
    return _apply(defaults, overrides)


def decline_assignment_payload(**overrides) -> dict:
    return _apply({"decline_reason": "Schedule conflict on the home route"}, overrides)


def release_assignment_payload(**overrides) -> dict:
    return _apply({"release_reason": "CASELOAD_REBALANCE"}, overrides)


# ---------------------------------------------------------------------------
# Home visit safety review
# ---------------------------------------------------------------------------


def create_safety_review_payload(case_id: str = None, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "evidence_source": "ONSITE_WALKTHROUGH",
        "review_date": "2026-09-02",
    }
    if case_id is None:
        defaults.pop("case_id")
    return _apply(defaults, overrides)


# ---------------------------------------------------------------------------
# Instruction session
# ---------------------------------------------------------------------------


def create_session_payload(
    case_id: str = None, assignment_id: str = None, **overrides
) -> dict:
    defaults = {
        "case_id": case_id,
        "assignment_id": assignment_id,
        "scheduled_start": "2026-09-07T09:00:00Z",
        "scheduled_end": "2026-09-07T11:00:00Z",
        "delivery_mode": "IN_HOME",
        "subject": "MATH",
    }
    if case_id is None:
        defaults.pop("case_id")
    if assignment_id is None:
        defaults.pop("assignment_id")
    return _apply(defaults, overrides)


def makeup_session_payload(assignment_id: str = None, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "scheduled_start": "2026-09-08T09:00:00Z",
        "scheduled_end": "2026-09-08T10:00:00Z",
        "delivery_mode": "IN_HOME",
        "subject": "MATH",
    }
    if assignment_id is None:
        defaults.pop("assignment_id")
    return _apply(defaults, overrides)


def log_delivered_payload(actual_minutes: int = 120, **overrides) -> dict:
    return _apply(
        {"outcome": "DELIVERED", "actual_minutes": actual_minutes}, overrides
    )


def log_student_unavailable_payload(absence_kind: str = "MEDICAL", **overrides) -> dict:
    return _apply(
        {"outcome": "STUDENT_UNAVAILABLE", "absence_kind": absence_kind}, overrides
    )


def log_teacher_cancelled_payload(**overrides) -> dict:
    return _apply(
        {"outcome": "TEACHER_CANCELLED", "outcome_reason": "Teacher illness"}, overrides
    )


def log_safety_aborted_payload(**overrides) -> dict:
    return _apply(
        {
            "outcome": "SAFETY_ABORTED",
            "outcome_reason": "Unsecured dog in the entry hallway",
        },
        overrides,
    )


def void_session_payload(**overrides) -> dict:
    return _apply({"void_reason": "AUDIT_REVERSAL"}, overrides)


# ---------------------------------------------------------------------------
# Extension request
# ---------------------------------------------------------------------------


def create_extension_request_payload(
    case_id: str = None,
    certification_id: str = None,
    expected_case_version: int = None,
    **overrides,
) -> dict:
    defaults = {
        "case_id": case_id,
        "certification_id": certification_id,
        "requested_additional_days": 30,
        "justification": "Treatment extended by the attending physician",
        "expected_case_version": expected_case_version,
    }
    for key in ("case_id", "certification_id", "expected_case_version"):
        if defaults.get(key) is None:
            defaults.pop(key, None)
    return _apply(defaults, overrides)


def request_extension_info_payload(**overrides) -> dict:
    return _apply({"info_note": "Attach the updated discharge summary"}, overrides)


def resubmit_extension_payload(certification_id: str = None, **overrides) -> dict:
    defaults = {"certification_id": certification_id}
    if certification_id is None:
        defaults.pop("certification_id")
    return _apply(defaults, overrides)


def decide_extension_payload(decision: str = "APPROVED", **overrides) -> dict:
    return _apply({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Transition plan
# ---------------------------------------------------------------------------


def create_transition_plan_payload(
    case_id: str = None, expected_case_version: int = None, **overrides
) -> dict:
    defaults = {
        "case_id": case_id,
        "target_return_date": "2026-09-14",
        "reintegration_mode": "FULL_DAY",
        "expected_case_version": expected_case_version,
    }
    for key in ("case_id", "expected_case_version"):
        if defaults.get(key) is None:
            defaults.pop(key, None)
    return _apply(defaults, overrides)


def abort_transition_plan_payload(**overrides) -> dict:
    return _apply({"abort_reason": "MEDICAL_RELAPSE"}, overrides)


# ---------------------------------------------------------------------------
# Curriculum pacing coordination
# ---------------------------------------------------------------------------


def create_pacing_sync_payload(
    case_id: str = None, classroom_teacher_id: str = None, **overrides
) -> dict:
    defaults = {
        "case_id": case_id,
        "classroom_teacher_id": classroom_teacher_id,
        "subject": "MATH",
        "pacing_target_unit": "Unit 3: Linear Equations",
        "assessment_accommodation": "EXTENDED_TIME",
    }
    for key in ("case_id", "classroom_teacher_id"):
        if defaults.get(key) is None:
            defaults.pop(key, None)
    return _apply(defaults, overrides)


def dispute_pacing_sync_payload(**overrides) -> dict:
    return _apply(
        {"dispute_note": "Unit 3 was already assessed in class last week"}, overrides
    )


# ---------------------------------------------------------------------------
# Special-education service continuation log
# ---------------------------------------------------------------------------


def create_sped_service_log_payload(case_id: str = None, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "service_type": "SPEECH",
        "required_weekly_minutes": 60,
    }
    if case_id is None:
        defaults.pop("case_id")
    return _apply(defaults, overrides)


def record_sped_delivery_payload(
    minutes: int = 60, service_date: str = "2026-09-08", **overrides
) -> dict:
    return _apply({"minutes": minutes, "service_date": service_date}, overrides)


def sped_continuation_payload(
    to_status: str = "MODIFIED_VIRTUAL",
    continuation_reason: str = "Therapist delivering via teletherapy",
    **overrides,
) -> dict:
    return _apply(
        {"to_status": to_status, "continuation_reason": continuation_reason}, overrides
    )
