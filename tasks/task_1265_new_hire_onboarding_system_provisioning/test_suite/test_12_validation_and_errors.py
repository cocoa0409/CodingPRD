"""Validation pipeline, not-found error family, and priority ordering."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    setup_basic_case,
    create_published_profile,
    create_manager_and_buddy,
    create_new_hire,
    create_employee,
    create_employee_payload,
    create_role_profile_payload,
    create_onboarding_case_payload,
    get_case_tasks,
    make_buddy_headers,
    make_new_hire_headers,
    make_hiring_manager_headers,
)

HR = TEST_USERS["hr_admin_headers"]
IT = TEST_USERS["it_provisioner_headers"]
PAYROLL = TEST_USERS["payroll_ops_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role string
    outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`."

    Design: Corner/errors/missing_auth_header_returns_400
    """
    resp = api._request("GET", "/api/onboarding-cases", headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT, expected_status=400)


def test_forbidden_role_returns_403(api):
    """PRD §2.1: "A request whose role is valid but not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

    Buddy calling the HRAdmin-only review endpoint.

    Design: Corner/errors/forbidden_role_returns_403
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    t1 = get_case_tasks(case_id)[0]
    buddy = make_buddy_headers(ctx["buddy"]["id"])
    resp = api.review_task(t1["id"], {"decision": "APPROVE"}, buddy)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_nonexistent_ids_return_domain_not_found(api):
    """PRD §2.7: "Each entity type has a dedicated error:
    `ERR_ROLE_PROFILE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_NEW_HIRE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`,
    `ERR_CLEARANCE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`, `ERR_TRAINING_NOT_FOUND`,
    `ERR_CYCLE_NOT_FOUND`, `ERR_HANDOFF_NOT_FOUND`, and `ERR_SURVEY_NOT_FOUND`."

    Design: Corner/errors/nonexistent_ids_return_domain_not_found
    """
    N = NON_EXISTENT_UUID
    nh_any = make_new_hire_headers(N)
    mgr_any = make_hiring_manager_headers(N)

    checks = [
        (api.get_role_profile(N, HR), ApiErrorId.ERR_ROLE_PROFILE_NOT_FOUND),
        (api.get_employee(N, HR), ApiErrorId.ERR_EMPLOYEE_NOT_FOUND),
        (api.get_new_hire(N, HR), ApiErrorId.ERR_NEW_HIRE_NOT_FOUND),
        (api.get_onboarding_case(N, HR), ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.submit_task(N, {"document_ref": "d"}, nh_any), ApiErrorId.ERR_TASK_NOT_FOUND),
        (api.record_clearance_result(N, {"component": "BACKGROUND", "result": "PASSED"}, HR),
         ApiErrorId.ERR_CLEARANCE_NOT_FOUND),
        (api.get_provisioning_order(N, HR), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.transition_provisioning_item(N, {"to": "DONE"}, IT), ApiErrorId.ERR_ITEM_NOT_FOUND),
        (api.cancel_orientation_session(N, HR), ApiErrorId.ERR_SESSION_NOT_FOUND),
        (api.complete_check_in(N, {}, make_buddy_headers(N)), ApiErrorId.ERR_CHECKIN_NOT_FOUND),
        (api.complete_training(N, {}, nh_any), ApiErrorId.ERR_TRAINING_NOT_FOUND),
        (api.evaluate_probation_cycle(N, {"outcome": "PASS", "rating": 5}, mgr_any),
         ApiErrorId.ERR_CYCLE_NOT_FOUND),
        (api.get_payroll_handoff(N, HR), ApiErrorId.ERR_HANDOFF_NOT_FOUND),
        (api.submit_survey(N, {
            "onboarding_experience_rating": 3,
            "manager_support_rating": 3,
            "resources_rating": 3,
        }, nh_any), ApiErrorId.ERR_SURVEY_NOT_FOUND),
    ]
    for resp, expected in checks:
        validate_error(resp, expected)


def test_request_shape_error_beats_state_error(api):
    """PRD §2.6: "3. **Request shape.** Required fields must be present, enum
    values valid, dates parseable ... Shape failures draw `ERR_VALIDATION`."
    PRD §2.6: "6. **State gates.** The target entity must be in a state that
    permits the operation"

    Design: Corner/validations/request_shape_error_beats_state_error
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    t1 = get_case_tasks(case_id)[0]
    # Invalid enum 'MAYBE' on a PENDING task: shape (priority 3) beats state (6).
    resp = api.review_task(t1["id"], {"decision": "MAYBE"}, HR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_case_referential_beats_temporal(api):
    """PRD §2.6: "8. **Referential usability.** Referenced configuration and
    people must be usable: ... the named manager and buddy must be `ACTIVE`
    employees ... 10. **Temporal sanity.** Date and time rules that compare
    against the logical clock come last"
    PRD §2.6: "when several problems are present at once, the stage that runs
    first determines which error the caller sees."

    Design: Difficulty/priority_pair_validation_conflict/create_case_referential_beats_temporal
    """
    profile = create_published_profile()
    mgr = create_employee()
    bud = get_success_data(api.create_employee(
        create_employee_payload(manager_id=mgr["id"]), HR))
    get_success_data(api.deactivate_employee(mgr["id"], HR))
    nh = create_new_hire()

    # Both rules fail: manager INACTIVE (priority 8) AND start_date in past (priority 10).
    resp = api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh["id"],
        role_profile_id=profile["id"],
        manager_id=mgr["id"],
        buddy_id=bud["id"],
        start_date="2026-04-01",
    ), HR)
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)


def test_create_case_temporal_fires_alone_when_referential_ok(api):
    """PRD §3.2: "finally the `start_date` must not precede the current logical
    date (`ERR_START_DATE_IN_PAST`)."

    With all referential checks satisfied, the past-start-date rule surfaces.

    Design: Difficulty/priority_pair_validation_conflict/create_case_referential_beats_temporal
    """
    profile = create_published_profile()
    mgr, bud = create_manager_and_buddy()
    nh = create_new_hire()
    resp = api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh["id"],
        role_profile_id=profile["id"],
        manager_id=mgr["id"],
        buddy_id=bud["id"],
        start_date="2026-04-01",
    ), HR)
    validate_error(resp, ApiErrorId.ERR_START_DATE_IN_PAST)


def test_start_date_in_past_rejected(api):
    """PRD §3.2: "finally the `start_date` must not precede the current logical
    date (`ERR_START_DATE_IN_PAST`)."

    Design: Corner/validations/start_date_in_past_rejected
    """
    profile = create_published_profile()
    mgr, bud = create_manager_and_buddy()
    nh = create_new_hire()
    resp = api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh["id"],
        role_profile_id=profile["id"],
        manager_id=mgr["id"],
        buddy_id=bud["id"],
        start_date="2026-04-01",
    ), HR)
    validate_error(resp, ApiErrorId.ERR_START_DATE_IN_PAST)


def test_draft_profile_rejected_at_case_creation(api):
    """PRD §3.2: "the referenced profile must be `PUBLISHED`
    (`ERR_ROLE_PROFILE_NOT_PUBLISHED`)"

    Design: Corner/validations/draft_profile_rejected_at_case_creation
    """
    # Create a profile but never publish it.
    profile = get_success_data(api.create_role_profile(create_role_profile_payload(), HR))
    mgr, bud = create_manager_and_buddy()
    nh = create_new_hire()
    resp = api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh["id"],
        role_profile_id=profile["id"],
        manager_id=mgr["id"],
        buddy_id=bud["id"],
    ), HR)
    validate_error(resp, ApiErrorId.ERR_ROLE_PROFILE_NOT_PUBLISHED)


def test_duplicate_active_case_for_same_newhire_rejected(api):
    """PRD §3.2: "the new hire must not already have another non-terminal case
    (`ERR_DUPLICATE_ACTIVE_CASE`)"

    Design: Corner/validations/duplicate_active_case_for_same_newhire_rejected
    """
    ctx = setup_basic_case()
    profile = ctx["profile"]
    mgr = ctx["manager"]
    bud = ctx["buddy"]
    nh = ctx["new_hire"]
    resp = api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh["id"],
        role_profile_id=profile["id"],
        manager_id=mgr["id"],
        buddy_id=bud["id"],
    ), HR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CASE)


def test_dual_role_manager_buddy_rejected(api):
    """PRD §3.2: "then the manager and buddy must be different people
    (`ERR_DUAL_ROLE_ASSIGNMENT`)"

    Design: Corner/validations/dual_role_manager_buddy_rejected
    """
    profile = create_published_profile()
    mgr = create_employee()
    nh = create_new_hire()
    resp = api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh["id"],
        role_profile_id=profile["id"],
        manager_id=mgr["id"],
        buddy_id=mgr["id"],  # same person as manager
    ), HR)
    validate_error(resp, ApiErrorId.ERR_DUAL_ROLE_ASSIGNMENT)


def test_newhire_cannot_submit_other_case_task(api):
    """PRD §3.3: "the caller's `X-User-ID` must equal the owning case's
    `new_hire_id` (`ERR_NOT_RESOURCE_OWNER`)"

    Design: Corner/validations/newhire_cannot_submit_other_case_task
    """
    profile = create_published_profile()
    mgr, bud = create_manager_and_buddy()
    nh_a = create_new_hire()
    case_a_resp = api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh_a["id"], role_profile_id=profile["id"],
        manager_id=mgr["id"], buddy_id=bud["id"]), HR)
    case_a = get_success_data(case_a_resp)
    nh_b = create_new_hire()
    get_success_data(api.create_onboarding_case(create_onboarding_case_payload(
        new_hire_id=nh_b["id"], role_profile_id=profile["id"],
        manager_id=mgr["id"], buddy_id=bud["id"]), HR))

    task_a = get_case_tasks(case_a["id"])[0]
    # New hire B submits a task of case A -> ERR_NOT_RESOURCE_OWNER.
    resp = api.submit_task(task_a["id"], {"document_ref": "doc://evil"},
                           make_new_hire_headers(nh_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
