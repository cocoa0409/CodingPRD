"""Action endpoints (rule sweep, reverse-reachability reads), RBAC denials and
authentication, OCC positive path, and immediate-consistency read-after-write.
Queue B (corner) — endpoints / rbac / cross_cutting_complexity_layers / consistency_model.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    create_employee,
    create_published_course,
    create_enrollment,
    setup_started_enrollment,
    setup_published_path,
    create_path_enrollment,
    create_assignment_rule,
    get_path_enrollment,
    get_enrollment,
    make_learner_headers,
    build_user_headers,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Corner/endpoints/apply_assignment_rule_creates_enrollments_for_matching_employees
# ===========================================================================
def test_apply_rule_enrolls_matching_employee_with_rule_id(api):
    """PRD §3.3: "for each match it creates one course Enrollment or, for a path-targeted
    rule, one PathEnrollment, stamping the new record's assignment_rule_id with the rule's
    id ... The sweep responds with the list of created_enrollment_ids ... and a created_count."

    Design: Corner/endpoints/apply_assignment_rule_creates_enrollments_for_matching_employees
    """
    set_clock("2026-03-01T00:00:00.000Z")
    emp = create_employee(department="ENGINEERING", job_role="IC")
    course = create_published_course(passing_score=70)
    rule = create_assignment_rule(
        target_department="ENGINEERING", target_job_role="IC", course_id=course["id"],
        due_in_days=30, effective_from="2026-01-01T00:00:00.000Z",
        effective_to="2026-12-31T00:00:00.000Z",
    )
    sweep = get_success_data(api.apply_assignment_rule(rule["id"], ADMIN))
    assert sweep["created_count"] == 1, f"one matching employee → created_count 1, got {sweep['created_count']}"

    listed, _ = validate_paginated(api.list_enrollments(ADMIN, params={"assignment_rule_id": rule["id"]}))
    assert len(listed) == 1
    assert listed[0]["assignment_rule_id"] == rule["id"]
    assert listed[0]["employee_id"] == emp["id"]


# ===========================================================================
# Corner/endpoints/certificate_reverse_reachability_by_employee
# ===========================================================================
def test_list_certificates_by_employee_returns_holders_cert(api):
    """PRD §3.8: "Certificates can be listed and filtered by employee_id, course_id,
    enrollment_id, or status, and fetched by id."

    Design: Corner/endpoints/certificate_reverse_reachability_by_employee
    """
    set_clock()
    emp = create_employee()
    course = create_published_course(passing_score=70, ceu_credits=2.00)
    learner = make_learner_headers(emp["id"])
    enr = create_enrollment(emp["id"], course["id"])
    started = get_success_data(api.start_enrollment(enr["id"], learner))
    get_success_data(
        api.create_quiz_attempt(enr["id"], {"score": 80, "expected_enrollment_version": started["version"]}, learner)
    )
    data, _ = validate_paginated(api.list_certificates(learner, params={"employee_id": emp["id"]}))
    assert len(data) >= 1, "holder's cert must be discoverable by employee_id"
    cert = data[0]
    assert cert["employee_id"] == emp["id"]
    assert cert["status"] == "ACTIVE"


# ===========================================================================
# Corner/rbac/learner_cannot_create_course_returns_403
# ===========================================================================
def test_learner_cannot_create_course_returns_403(api):
    """PRD §2.1: "When a request is well-authenticated but the acting role is not
    permitted to perform the operation ... the rejection is ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/learner_cannot_create_course_returns_403
    """
    emp = create_employee()
    resp = api.create_course(
        f.create_course_payload(code="NOPE", title="Nope", content_type="SCORM", passing_score=70),
        make_learner_headers(emp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# Corner/rbac/learner_cannot_start_others_enrollment_returns_403
# ===========================================================================
def test_learner_cannot_start_others_enrollment_returns_403(api):
    """PRD §3.4: "the acting learner must own it, meaning X-User-ID equals the
    enrollment's employee_id (else ERR_UNAUTHORIZED)."

    Design: Corner/rbac/learner_cannot_start_others_enrollment_returns_403
    """
    set_clock()
    owner = create_employee(email="own@x.com")
    intruder = create_employee(email="intr@x.com")
    course = create_published_course(passing_score=70)
    enr = create_enrollment(owner["id"], course["id"])
    resp = api.start_enrollment(enr["id"], make_learner_headers(intruder["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# Corner/rbac/missing_user_role_header_returns_401
# ===========================================================================
def test_missing_user_role_header_returns_401(api):
    """PRD §2.1: "If X-User-Role is missing or is not one of these three values, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_user_role_header_returns_401
    """
    resp = api._request("GET", "/courses", headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
# ===========================================================================
def test_quiz_attempt_with_current_version_succeeds_and_advances_version(api):
    """PRD §2.9: "A quiz-attempt submission must carry expected_enrollment_version as a
    required field whose value is the version of the target Enrollment that the client
    last observed. If that value does not equal the enrollment's current version, the
    submission is rejected with ERR_STALE_VERSION."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    emp, course, started = setup_started_enrollment(course_overrides={"passing_score": 70})
    # version after create(1) → start(2); a passing attempt completes → 3
    resp = api.create_quiz_attempt(
        started["id"], {"score": 88, "expected_enrollment_version": started["version"]},
        make_learner_headers(emp["id"]),
    )
    validate_success(resp, 201)
    enr = get_enrollment(started["id"])
    assert enr["status"] == "COMPLETED"
    assert enr["version"] == 3, f"create→start→complete advances version to 3, got {enr['version']}"


# ===========================================================================
# Corner/consistency_model/immediate_consistency_completion_visible_in_same_response_chain
# ===========================================================================
def test_passing_attempt_completion_visible_on_immediate_read(api):
    """PRD §2.10: "When an enrollment completes, fails, is waived, or is reset, the
    system independently mutates each affected resource."
    PRD §3.5: "A passing attempt drives the enrollment from IN_PROGRESS to COMPLETED."

    Design: Corner/consistency_model/immediate_consistency_completion_visible_in_same_response_chain
    """
    emp, course, started = setup_started_enrollment(course_overrides={"passing_score": 70})
    learner = make_learner_headers(emp["id"])
    get_success_data(
        api.create_quiz_attempt(started["id"], {"score": 91, "expected_enrollment_version": started["version"]}, learner)
    )
    enr = get_enrollment(started["id"], learner)
    assert enr["status"] == "COMPLETED", "completion must be immediately visible"
    assert enr["final_grade"] == 91, f"final_grade visible immediately, got {enr['final_grade']}"
