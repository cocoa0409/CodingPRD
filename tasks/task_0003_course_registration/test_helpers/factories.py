"""Payload factories — one per entity, input fields only (PRD §3 / §4)."""
from typing import List, Optional


# ─── Student ───────────────────────────────────────────────────────────
def create_student_payload(
    full_name: str = "Test Student",
    program_id: str = "PROG_DEFAULT",
    program_department_id: Optional[str] = None,
    home_campus_id: Optional[str] = None,
    year_in_program: int = 1,
    gpa: float = 3.50,
    completed_course_ids: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "program_id": program_id,
        "program_department_id": program_department_id,
        "home_campus_id": home_campus_id,
        "year_in_program": year_in_program,
        "gpa": gpa,
        "completed_course_ids": completed_course_ids if completed_course_ids is not None else [],
    }
    payload.update(overrides)
    return payload


# ─── Department / Campus / Professor / LabEquipment ────────────────────
def create_department_payload(code: str = "D-DEFAULT", name: str = "Default Dept",
                              campus_id: Optional[str] = None, **overrides) -> dict:
    payload = {"code": code, "name": name, "campus_id": campus_id}
    payload.update(overrides)
    return payload


def create_campus_payload(code: str = "C-DEFAULT", name: str = "Default Campus",
                          commute_minutes_to: Optional[dict] = None, **overrides) -> dict:
    payload = {
        "code": code,
        "name": name,
        "commute_minutes_to": commute_minutes_to if commute_minutes_to is not None else {},
    }
    payload.update(overrides)
    return payload


def create_professor_payload(
    department_id: Optional[str] = None,
    full_name: str = "Default Professor",
    rank: str = "ASSOCIATE",
    is_chair: bool = False,
    max_concurrent_teaching_minutes_per_week: int = 600,
    **overrides,
) -> dict:
    payload = {
        "department_id": department_id,
        "full_name": full_name,
        "rank": rank,
        "is_chair": is_chair,
        "max_concurrent_teaching_minutes_per_week": max_concurrent_teaching_minutes_per_week,
    }
    payload.update(overrides)
    return payload


def create_lab_equipment_payload(campus_id: Optional[str] = None,
                                  name: str = "Default Equipment",
                                  setup_buffer_minutes: int = 0,
                                  **overrides) -> dict:
    payload = {
        "campus_id": campus_id,
        "name": name,
        "setup_buffer_minutes": setup_buffer_minutes,
    }
    payload.update(overrides)
    return payload


# ─── Term ──────────────────────────────────────────────────────────────
def create_term_payload(
    code: str = "TERM-DEFAULT",
    registration_open_at: int = 1_700_000_000,
    registration_close_at: int = 1_700_000_000 + 86400 * 30,
    classes_start_at: int = 1_700_000_000 + 86400 * 31,
    exam_window_start_at: int = 1_700_000_000 + 86400 * 90,
    exam_window_end_at: int = 1_700_000_000 + 86400 * 97,
    **overrides,
) -> dict:
    payload = {
        "code": code,
        "registration_open_at": registration_open_at,
        "registration_close_at": registration_close_at,
        "classes_start_at": classes_start_at,
        "exam_window_start_at": exam_window_start_at,
        "exam_window_end_at": exam_window_end_at,
    }
    payload.update(overrides)
    return payload


# ─── Course ────────────────────────────────────────────────────────────
def create_course_payload(
    code: str = "C-DEFAULT-101",
    title: str = "Default Course",
    credits: float = 3.0,
    owning_department_id: Optional[str] = None,
    prerequisite_course_ids: Optional[list] = None,
    equivalent_course_ids: Optional[list] = None,
    **overrides,
) -> dict:
    payload = {
        "code": code,
        "title": title,
        "credits": credits,
        "owning_department_id": owning_department_id,
        "prerequisite_course_ids": prerequisite_course_ids if prerequisite_course_ids is not None else [],
        "equivalent_course_ids": equivalent_course_ids if equivalent_course_ids is not None else [],
    }
    payload.update(overrides)
    return payload


# ─── CourseOffering ────────────────────────────────────────────────────
def create_course_offering_payload(
    term_id: Optional[str] = None,
    course_id: Optional[str] = None,
    campus_id: Optional[str] = None,
    instructor_id: Optional[str] = None,
    base_capacity: int = 10,
    scheduled_meetings: Optional[list] = None,
    requires_lab_equipment_ids: Optional[list] = None,
    **overrides,
) -> dict:
    if scheduled_meetings is None:
        scheduled_meetings = [{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 660}]
    payload = {
        "term_id": term_id,
        "course_id": course_id,
        "campus_id": campus_id,
        "instructor_id": instructor_id,
        "base_capacity": base_capacity,
        "scheduled_meetings": scheduled_meetings,
        "requires_lab_equipment_ids": requires_lab_equipment_ids if requires_lab_equipment_ids is not None else [],
    }
    payload.update(overrides)
    return payload


# ─── EnrollmentRequest ─────────────────────────────────────────────────
def create_enrollment_request_payload(student_id: Optional[str] = None,
                                       offering_id: Optional[str] = None,
                                       **overrides) -> dict:
    payload = {"student_id": student_id, "offering_id": offering_id}
    payload.update(overrides)
    return payload


# ─── OverLimitApplication ──────────────────────────────────────────────
def create_over_limit_application_payload(
    student_id: Optional[str] = None,
    term_id: Optional[str] = None,
    requested_extension_credits: float = 6.0,
    justification: str = "Need extra credits for graduation requirement",
    primary_signer_id: Optional[str] = None,
    secondary_signer_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "student_id": student_id,
        "term_id": term_id,
        "requested_extension_credits": requested_extension_credits,
        "justification": justification,
        "primary_signer_id": primary_signer_id,
        "secondary_signer_id": secondary_signer_id,
    }
    payload.update(overrides)
    return payload


# ─── DepartmentAccessGrant ─────────────────────────────────────────────
def create_department_access_grant_payload(
    source_department_id: Optional[str] = None,
    target_department_id: Optional[str] = None,
    course_categories_allowed: Optional[list] = None,
    bidirectional: bool = False,
    **overrides,
) -> dict:
    payload = {
        "source_department_id": source_department_id,
        "target_department_id": target_department_id,
        "course_categories_allowed": course_categories_allowed if course_categories_allowed is not None else [],
        "bidirectional": bidirectional,
    }
    payload.update(overrides)
    return payload


# ─── CreditEquivalencePolicy ───────────────────────────────────────────
def create_credit_equivalence_policy_payload(
    source_program_id: str = "SRC_PRG",
    target_program_id: str = "TGT_PRG",
    source_course_id: Optional[str] = None,
    target_course_id: Optional[str] = None,
    transfer_factor: float = 1.0,
    **overrides,
) -> dict:
    payload = {
        "source_program_id": source_program_id,
        "target_program_id": target_program_id,
        "source_course_id": source_course_id,
        "target_course_id": target_course_id,
        "transfer_factor": transfer_factor,
    }
    payload.update(overrides)
    return payload


# ─── Test-driving payloads ─────────────────────────────────────────────
def advance_clock_payload(target_unix_seconds: int, **overrides) -> dict:
    payload = {"target_unix_seconds": target_unix_seconds}
    payload.update(overrides)
    return payload
