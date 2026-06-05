"""Composite setup helpers.

Encapsulates the multi-step preambles that the design-index test recipes share:
setting the logical clock, creating employees and published courses, enrolling
and starting learners, completing/failing enrollments, building published paths
and path enrollments, and driving overdue state. Tests import these by name and
focus on the trigger + assertions.

Every helper uses get_success_data() (lenient 2xx validator) for setup steps so a
broken precondition surfaces as a clear "Setup step failed" rather than a confusing
assertion. Each test runs against a fresh, empty database (the harness restarts the
server before every test), so every helper builds its preconditions from scratch.

Identity threading: Learner is entity_backed:Employee. Any ownership-gated learner
call (start / quiz-attempts / tracking-sessions) uses make_learner_headers(emp_id)
with the real employee id — never the shared TEST_USERS["learner_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_learner_headers
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]

DEFAULT_CLOCK = "2026-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(current_utc: str = DEFAULT_CLOCK):
    """Set the deterministic logical clock to current_utc (defaults to DEFAULT_CLOCK)."""
    return get_success_data(api_client.set_clock(f.clock_payload(current_utc), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: leaf entities
# ---------------------------------------------------------------------------
def create_employee(clock=DEFAULT_CLOCK, set_clock_first=False, **overrides) -> dict:
    """Create one ACTIVE employee. Returns the employee object."""
    if set_clock_first:
        set_clock(clock)
    return get_success_data(
        api_client.create_employee(f.create_employee_payload(**overrides), ADMIN)
    )


def create_course(**overrides) -> dict:
    """Create one DRAFT course. Returns the course object."""
    return get_success_data(
        api_client.create_course(f.create_course_payload(**overrides), ADMIN)
    )


def create_published_course(**overrides) -> dict:
    """Create a course and publish it (DRAFT → PUBLISHED). Returns the course."""
    course = create_course(**overrides)
    get_success_data(api_client.publish_course(course["id"], ADMIN))
    return get_success_data(api_client.get_course(course["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: enrollment hierarchy
# ---------------------------------------------------------------------------
def setup_clock_employee_published_course(clock=DEFAULT_CLOCK, course_overrides=None,
                                          employee_overrides=None):
    """Clock set + one employee + one PUBLISHED course. Returns (employee, course)."""
    set_clock(clock)
    emp = create_employee(**(employee_overrides or {}))
    course = create_published_course(**(course_overrides or {}))
    return emp, course


def create_enrollment(employee_id, course_id, **overrides) -> dict:
    """Create a NOT_STARTED course enrollment. Returns the enrollment."""
    return get_success_data(
        api_client.create_enrollment(
            f.create_enrollment_payload(employee_id, course_id, **overrides), ADMIN
        )
    )


def setup_enrollment(clock=DEFAULT_CLOCK, course_overrides=None, enrollment_overrides=None,
                     employee_overrides=None):
    """Clock + employee + PUBLISHED course + NOT_STARTED enrollment.
    Returns (employee, course, enrollment)."""
    emp, course = setup_clock_employee_published_course(
        clock=clock, course_overrides=course_overrides, employee_overrides=employee_overrides
    )
    enr = create_enrollment(emp["id"], course["id"], **(enrollment_overrides or {}))
    return emp, course, enr


def setup_started_enrollment(clock=DEFAULT_CLOCK, course_overrides=None,
                             enrollment_overrides=None, employee_overrides=None):
    """Clock + employee + PUBLISHED course + enrollment STARTED (IN_PROGRESS).
    Returns (employee, course, enrollment_after_start). The returned enrollment
    carries the post-start version for use as expected_enrollment_version."""
    emp, course, enr = setup_enrollment(
        clock=clock, course_overrides=course_overrides,
        enrollment_overrides=enrollment_overrides, employee_overrides=employee_overrides,
    )
    started = get_success_data(
        api_client.start_enrollment(enr["id"], make_learner_headers(emp["id"]))
    )
    return emp, course, started


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts (complete / fail)
# ---------------------------------------------------------------------------
def submit_attempt(enrollment_id, employee_id, score, expected_version):
    """Submit one quiz attempt as the owning learner. Returns the attempt object."""
    return get_success_data(
        api_client.create_quiz_attempt(
            enrollment_id, f.quiz_attempt_payload(score, expected_version),
            make_learner_headers(employee_id),
        )
    )


def get_enrollment(enrollment_id, headers=None):
    return get_success_data(api_client.get_enrollment(enrollment_id, headers or ADMIN))


def complete_enrollment(clock=DEFAULT_CLOCK, pass_score=88, course_overrides=None,
                        enrollment_overrides=None, employee_overrides=None):
    """Full path to a COMPLETED enrollment with an issued ACTIVE certificate.

    Clock + employee + PUBLISHED course + enroll + start + one passing attempt.
    Returns (employee, course, enrollment_after_complete, certificate)."""
    emp, course, started = setup_started_enrollment(
        clock=clock, course_overrides=course_overrides,
        enrollment_overrides=enrollment_overrides, employee_overrides=employee_overrides,
    )
    submit_attempt(started["id"], emp["id"], pass_score, started["version"])
    enr = get_enrollment(started["id"])
    cert = get_certificate_for_enrollment(started["id"])
    return emp, course, enr, cert


def fail_single_attempt_enrollment(clock=DEFAULT_CLOCK, fail_score=40,
                                   course_overrides=None, employee_overrides=None):
    """A max_attempts=1 course; enroll + start + one failing attempt → FAILED.

    Returns (employee, course, started_enrollment) where started_enrollment carries
    the post-start version (the value that becomes stale after the failing attempt)."""
    overrides = {"max_attempts": 1, "passing_score": 70}
    overrides.update(course_overrides or {})
    emp, course, started = setup_started_enrollment(
        clock=clock, course_overrides=overrides, employee_overrides=employee_overrides,
    )
    submit_attempt(started["id"], emp["id"], fail_score, started["version"])
    return emp, course, started


def get_certificate_for_enrollment(enrollment_id) -> dict:
    """Look up the certificate minted for an enrollment via reverse-reachability."""
    data, _ = _paginated(
        api_client.list_certificates(ADMIN, params={"enrollment_id": enrollment_id})
    )
    assert data, f"no certificate found for enrollment {enrollment_id}"
    return data[0]


def get_employee_dashboard(employee_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_employee_dashboard(employee_id, headers or ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 4: tracking sessions
# ---------------------------------------------------------------------------
def open_session(enrollment_id, employee_id) -> dict:
    """Open an INITIALIZED tracking session on a started enrollment."""
    return get_success_data(
        api_client.open_tracking_session(enrollment_id, make_learner_headers(employee_id))
    )


def setup_running_session_with_score(clock=DEFAULT_CLOCK, reported_score=90,
                                     course_overrides=None, employee_overrides=None):
    """Started enrollment + open session + one commit carrying reported_score.

    Returns (employee, course, started_enrollment, session). The session is RUNNING
    after the commit; the enrollment carries its post-start version."""
    emp, course, started = setup_started_enrollment(
        clock=clock, course_overrides=course_overrides, employee_overrides=employee_overrides,
    )
    sess = open_session(started["id"], emp["id"])
    get_success_data(
        api_client.commit_tracking_session(
            sess["id"], f.commit_session_payload("PASSED", 100, reported_score=reported_score),
            make_learner_headers(emp["id"]),
        )
    )
    return emp, course, started, sess


# ---------------------------------------------------------------------------
# Tier 5: learning paths
# ---------------------------------------------------------------------------
def setup_published_path(num_steps=3, enforce_sequence=False, weights=None,
                         mandatory=None, clock=DEFAULT_CLOCK, set_clock_first=True):
    """Build a PUBLISHED path of `num_steps` PUBLISHED-course steps.

    Returns (path, [course, ...]). sequence_index runs 1..N contiguously.
    weights / mandatory may pin per-step values (defaults: weight 1, mandatory True)."""
    if set_clock_first:
        set_clock(clock)
    weights = weights or [1] * num_steps
    mandatory = mandatory if mandatory is not None else [True] * num_steps
    courses = [create_published_course() for _ in range(num_steps)]
    path = get_success_data(
        api_client.create_learning_path(
            f.create_learning_path_payload(enforce_sequence=enforce_sequence), ADMIN
        )
    )
    for i, course in enumerate(courses):
        get_success_data(
            api_client.add_path_step(
                path["id"],
                f.add_path_step_payload(
                    course["id"], i + 1, is_mandatory=mandatory[i], weight=weights[i]
                ),
                ADMIN,
            )
        )
    get_success_data(api_client.publish_learning_path(path["id"], ADMIN))
    return path, courses


def create_path_enrollment(employee_id, learning_path_id, **overrides) -> dict:
    """Enroll an employee into a path; fans out child course enrollments."""
    return get_success_data(
        api_client.create_path_enrollment(
            f.create_path_enrollment_payload(employee_id, learning_path_id, **overrides), ADMIN
        )
    )


def child_enrollment_for(path_enrollment_id, course_id) -> dict:
    """Find the child course enrollment of a path enrollment for a given course."""
    params = {"path_enrollment_id": path_enrollment_id, "course_id": course_id}
    data, _ = _paginated(api_client.list_enrollments(ADMIN, params=params))
    assert data, f"no child enrollment for path {path_enrollment_id}, course {course_id}"
    return data[0]


def child_enrollments(path_enrollment_id) -> list:
    """All child enrollments of a path enrollment."""
    data, _ = _paginated(
        api_client.list_enrollments(ADMIN, params={"path_enrollment_id": path_enrollment_id})
    )
    return data


def complete_child_step(path_enrollment_id, course_id, employee_id, pass_score=90):
    """Start + pass the child enrollment of a path step. Returns the completed child."""
    child = child_enrollment_for(path_enrollment_id, course_id)
    started = get_success_data(
        api_client.start_enrollment(child["id"], make_learner_headers(employee_id))
    )
    submit_attempt(started["id"], employee_id, pass_score, started["version"])
    return get_enrollment(started["id"])


def get_path_enrollment(path_enrollment_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_path_enrollment(path_enrollment_id, headers or ADMIN)
    )


# ---------------------------------------------------------------------------
# Assignment rules
# ---------------------------------------------------------------------------
def create_assignment_rule(**overrides) -> dict:
    return get_success_data(
        api_client.create_assignment_rule(f.create_assignment_rule_payload(**overrides), ADMIN)
    )


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------
def run_escalations() -> dict:
    return get_success_data(api_client.run_escalations(ADMIN))


# ---------------------------------------------------------------------------
# internal
# ---------------------------------------------------------------------------
def _paginated(response):
    """Return (data_list, meta) from a 2xx list response without status pinning."""
    body = get_success_data(response)
    # get_success_data returns body["data"]; meta is on the full envelope, but
    # list helpers here only need the data list.
    return body, None
