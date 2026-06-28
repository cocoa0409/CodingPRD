"""Payload factories — one per entity, input fields only."""

FUTURE_EXPIRY = "2027-01-01T00:00:00Z"


def create_program_payload(**overrides) -> dict:
    """POST /programs. skills_pass_threshold is optional (defaults to 80)."""
    defaults = {
        "name": "Class B CDL ELDT",
        "cdl_class": "CLASS_B",
        "classroom_required_hours": 1,
        "range_required_hours": 1,
        "road_required_hours": 1,
        "tuition_cents": 700000,
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    """POST /trucks. turnaround_buffer_minutes is optional (defaults to 30)."""
    defaults = {
        "unit_number": "T1",
        "cdl_class": "CLASS_B",
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    """POST /instructors. examiner_certified is optional (defaults to false)."""
    defaults = {
        "full_name": "Ivy Instructor",
        "cdl_class": "CLASS_B",
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    """POST /carriers."""
    defaults = {
        "name": "BigHaul Carrier",
        "commitment_months": 12,
        "reimbursement_cents": 600000,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(program_id, **overrides) -> dict:
    """POST /enrollments."""
    defaults = {
        "program_id": program_id,
        "student_name": "Sam Student",
    }
    defaults.update(overrides)
    return defaults


def create_prereq_document_payload(kind, **overrides) -> dict:
    """POST /enrollments/{id}/prereq-documents. kind is DOT_MEDICAL or CLP_PERMIT."""
    defaults = {
        "kind": kind,
        "reference_code": f"REF-{kind}",
        "expires_on": FUTURE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_clock_session_payload(phase, instructor_id, starts_at, duration_minutes,
                                 truck_id=None, **overrides) -> dict:
    """POST /enrollments/{id}/clock-sessions. truck_id required for RANGE/ROAD,
    forbidden for CLASSROOM."""
    defaults = {
        "phase": phase,
        "instructor_id": instructor_id,
        "starts_at": starts_at,
        "duration_minutes": duration_minutes,
    }
    if truck_id is not None:
        defaults["truck_id"] = truck_id
    defaults.update(overrides)
    return defaults


def create_skills_test_payload(examiner_id, **overrides) -> dict:
    """POST /enrollments/{id}/skills-tests. supersedes_test_id is optional."""
    defaults = {
        "examiner_id": examiner_id,
    }
    defaults.update(overrides)
    return defaults


def grade_skills_test_payload(pre_trip_score, basic_control_score, road_score, **overrides) -> dict:
    """POST /skills-tests/{id}/grade."""
    defaults = {
        "pre_trip_score": pre_trip_score,
        "basic_control_score": basic_control_score,
        "road_score": road_score,
    }
    defaults.update(overrides)
    return defaults


def create_sponsorship_offer_payload(carrier_id, **overrides) -> dict:
    """POST /enrollments/{id}/sponsorship-offers."""
    defaults = {
        "carrier_id": carrier_id,
    }
    defaults.update(overrides)
    return defaults


def create_finance_plan_payload(term_months, expected_enrollment_version, **overrides) -> dict:
    """POST /enrollments/{id}/finance-plans. Both fields required (OCC-guarded)."""
    defaults = {
        "term_months": term_months,
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def create_completion_report_payload(passing_test_id, **overrides) -> dict:
    """POST /enrollments/{id}/completion-reports."""
    defaults = {
        "passing_test_id": passing_test_id,
    }
    defaults.update(overrides)
    return defaults
