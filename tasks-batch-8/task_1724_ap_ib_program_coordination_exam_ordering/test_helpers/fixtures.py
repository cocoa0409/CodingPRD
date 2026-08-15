"""Composite setup helpers for the PRD §3 workflows.

Every helper builds its preconditions from scratch through PRD-declared
endpoints — the runner restarts the server before every test, so nothing is
carried over between tests. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors instead of confusing assertions.

Identity threading: Student and Teacher are entity-backed roles (PRD §2.1), so
ownership-gated calls always go through make_student_headers(entity_id) /
make_teacher_headers(entity_id) with the id of the entity just created.

Role headers used internally:
  COORD      ApCoordinator (cycles, courses, teachers, students, orders,
             sessions, proctor assignments, application decisions, reports,
             clock)
  REGISTRAR  Registrar (score release, transcript posting)
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    administer_session_payload,
    create_exam_cycle_payload,
    create_exam_order_payload,
    create_exam_session_payload,
    create_fee_reduction_application_payload,
    create_irregularity_report_payload,
    create_proctor_assignment_payload,
    create_registration_payload,
    create_student_payload,
    create_teacher_authorization_payload,
    create_teacher_payload,
    create_course_payload,
    patch_exam_order_payload,
    release_scores_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_student_headers, make_teacher_headers

COORD = TEST_USERS["coordinator_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (runs the authorization-expiry sweep)."""
    res = api_client.set_current_utc(set_clock_payload(to_iso8601), COORD)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: cycles, courses, teachers, students (PRD §3.1-§3.3)
# ---------------------------------------------------------------------------

def make_cycle(**overrides) -> dict:
    """Create an ExamCycle in SETUP."""
    res = api_client.create_exam_cycle(create_exam_cycle_payload(**overrides), COORD)
    return get_success_data(res)


def make_open_cycle(**overrides) -> dict:
    """Create an ExamCycle and open it (SETUP -> OPEN)."""
    cycle = make_cycle(**overrides)
    res = api_client.open_exam_cycle(cycle["id"], COORD)
    return get_success_data(res)


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_exam_cycle(cycle_id, COORD))


def make_course(cycle_id: str, **overrides) -> dict:
    """Create a Course (born SUSPENDED with authorized_teacher_count 0)."""
    res = api_client.create_course(
        create_course_payload(cycle_id, **overrides), COORD
    )
    return get_success_data(res)


def get_course(course_id: str) -> dict:
    return get_success_data(api_client.get_course(course_id, COORD))


def make_teacher(**overrides) -> dict:
    res = api_client.create_teacher(create_teacher_payload(**overrides), COORD)
    return get_success_data(res)


def make_authorization(teacher_id: str, course_id: str) -> dict:
    """Open a TeacherAuthorization (born PENDING_TRAINING)."""
    res = api_client.create_teacher_authorization(
        create_teacher_authorization_payload(teacher_id, course_id), COORD
    )
    return get_success_data(res)


def get_authorization(authorization_id: str) -> dict:
    return get_success_data(
        api_client.get_teacher_authorization(authorization_id, COORD)
    )


def complete_training(authorization_id: str, teacher_id: str) -> dict:
    """The teacher on the record attests training (PENDING_TRAINING or EXPIRED
    -> AUTHORIZED). Ownership-gated: headers carry the teacher's own id."""
    res = api_client.complete_training(
        authorization_id, make_teacher_headers(teacher_id)
    )
    return get_success_data(res)


def authorize_teacher(teacher_id: str, course_id: str) -> dict:
    """Open + complete training. Returns the AUTHORIZED record."""
    auth = make_authorization(teacher_id, course_id)
    return complete_training(auth["id"], teacher_id)


def make_active_course(cycle_id: str, teacher=None, **overrides) -> tuple:
    """Course + one AUTHORIZED teacher so the course flips to ACTIVE.

    Returns (course, teacher, authorization).
    """
    course = make_course(cycle_id, **overrides)
    if teacher is None:
        teacher = make_teacher()
    auth = authorize_teacher(teacher["id"], course["id"])
    return get_course(course["id"]), teacher, auth


def make_student(**overrides) -> dict:
    res = api_client.create_student(create_student_payload(**overrides), COORD)
    return get_success_data(res)


def get_statement(student_id: str) -> dict:
    return get_success_data(api_client.get_student_statement(student_id, COORD))


# ---------------------------------------------------------------------------
# Tier 2: fee-reduction applications (PRD §3.3)
# ---------------------------------------------------------------------------

def make_application(student_id: str, cycle_id: str, **overrides) -> dict:
    """File a fee-reduction application as the owning student (SUBMITTED)."""
    res = api_client.create_fee_reduction_application(
        create_fee_reduction_application_payload(student_id, cycle_id, **overrides),
        make_student_headers(student_id),
    )
    return get_success_data(res)


def get_application(application_id: str) -> dict:
    return get_success_data(
        api_client.get_fee_reduction_application(application_id, COORD)
    )


def approve_application(application_id: str) -> dict:
    return get_success_data(
        api_client.approve_fee_reduction_application(application_id, COORD)
    )


def deny_application(application_id: str) -> dict:
    return get_success_data(
        api_client.deny_fee_reduction_application(application_id, COORD)
    )


def resubmit_application(application_id: str, student_id: str) -> dict:
    """Re-open a DENIED application; ownership-gated on the student."""
    return get_success_data(
        api_client.resubmit_fee_reduction_application(
            application_id, make_student_headers(student_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: registrations (PRD §3.3)
# ---------------------------------------------------------------------------

def make_registration(student_id: str, course_id: str, **overrides) -> dict:
    """Register a student for a course exam as that student (REGISTERED x
    PENDING). Ownership-gated: headers carry the student's own id."""
    res = api_client.create_registration(
        create_registration_payload(student_id, course_id, **overrides),
        make_student_headers(student_id),
    )
    return get_success_data(res)


def get_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_registration(registration_id, COORD))


def cancel_registration(registration_id: str, student_id: str = None) -> dict:
    """Cancel a REGISTERED registration. When student_id is given the owning
    student cancels; otherwise the coordinator does."""
    headers = COORD if student_id is None else make_student_headers(student_id)
    return get_success_data(api_client.cancel_registration(registration_id, headers))


# ---------------------------------------------------------------------------
# Tier 2/3: exam orders (PRD §3.4)
# ---------------------------------------------------------------------------

def make_order(cycle_id: str) -> dict:
    """Create the cycle's ExamOrder (born DRAFT; one per cycle)."""
    res = api_client.create_exam_order(create_exam_order_payload(cycle_id), COORD)
    return get_success_data(res)


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_exam_order(order_id, COORD))


def patch_order(order_id: str, expected_version, adjustments=None) -> dict:
    res = api_client.patch_exam_order(
        order_id, patch_exam_order_payload(expected_version, adjustments), COORD
    )
    return get_success_data(res)


def submit_order(order_id: str) -> dict:
    return get_success_data(api_client.submit_exam_order(order_id, COORD))


def lock_order(order_id: str) -> dict:
    return get_success_data(api_client.lock_exam_order(order_id, COORD))


def reconcile_order(order_id: str) -> dict:
    return get_success_data(api_client.reconcile_exam_order(order_id, COORD))


def make_submitted_order(cycle_id: str) -> dict:
    """Create + submit the cycle's order. Returns the SUBMITTED order."""
    order = make_order(cycle_id)
    return submit_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 2/3: sessions and proctors (PRD §3.5)
# ---------------------------------------------------------------------------

def make_session(course_id: str, **overrides) -> dict:
    """Schedule an ExamSession (born SCHEDULED)."""
    res = api_client.create_exam_session(
        create_exam_session_payload(course_id, **overrides), COORD
    )
    return get_success_data(res)


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_exam_session(session_id, COORD))


def make_proctor_assignment(session_id: str, teacher_id: str) -> dict:
    res = api_client.create_proctor_assignment(
        create_proctor_assignment_payload(session_id, teacher_id), COORD
    )
    return get_success_data(res)


def get_proctor_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_proctor_assignment(assignment_id, COORD))


def release_proctor_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.release_proctor_assignment(assignment_id, COORD))


def cancel_session(session_id: str) -> dict:
    return get_success_data(api_client.cancel_exam_session(session_id, COORD))


def administer_session(session_id: str, present_registration_ids) -> dict:
    """Record attendance. Caller must have moved the clock to/after end_at."""
    res = api_client.administer_exam_session(
        session_id, administer_session_payload(present_registration_ids), COORD
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 3: irregularity reports (PRD §3.6)
# ---------------------------------------------------------------------------

def file_irregularity(session_id: str, proctor_teacher_id: str, **overrides) -> dict:
    """File a report as the session's ASSIGNED proctor (ownership-gated)."""
    res = api_client.create_irregularity_report(
        create_irregularity_report_payload(session_id, **overrides),
        make_teacher_headers(proctor_teacher_id),
    )
    return get_success_data(res)


def get_report(report_id: str) -> dict:
    return get_success_data(api_client.get_irregularity_report(report_id, COORD))


def resolve_report(report_id: str) -> dict:
    return get_success_data(api_client.resolve_irregularity_report(report_id, COORD))


def cancel_scores_report(report_id: str) -> dict:
    return get_success_data(
        api_client.cancel_scores_irregularity_report(report_id, COORD)
    )


# ---------------------------------------------------------------------------
# Tier 3: score release and transcript posting (PRD §3.7)
# ---------------------------------------------------------------------------

def release_scores(cycle_id: str, scores) -> dict:
    """Bulk release by the Registrar. scores: [{registration_id, score}]."""
    res = api_client.release_scores(cycle_id, release_scores_payload(scores), REGISTRAR)
    return get_success_data(res)


def post_to_transcript(registration_id: str) -> dict:
    return get_success_data(api_client.post_to_transcript(registration_id, REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 4/5: composite lifecycle scenarios
# ---------------------------------------------------------------------------

def setup_sat_scenario(
    num_students: int = 1,
    present: int = 1,
    cycle_overrides=None,
    course_overrides=None,
    session_overrides=None,
    with_proctor: bool = False,
):
    """Full exam-day setup ending in an ADMINISTERED session.

    Builds: OPEN cycle -> ACTIVE course (instructor authorized) -> N students
    each registered -> SCHEDULED session -> [optional proctor assigned while
    the session is still SCHEDULED, per the assignment state gate] -> clock
    past session end -> administer with the first `present` registrations
    listed.

    Returns a dict with cycle, course, instructor, authorization, students,
    registrations, session (and proctor, assignment when with_proctor).
    """
    cycle_overrides = cycle_overrides or {}
    course_overrides = course_overrides or {}
    session_overrides = session_overrides or {}

    cycle = make_open_cycle(**cycle_overrides)
    course, instructor, authorization = make_active_course(
        cycle["id"], **course_overrides
    )
    students = [make_student(full_name=f"Stu {i}") for i in range(num_students)]
    registrations = [
        make_registration(s["id"], course["id"]) for s in students
    ]
    session = make_session(course["id"], **session_overrides)
    result = {
        "cycle": cycle,
        "course": get_course(course["id"]),
        "instructor": instructor,
        "authorization": authorization,
        "students": students,
        "session": session,
    }
    if with_proctor:
        proctor = make_teacher(full_name="T Proctor", email="proc@x.edu")
        assignment = make_proctor_assignment(session["id"], proctor["id"])
        result["proctor"] = proctor
        result["assignment"] = assignment
    set_clock(C.AFTER_SESSION_END_AT)
    present_ids = [r["id"] for r in registrations[:present]]
    result["session"] = administer_session(session["id"], present_ids)
    result["registrations"] = [get_registration(r["id"]) for r in registrations]
    return result


def setup_released_registrations(scores, **scenario_kwargs):
    """SAT scenario plus score release at the cycle's release instant.

    `scores` maps registration indexes to scores, e.g. {0: 4, 1: 3}.
    Returns the scenario dict plus the release response payload.
    """
    scenario = setup_sat_scenario(**scenario_kwargs)
    cycle = scenario["cycle"]
    registrations = scenario["registrations"]
    set_clock(C.SCORE_RELEASE_AT)
    payload = [
        {"registration_id": registrations[i]["id"], "score": score}
        for i, score in scores.items()
    ]
    release = release_scores(cycle["id"], payload)
    scenario["release"] = release
    scenario["registrations"] = [
        get_registration(r["id"]) for r in registrations
    ]
    return scenario


def setup_under_investigation(category="TIMING_ERROR", details="Section 1 ran short"):
    """ADMINISTERED session (one SAT registration) with an ASSIGNED proctor who
    files a report: session ends UNDER_INVESTIGATION and the SAT record HELD.

    The proctor is assigned while the session is still SCHEDULED (the
    assignment state gate), then the sitting is administered, then the report
    is filed. Returns the scenario dict plus proctor, assignment, report.
    """
    scenario = setup_sat_scenario(num_students=1, present=1, with_proctor=True)
    proctor = scenario["proctor"]
    report = file_irregularity(
        scenario["session"]["id"], proctor["id"], category=category, details=details
    )
    scenario["report"] = report
    return scenario
