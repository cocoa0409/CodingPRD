"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through the public API,
because each test starts against an empty database. Internally these helpers
use get_success_data() so a setup failure surfaces as a clear setup error.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_INIT, CLOCK_IN_SESSION, STD_FISCAL_YEAR, STD_MEETING_END,
    STD_MEETING_START, STD_ROOM, STD_SCHOOL_YEAR,
)
from .factories import (
    create_assignment_payload, create_audit_case_payload, create_budget_payload,
    create_building_payload, create_course_payload, create_employee_payload,
    create_growth_plan_payload, create_meeting_payload, create_registration_payload,
    create_section_payload, create_survey_payload, create_workshop_payload,
)
from .test_users import (
    TEST_USERS, make_auditor_headers, make_building_admin_headers,
    make_coordinator_headers, make_instructor_headers, make_officer_headers,
    make_teacher_headers,
)

COORD = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --- Primitive creators -------------------------------------------------

def set_clock(to_iso8601=CLOCK_INIT):
    """Advance the server-held logical clock (PDCoordinator-only, PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


def make_building(**overrides):
    return get_success_data(api_client.create_building(create_building_payload(**overrides), COORD))


def make_budget(building_id, allocated_cents=500000, fiscal_year=STD_FISCAL_YEAR,
                open_it=True):
    budget = get_success_data(api_client.create_budget(
        create_budget_payload(building_id, fiscal_year=fiscal_year,
                              allocated_cents=allocated_cents), OFFICER))
    if open_it:
        budget = get_success_data(api_client.open_budget(budget["id"], OFFICER))
    return budget


def make_employee(building_id, kind="TEACHER", lane="BA", **overrides):
    return get_success_data(api_client.create_employee(
        create_employee_payload(building_id, employee_kind=kind, base_lane=lane,
                                **overrides), COORD))


def make_teacher(building_id, lane="BA", **overrides):
    return make_employee(building_id, kind="TEACHER", lane=lane, **overrides)


def make_admin(building_id, lane="DOC", **overrides):
    return make_employee(building_id, kind="ADMIN", lane=lane, **overrides)


def make_instructor(building_id, lane="MA", **overrides):
    return make_employee(building_id, kind="SPECIALIST", lane=lane, **overrides)


def make_course(**overrides):
    return get_success_data(api_client.create_course(create_course_payload(**overrides), COORD))


def make_section(course_id, instructor_id, building_id, **overrides):
    """Create a DRAFT section (no meetings)."""
    return get_success_data(api_client.create_section(
        create_section_payload(course_id, instructor_id, building_id, **overrides), COORD))


def add_meeting(section_id, starts_at=STD_MEETING_START, ends_at=STD_MEETING_END,
                room=STD_ROOM):
    return get_success_data(api_client.add_meeting(
        section_id, create_meeting_payload(starts_at=starts_at, ends_at=ends_at, room=room),
        COORD))


def publish_section(section_id):
    return get_success_data(api_client.publish_section(section_id, COORD))


# --- Tier 2: catalog scenario --------------------------------------------

def setup_catalog_scenario(course_overrides=None, section_overrides=None,
                           meeting_times=None, with_budget=None):
    """Building + instructor + course + section (PUBLISHED) with meeting(s).

    with_budget: when set to an int, also creates an OPEN FY2026 budget of that
    many cents for the building. Returns a namespace with every entity.
    """
    set_clock(CLOCK_INIT)
    building = make_building()
    budget = make_budget(building["id"], allocated_cents=with_budget) if with_budget is not None else None
    instructor = make_instructor(building["id"])
    course = make_course(**(course_overrides or {}))
    section = make_section(course["id"], instructor["id"], building["id"],
                           **(section_overrides or {}))
    times = meeting_times if meeting_times is not None else [
        (STD_MEETING_START, STD_MEETING_END, STD_ROOM)
    ]
    meetings = [add_meeting(section["id"], s, e, r) for (s, e, r) in times]
    section = publish_section(section["id"])
    return SimpleNamespace(building=building, budget=budget, instructor=instructor,
                           course=course, section=section, meetings=meetings)


# --- Tier 3: registration lifecycle --------------------------------------

def register_teacher(teacher_id, section_id, **payload_overrides):
    """Register a teacher for a section as the teacher themselves (201 data)."""
    return get_success_data(api_client.create_registration(
        create_registration_payload(teacher_id, section_id, **payload_overrides),
        make_teacher_headers(teacher_id)))


def record_marks(meeting_id, instructor_id, records):
    """Bulk-record attendance as the section's assigned instructor."""
    return get_success_data(api_client.record_attendance(
        meeting_id, {"records": records}, make_instructor_headers(instructor_id)))


def verify_registration(registration_id, instructor_id):
    return get_success_data(api_client.verify_attendance(
        registration_id, make_instructor_headers(instructor_id)))


def waive_registration_survey(registration_id, reason="coordinator waiver"):
    return get_success_data(api_client.waive_survey(
        registration_id, {"reason": reason}, COORD))


def run_ops():
    return get_success_data(api_client.run_ops(COORD))


def prepare_completable_registration(registration_id, instructor_id, meetings,
                                     survey="waive", teacher_id=None):
    """PRESENT on every meeting + verify + survey satisfied, then move the section
    to IN_SESSION via the logical clock and one ops run. Returns nothing; the
    registration is then ready for POST .../complete."""
    for m in meetings:
        record_marks(m["id"], instructor_id,
                     [{"registration_id": registration_id, "mark": "PRESENT"}])
    verify_registration(registration_id, instructor_id)
    if survey == "waive":
        waive_registration_survey(registration_id)
    elif survey == "submit":
        assert teacher_id is not None, "survey='submit' needs the owning teacher_id"
        get_success_data(api_client.submit_survey(
            registration_id, create_survey_payload(), make_teacher_headers(teacher_id)))
    set_clock(CLOCK_IN_SESSION)
    run_ops()


def complete_registration(registration_id):
    return get_success_data(api_client.complete_registration(registration_id, COORD))


def setup_completed_course(clock_hours=24, fee_cents=0, course_overrides=None,
                           section_overrides=None, with_budget=None,
                           teacher_lane="BA", aligned_plan=None):
    """Full chain: one teacher completes a course and holds a COURSE_COMPLETION
    TranscriptEntry. Returns a namespace with building, budget, teacher,
    instructor, course, section, meetings, registration, entries."""
    merged_course = {"clock_hours": clock_hours, "fee_cents": fee_cents}
    merged_course.update(course_overrides or {})
    sc = setup_catalog_scenario(course_overrides=merged_course,
                                section_overrides=section_overrides,
                                with_budget=with_budget)
    teacher = make_teacher(sc.building["id"], lane=teacher_lane)
    payload = {}
    if aligned_plan is not None:
        focus = aligned_plan["focus_areas"][0]
        payload = {"growth_plan_id": aligned_plan["id"], "aligned_focus_area": focus}
    registration = register_teacher(teacher["id"], sc.section["id"], **payload)
    prepare_completable_registration(registration["id"], sc.instructor["id"],
                                     sc.meetings, survey="waive")
    registration = complete_registration(registration["id"])
    entries, _meta = _list_transcript(teacher["id"])
    return SimpleNamespace(building=sc.building, budget=sc.budget,
                           instructor=sc.instructor, course=sc.course,
                           section=sc.section, meetings=sc.meetings,
                           teacher=teacher, registration=registration,
                           entries=entries)


def _list_transcript(employee_id, params=None):
    res = api_client.get_transcript(employee_id, COORD, params=params)
    body = res.json()
    return body["data"], body.get("meta", {})


def list_transcript(employee_id, params=None):
    """Public wrapper: transcript rows for an employee (list payload + meta)."""
    return _list_transcript(employee_id, params=params)


# --- Tier 3: growth plans -------------------------------------------------

def make_growth_plan(teacher, school_year=STD_SCHOOL_YEAR, target_credits=2.0,
                     focus_areas=("math",), approve=False, admin=None):
    """Create a plan as the teacher (OCC: expected_employee_version = current
    Employee.version). Optionally walk SUBMITTED -> APPROVED with a
    building-scoped admin. Returns the plan as of its last transition."""
    current = get_success_data(api_client.get_employee(teacher["id"], COORD))
    plan = get_success_data(api_client.create_growth_plan(
        create_growth_plan_payload(
            teacher["id"], current["version"], school_year=school_year,
            target_credits=target_credits, focus_areas=list(focus_areas)),
        make_teacher_headers(teacher["id"])))
    if approve:
        assert admin is not None, "approve=True needs an admin employee"
        get_success_data(api_client.submit_plan(plan["id"], make_teacher_headers(teacher["id"])))
        plan = get_success_data(api_client.approve_plan(
            plan["id"], make_building_admin_headers(admin["id"])))
    return plan


# --- Tier 3: compliance assignments ---------------------------------------

def make_assignment(employee_id, course_id, due_date="2027-06-01T00:00:00Z",
                    coordinator_id="coord-1"):
    return get_success_data(api_client.create_assignment(
        create_assignment_payload(employee_id, course_id, due_date=due_date),
        make_coordinator_headers(coordinator_id)))


# --- Tier 3: workshops ------------------------------------------------------

def make_workshop(teacher_id, **overrides):
    """Create a DRAFT workshop request as the teacher themselves."""
    return get_success_data(api_client.create_workshop(
        create_workshop_payload(teacher_id, **overrides), make_teacher_headers(teacher_id)))


def workshop_to_submitted(workshop_id, teacher_id):
    return get_success_data(api_client.submit_workshop(
        workshop_id, make_teacher_headers(teacher_id)))


def workshop_to_approved(workshop_id, teacher_id, admin_id):
    workshop_to_submitted(workshop_id, teacher_id)
    return get_success_data(api_client.approve_workshop(
        workshop_id, make_building_admin_headers(admin_id)))


def workshop_to_attended(workshop_id, teacher_id, admin_id, actual_hours,
                         receipt_cents, evidence_clock):
    """DRAFT -> SUBMITTED -> APPROVED -> (clock to evidence date) -> ATTENDED."""
    workshop_to_approved(workshop_id, teacher_id, admin_id)
    set_clock(evidence_clock)
    return get_success_data(api_client.complete_workshop(
        workshop_id, {"actual_hours": actual_hours, "receipt_cents": receipt_cents},
        make_teacher_headers(teacher_id)))


# --- Tier 3: audit cases ----------------------------------------------------

def make_audit_case(employee_id, fiscal_year=STD_FISCAL_YEAR, auditor_id="aud-1"):
    return get_success_data(api_client.create_audit_case(
        create_audit_case_payload(employee_id, fiscal_year=fiscal_year),
        make_auditor_headers(auditor_id)))
