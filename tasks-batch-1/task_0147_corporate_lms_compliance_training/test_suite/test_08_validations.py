"""Business-rule validations: publish gates (recurrence config, empty path, sequence
contiguity), prerequisite DAG cycle, attempts-exhausted, prerequisite-not-met on
start, and assignment-rule exactly-one-target. Queue B (corner) — validations section.
"""
from test_helpers import (
    get_success_data,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    create_employee,
    create_course,
    create_published_course,
    create_enrollment,
    fail_single_attempt_enrollment,
    get_enrollment,
    make_learner_headers,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Corner/validations/publish_recurring_course_without_recurrence_months_returns_409
# ===========================================================================
def test_publish_recurring_course_without_recurrence_months_returns_409(api):
    """PRD §3.1: "If the course is recurring, its recurrence_months must be a positive
    integer at publish time, or the publish fails with ERR_RECURRENCE_CONFIG_INVALID."

    Design: Corner/validations/publish_recurring_course_without_recurrence_months_returns_409
    """
    set_clock()
    course = get_success_data(
        api.create_course(
            {"code": "RECBAD", "title": "RecBad", "content_type": "SCORM",
             "passing_score": 70, "is_recurring": True}, ADMIN
        )
    )
    resp = api.publish_course(course["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RECURRENCE_CONFIG_INVALID.value)


# ===========================================================================
# Corner/validations/publish_empty_path_returns_409
# ===========================================================================
def test_publish_path_with_no_steps_returns_409(api):
    """PRD §3.2: "it must contain at least one PathStep (else ERR_PATH_EMPTY)."

    Design: Corner/validations/publish_empty_path_returns_409
    """
    set_clock()
    path = get_success_data(
        api.create_learning_path(f.create_learning_path_payload(code="EMPTYP", enforce_sequence=True), ADMIN)
    )
    resp = api.publish_learning_path(path["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PATH_EMPTY.value)


# ===========================================================================
# Corner/validations/publish_path_with_noncontiguous_sequence_returns_409
# ===========================================================================
def test_publish_path_with_sequence_gap_returns_409(api):
    """PRD §3.2: "the set of sequence_index values must be the contiguous run 1 through
    N with no gaps and no duplicates (else ERR_PATH_SEQUENCE_INVALID)."

    Design: Corner/validations/publish_path_with_noncontiguous_sequence_returns_409
    """
    set_clock()
    ca = create_published_course(code="SQ1", passing_score=70)
    cb = create_published_course(code="SQ2", passing_score=70)
    path = get_success_data(
        api.create_learning_path(f.create_learning_path_payload(code="SEQP", enforce_sequence=True), ADMIN)
    )
    get_success_data(api.add_path_step(path["id"], f.add_path_step_payload(ca["id"], 1), ADMIN))
    get_success_data(api.add_path_step(path["id"], f.add_path_step_payload(cb["id"], 3), ADMIN))  # gap at 2
    resp = api.publish_learning_path(path["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PATH_SEQUENCE_INVALID.value)


# ===========================================================================
# Corner/validations/prerequisite_cycle_rejected_409
# ===========================================================================
def test_prerequisite_cycle_rejected_409(api):
    """PRD §3.1: "The prerequisite graph is a directed acyclic graph: adding an edge
    that would close a cycle across the existing CoursePrerequisite edges is rejected
    with ERR_PREREQUISITE_CYCLE."

    Design: Corner/validations/prerequisite_cycle_rejected_409
    """
    set_clock()
    a = create_course(code="CYA", passing_score=70)
    b = create_course(code="CYB", passing_score=70)
    get_success_data(api.add_course_prerequisite(a["id"], f.add_prerequisite_payload(b["id"]), ADMIN))
    resp = api.add_course_prerequisite(b["id"], f.add_prerequisite_payload(a["id"]), ADMIN)  # closes cycle
    validate_error(resp, ApiErrorId.ERR_PREREQUISITE_CYCLE.value)


# ===========================================================================
# Corner/validations/attempts_exhausted_returns_409
# ===========================================================================
def test_quiz_attempt_after_failed_single_attempt_returns_exhausted(api):
    """PRD §3.5: "A submission against a FAILED enrollment — whose cycle attempts are
    already exhausted — fails this check with ERR_ATTEMPTS_EXHAUSTED."

    Design: Corner/validations/attempts_exhausted_returns_409
    """
    emp, course, started = fail_single_attempt_enrollment(fail_score=40)
    learner = make_learner_headers(emp["id"])
    # Re-read the CURRENT version so the OCC check passes and the attempts check fires.
    current_version = get_enrollment(started["id"], learner)["version"]
    resp = api.create_quiz_attempt(
        started["id"], {"score": 95, "expected_enrollment_version": current_version}, learner,
    )
    validate_error(resp, ApiErrorId.ERR_ATTEMPTS_EXHAUSTED.value)


# ===========================================================================
# Corner/validations/prerequisite_not_met_on_start_returns_409
# ===========================================================================
def test_start_with_uncertified_prerequisite_returns_prerequisite_not_met(api):
    """PRD §3.7.1: "The course-prerequisite gate is satisfied only when, for the course
    being started, every prerequisite course recorded as a CoursePrerequisite edge has
    an ACTIVE certificate held by this same employee; absent that, starting is refused
    with ERR_PREREQUISITE_NOT_MET."

    Design: Corner/validations/prerequisite_not_met_on_start_returns_409
    """
    set_clock()
    emp = create_employee()
    pre = create_published_course(code="PRE2", passing_score=70)
    main = create_course(code="MAIN2", passing_score=70)
    get_success_data(api.add_course_prerequisite(main["id"], f.add_prerequisite_payload(pre["id"]), ADMIN))
    get_success_data(api.publish_course(main["id"], ADMIN))
    enr = create_enrollment(emp["id"], main["id"])
    resp = api.start_enrollment(enr["id"], make_learner_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET.value)


# ===========================================================================
# Corner/validations/assignment_rule_two_targets_returns_400
# ===========================================================================
def test_assignment_rule_with_both_targets_returns_400(api):
    """PRD §3.3: "points at exactly one of a course_id or a learning_path_id — setting
    neither or both is ERR_INVALID_REQUEST."

    Design: Corner/validations/assignment_rule_two_targets_returns_400
    """
    set_clock()
    course = create_published_course(code="AR2", passing_score=70)
    path = get_success_data(
        api.create_learning_path(f.create_learning_path_payload(code="ARLP", enforce_sequence=False), ADMIN)
    )
    get_success_data(api.add_path_step(path["id"], f.add_path_step_payload(course["id"], 1), ADMIN))
    get_success_data(api.publish_learning_path(path["id"], ADMIN))
    resp = api.create_assignment_rule(
        f.create_assignment_rule_payload(
            target_department="HR", target_job_role="IC",
            course_id=course["id"], learning_path_id=path["id"], due_in_days=30,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
