"""Priority-pair conflicts (higher-priority error wins) and cross-entity start gates
(course state, path-step sequence). Queue A (difficulty).
"""
from test_helpers import (
    get_success_data,
    validate_error,
    validate_paginated,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    create_employee,
    create_published_course,
    create_course,
    create_enrollment,
    fail_single_attempt_enrollment,
    setup_published_path,
    create_path_enrollment,
    child_enrollment_for,
    get_enrollment,
    make_learner_headers,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/
#   quiz_attempt_stale_version_state_beats_attempts_exhausted_constraint
# ===========================================================================
def test_stale_version_on_failed_enrollment_returns_stale_version_not_exhausted(api):
    """PRD §2.9: "This version check is evaluated before the business check for
    remaining attempts, so a stale submission against a FAILED enrollment yields
    ERR_STALE_VERSION and not the attempts-exhausted error."

    Design: Difficulty/priority_pair_validation_conflict/quiz_attempt_stale_version_state_beats_attempts_exhausted_constraint
    """
    emp, course, started = fail_single_attempt_enrollment(fail_score=40)
    # started["version"] is now stale (the failing attempt advanced the enrollment),
    # and the enrollment is FAILED (attempts exhausted). Re-submit with the stale value.
    resp = api.create_quiz_attempt(
        started["id"], {"score": 95, "expected_enrollment_version": started["version"]},
        make_learner_headers(emp["id"]),
    )
    assert resp.status_code == 412, f"expected HTTP 412, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_version_rejection_records_no_attempt(api):
    """PRD §2.9: "If that value does not equal the enrollment's current version, the
    submission is rejected with ERR_STALE_VERSION (HTTP 412), and no attempt is
    recorded."

    Design: Difficulty/priority_pair_validation_conflict/quiz_attempt_stale_version_state_beats_attempts_exhausted_constraint
    """
    emp, course, started = fail_single_attempt_enrollment(fail_score=40)
    learner = make_learner_headers(emp["id"])
    api.create_quiz_attempt(
        started["id"], {"score": 95, "expected_enrollment_version": started["version"]}, learner,
    )
    attempts, _ = validate_paginated(api.list_quiz_attempts(started["id"], learner))
    assert len(attempts) == 1, (
        f"only the original failing attempt should exist (stale write recorded nothing), "
        f"got {len(attempts)}"
    )


# ===========================================================================
# Difficulty/cross_entity_state_dependency/enrollment_start_requires_course_published
# ===========================================================================
def test_start_enrollment_on_draft_course_returns_course_not_published(api):
    """PRD §3.4: "the course must be PUBLISHED (else ERR_COURSE_NOT_PUBLISHED)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_start_requires_course_published
    """
    set_clock()
    emp = create_employee()
    course = create_course(passing_score=70)  # never published → DRAFT
    enr = create_enrollment(emp["id"], course["id"])
    resp = api.start_enrollment(enr["id"], make_learner_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_COURSE_NOT_PUBLISHED.value)


def test_start_on_draft_course_leaves_enrollment_not_started(api):
    """PRD §3.4: "On success the enrollment becomes IN_PROGRESS, its version
    increments." (so a rejected start must leave it NOT_STARTED)

    Design: Difficulty/cross_entity_state_dependency/enrollment_start_requires_course_published
    """
    set_clock()
    emp = create_employee()
    course = create_course(passing_score=70)
    enr = create_enrollment(emp["id"], course["id"])
    api.start_enrollment(enr["id"], make_learner_headers(emp["id"]))
    after = get_enrollment(enr["id"])
    assert after["status"] == "NOT_STARTED", f"rejected start stays NOT_STARTED, got {after['status']}"


# ===========================================================================
# Difficulty/cross_entity_state_dependency/path_step_start_requires_prior_step_completed
# ===========================================================================
def test_start_second_path_step_before_first_completed_is_locked(api):
    """PRD §3.7.1: "such a step may be started only after the immediately preceding
    step's child enrollment has reached COMPLETED, and a premature start is refused
    with ERR_PATH_STEP_LOCKED."

    Design: Difficulty/cross_entity_state_dependency/path_step_start_requires_prior_step_completed
    """
    set_clock()
    emp = create_employee(department="SALES", job_role="IC")
    path, courses = setup_published_path(num_steps=2, enforce_sequence=True, set_clock_first=False)
    pe = create_path_enrollment(emp["id"], path["id"])
    step2 = child_enrollment_for(pe["id"], courses[1]["id"])
    resp = api.start_enrollment(step2["id"], make_learner_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_PATH_STEP_LOCKED.value)


def test_locked_path_step_stays_not_started(api):
    """PRD §3.7.1: "the path-sequence gate applies only to enrollments that are steps
    of a path whose enforce_sequence is true: such a step may be started only after the
    immediately preceding step's child enrollment has reached COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/path_step_start_requires_prior_step_completed
    """
    set_clock()
    emp = create_employee(department="SALES", job_role="IC")
    path, courses = setup_published_path(num_steps=2, enforce_sequence=True, set_clock_first=False)
    pe = create_path_enrollment(emp["id"], path["id"])
    step2 = child_enrollment_for(pe["id"], courses[1]["id"])
    api.start_enrollment(step2["id"], make_learner_headers(emp["id"]))
    after = get_enrollment(step2["id"])
    assert after["status"] == "NOT_STARTED", f"locked step stays NOT_STARTED, got {after['status']}"
