"""Composite setup helpers for the K-12 SIS API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before each test. Setup calls use
get_success_data() (lenient) so a setup break surfaces as a clear "Setup failed".

Identity note: all roles are opaque (PRD §2.1); X-User-ID is recorded but not
matched to entity ids. Where a test must control which opaque identity a record
remembers (segregation of duties §2.10, the guardian check §2.4, adjudicator
matching §3.9), the helpers accept that identity as a parameter and thread it
through the relevant builder.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data, build_user_headers
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_registrar_headers,
    make_teacher_headers,
    make_administrator_headers,
    make_state_reporting_officer_headers,
)
from . import factories as F

_REG = TEST_USERS["registrar_headers"]
_TEACH = TEST_USERS["teacher_headers"]

_ssid = itertools.count(1)
_ccode = itertools.count(1)


def _ssid_next():
    return f"SSID-{next(_ssid):06d}"


def _ccode_next():
    return f"C{next(_ccode):06d}"


# ---------------------------------------------------------------------------
# Tier 1: primitive creators (single resource, returns the created object)
# ---------------------------------------------------------------------------
def create_school(ada_method="AGGREGATE_MEMBERSHIP", minimum_daily_minutes=240,
                  session_total_days=180, name="Test School", state_code="CA"):
    """Create a school. Returns the school object."""
    payload = {
        "name": name,
        "state_code": state_code,
        "ada_method": ada_method,
        "minimum_daily_minutes": minimum_daily_minutes,
        "session_total_days": session_total_days,
    }
    return get_success_data(api_client.create_school(payload, _REG))


def advance_clock(school_id, by_days):
    """Advance a school's deterministic clock by `by_days`. Returns the school."""
    return get_success_data(
        api_client.advance_clock(school_id, {"by_days": by_days}, _REG)
    )


def create_student(school_id, state_student_id=None, grade_level="9", **overrides):
    payload = F.create_student_payload(
        school_id,
        state_student_id=state_student_id or _ssid_next(),
        grade_level=grade_level,
        **overrides,
    )
    return get_success_data(api_client.create_student(payload, _REG))


def create_enrollment(student_id, entry_day_index=1, fte=None):
    payload = {"student_id": student_id, "entry_day_index": entry_day_index}
    if fte is not None:
        payload["fte"] = fte
    return get_success_data(api_client.create_enrollment(payload, _REG))


def create_course(school_id, grading_mode="STANDARDS", credit_value=None, course_code=None):
    payload = {
        "school_id": school_id,
        "course_code": course_code or _ccode_next(),
        "title": "Test Course",
        "grading_mode": grading_mode,
    }
    if credit_value is not None:
        payload["credit_value"] = credit_value
    return get_success_data(api_client.create_course(payload, _REG))


def create_section(course_id, period=1, meeting_minutes=None, capacity=None,
                   teacher_user_id="teacher-1"):
    payload = {"course_id": course_id, "teacher_user_id": teacher_user_id, "period": period}
    if meeting_minutes is not None:
        payload["meeting_minutes"] = meeting_minutes
    if capacity is not None:
        payload["capacity"] = capacity
    return get_success_data(api_client.create_section(payload, _REG))


def seat(enrollment_id, section_id):
    """Seat an enrollment into a section. Returns the schedule assignment."""
    return get_success_data(
        api_client.create_schedule_assignment(
            {"enrollment_id": enrollment_id, "section_id": section_id}, _REG
        )
    )


def post_attendance(schedule_assignment_id, day_index, code, as_teacher=True):
    headers = _TEACH if as_teacher else _REG
    return get_success_data(
        api_client.create_attendance_record(
            {"schedule_assignment_id": schedule_assignment_id, "day_index": day_index, "code": code},
            headers,
        )
    )


def post_standard_score(schedule_assignment_id, standard_code, mastery_level=None,
                        weight=None, percentage_points=None):
    payload = {"schedule_assignment_id": schedule_assignment_id, "standard_code": standard_code}
    if mastery_level is not None:
        payload["mastery_level"] = mastery_level
    if weight is not None:
        payload["weight"] = weight
    if percentage_points is not None:
        payload["percentage_points"] = percentage_points
    return get_success_data(api_client.create_standard_score(payload, _TEACH))


# ---------------------------------------------------------------------------
# Tier 2: composite scenarios (parent + child + resources)
# ---------------------------------------------------------------------------
def setup_enrolled_student(ada_method="AGGREGATE_MEMBERSHIP", minimum_daily_minutes=240,
                           session_total_days=180, clock_days=0, entry_day_index=1, fte=None,
                           grade_level="9"):
    """School + student + ACTIVE enrollment, clock advanced to `clock_days`.

    Returns dict with keys: school, student, enrollment.
    """
    school = create_school(ada_method, minimum_daily_minutes, session_total_days)
    if clock_days > 0:
        advance_clock(school["id"], clock_days)
    student = create_student(school["id"], grade_level=grade_level)
    enrollment = create_enrollment(student["id"], entry_day_index=entry_day_index, fte=fte)
    return {"school": school, "student": student, "enrollment": enrollment}


def setup_seated_student(grading_mode="STANDARDS", credit_value=None, period=1,
                         meeting_minutes=None, capacity=None, **scenario_kwargs):
    """School + student + enrollment + course + section + one seated assignment.

    Returns dict with: school, student, enrollment, course, section, assignment.
    """
    base = setup_enrolled_student(**scenario_kwargs)
    course = create_course(base["school"]["id"], grading_mode=grading_mode, credit_value=credit_value)
    section = create_section(course["id"], period=period, meeting_minutes=meeting_minutes, capacity=capacity)
    assignment = seat(base["enrollment"]["id"], section["id"])
    base.update({"course": course, "section": section, "assignment": assignment})
    return base


# ---------------------------------------------------------------------------
# Tier 3: ADA funding-report scenarios
# ---------------------------------------------------------------------------
def setup_school_single_present_enrollment(ada_method, clock_days, present_days,
                                           meeting_minutes=240, session_total_days=180,
                                           minimum_daily_minutes=240, entry_day_index=1, fte=None,
                                           absent_days=()):
    """One school + one enrollment seated in a meeting_minutes section, marked
    PRESENT on each day in `present_days` and ABSENT_UNEXCUSED on each in `absent_days`.

    Returns dict: school, student, enrollment, course, section, assignment.
    """
    ctx = setup_seated_student(
        ada_method=ada_method,
        minimum_daily_minutes=minimum_daily_minutes,
        session_total_days=session_total_days,
        clock_days=clock_days,
        entry_day_index=entry_day_index,
        fte=fte,
        meeting_minutes=meeting_minutes,
    )
    sa = ctx["assignment"]["id"]
    for d in present_days:
        post_attendance(sa, d, "PRESENT")
    for d in absent_days:
        post_attendance(sa, d, "ABSENT_UNEXCUSED")
    return ctx


def draft_ada_report(school_id, as_of_day_index, drafter_user_id="registrar-d"):
    """Draft an ADA funding report. Returns the report object (carries version)."""
    headers = make_registrar_headers(drafter_user_id)
    return get_success_data(
        api_client.create_ada_report(
            {"school_id": school_id, "as_of_day_index": as_of_day_index}, headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: discipline scenarios
# ---------------------------------------------------------------------------
def file_incident(enrollment_id, category="DISRUPTION", severity=2, incident_day_index=1,
                  referring_user_id="teacher-1", as_role="Teacher"):
    """File a discipline incident as a specific opaque identity. Returns the incident."""
    headers = build_user_headers(referring_user_id, as_role)
    payload = {
        "enrollment_id": enrollment_id,
        "category": category,
        "severity": severity,
        "incident_day_index": incident_day_index,
    }
    return get_success_data(api_client.create_discipline_incident(payload, headers))


def begin_review(incident_id, adjudicator_user_id="admin-1"):
    """Open review on an incident (pins adjudicator). Returns the incident."""
    headers = make_administrator_headers(adjudicator_user_id)
    return get_success_data(api_client.begin_review(incident_id, headers))


def attach_consequence(incident_id, consequence_type="WARNING", adjudicator_user_id="admin-1",
                       start_day_index=None, duration_days=None):
    """Attach a consequence as the pinned adjudicator. Returns the consequence."""
    headers = make_administrator_headers(adjudicator_user_id)
    payload = {"type": consequence_type}
    if start_day_index is not None:
        payload["start_day_index"] = start_day_index
    if duration_days is not None:
        payload["duration_days"] = duration_days
    return get_success_data(api_client.create_consequence(incident_id, payload, headers))


def setup_incident_under_review(referring_user_id="teacher-1", adjudicator_user_id="admin-1",
                                category="DISRUPTION", severity=2, incident_day_index=1,
                                **scenario_kwargs):
    """Enrolled student + incident filed by referring_user_id, taken UNDER_REVIEW by
    adjudicator_user_id.

    Returns dict: school, student, enrollment, incident (+ any seated context if
    `seated=True` passed, see setup_incident_with_attendance).
    """
    base = setup_enrolled_student(**scenario_kwargs)
    incident = file_incident(
        base["enrollment"]["id"], category=category, severity=severity,
        incident_day_index=incident_day_index, referring_user_id=referring_user_id,
    )
    begin_review(incident["id"], adjudicator_user_id=adjudicator_user_id)
    base["incident"] = get_success_data(
        api_client.get_discipline_incident(incident["id"], _REG)
    )
    return base


def setup_oss_ready_scenario(present_days, incident_day_index=2, clock_days=5,
                             meeting_minutes=240, ada_method="AGGREGATE_MEMBERSHIP",
                             minimum_daily_minutes=240, referring_user_id="teacher-1",
                             adjudicator_user_id="admin-1", category="FIGHTING", severity=4):
    """Full preamble for an OSS suspension cascade test: an enrolled student PRESENT
    on each day in `present_days`, seated in a meeting_minutes section, with an
    incident taken UNDER_REVIEW by adjudicator_user_id.

    Returns dict: school, student, enrollment, course, section, assignment, incident.
    """
    ctx = setup_seated_student(
        ada_method=ada_method,
        minimum_daily_minutes=minimum_daily_minutes,
        clock_days=clock_days,
        meeting_minutes=meeting_minutes,
    )
    sa = ctx["assignment"]["id"]
    for d in present_days:
        post_attendance(sa, d, "PRESENT")
    incident = file_incident(
        ctx["enrollment"]["id"], category=category, severity=severity,
        incident_day_index=incident_day_index, referring_user_id=referring_user_id,
    )
    begin_review(incident["id"], adjudicator_user_id=adjudicator_user_id)
    ctx["incident"] = get_success_data(api_client.get_discipline_incident(incident["id"], _REG))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: report-card scenarios
# ---------------------------------------------------------------------------
def open_report_card(enrollment_id, term_label="Q1"):
    """Open a DRAFT report card (carries version). Returns the report card."""
    return get_success_data(
        api_client.create_report_card({"enrollment_id": enrollment_id, "term_label": term_label}, _TEACH)
    )


def setup_report_card_ready_single_section(grading_mode="STANDARDS", mastery_level=3,
                                           percentage_points=None, weight=1.0, credit_value=None,
                                           standard_code="STD.1"):
    """Enrolled student seated in one section with one standard score, plus a DRAFT
    report card.

    Returns dict: school, student, enrollment, course, section, assignment,
    report_card (carries version).
    """
    ctx = setup_seated_student(grading_mode=grading_mode, credit_value=credit_value)
    post_standard_score(
        ctx["assignment"]["id"], standard_code, mastery_level=mastery_level,
        weight=weight, percentage_points=percentage_points,
    )
    ctx["report_card"] = open_report_card(ctx["enrollment"]["id"])
    return ctx


def finalize_report_card(report_card_id, expected_version):
    return get_success_data(
        api_client.finalize_report_card(
            report_card_id, {"expected_report_card_version": expected_version}, _TEACH
        )
    )
