"""Sleep plan authoring: initial states, method-age safety, supersede, resume,
the plan adjustment cycle, case-state gating, and plan-creation OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_plan,
    create_consultant,
    create_plan_for_case,
    create_plan_payload,
    get_case,
    get_consultant,
    make_consultant_headers,
    make_parent_headers,
    open_case,
    purchase_package_for_case,
    register_family,
    review_case_questionnaire,
    review_log_entry,
    set_logical_clock,
    setup_case_in_active_support,
    setup_case_in_planning,
    setup_completed_case,
    submit_log_for_case,
    submit_questionnaire,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["practice_admin_headers"]


def test_initial_states_on_service_journey(api):
    """PRD §3.2: "A successful submission creates the questionnaire in `SUBMITTED`
    status, computes its `provisional_severity_score`, moves the case from `INTAKE`
    to `ASSESSMENT`, and increments the case `version` by one."
    PRD §3.3: "Each plan carries a `plan_sequence`, a per-case ordinal that starts at
    1 for the first plan and takes the highest existing `plan_sequence` of the case
    plus one thereafter. The new plan snapshots the case's current `age_band` onto
    itself and starts life `ACTIVE`."
    PRD §3.4: "The purchase is stamped `purchased_at` from the logical clock, and the
    package begins `ACTIVE`."
    PRD §3.5: "Every new log starts with `review_status` set to `PENDING_REVIEW`, and
    the case's log list can be filtered by `log_date` and `review_status`."

    Design: Corner/state_machines/initial_states_on_service_journey
    """
    bundle = setup_case_in_planning()
    case, family, consultant = bundle["case"], bundle["family"], bundle["consultant"]
    questionnaire = bundle["questionnaire"]
    assert questionnaire["status"] == "SUBMITTED"

    plan = create_plan_for_case(case["id"], consultant)
    assert_plan(plan)
    assert plan["status"] == "ACTIVE"
    assert plan["plan_sequence"] == 1
    assert plan["age_band"] == "NEWBORN"  # snapshot of the case's band at creation

    package = purchase_package_for_case(case["id"], family)
    assert package["status"] == "ACTIVE"

    log = submit_log_for_case(case["id"], family, "2026-08-01")
    assert log["review_status"] == "PENDING_REVIEW"


def test_method_age_safety_matrix(api):
    """PRD §3.3: "Safety comes before everything else: the requested method must be
    appropriate for the case's current age band. A `NEWBORN` permits only
    `GENTLE_NO_CRY`. An `INFANT` additionally permits `FERBER_GRADUATED` and
    `CHAIR_METHOD`. `TODDLER` and `PRESCHOOL` permit all four methods, including
    `EXTINCTION`. A request outside the allowed set is rejected with
    `ERR_METHOD_NOT_AGE_APPROPRIATE`."

    Case A is NEWBORN (birth 2026-05-01 at the default clock); case B is INFANT
    (birth 2026-04-01, exactly four months).

    Design: Corner/validations/method_age_safety_matrix
    """
    bundle_a = setup_case_in_planning(child_birth_date="2026-05-01")
    consultant, family = bundle_a["consultant"], bundle_a["family"]
    case_a = bundle_a["case"]
    # Reuse the same consultant for a second, INFANT case in PLANNING.
    case_b = open_case(family, consultant, child_birth_date="2026-04-01")
    q_b = submit_questionnaire(case_b, family)
    review_case_questionnaire(q_b["id"], consultant)

    headers = make_consultant_headers(consultant["id"])
    version_a = get_case(case_a["id"])["version"]

    res = api.create_plan(
        case_a["id"],
        create_plan_payload(
            version_a, method="EXTINCTION", target_night_wake_count=1,
            target_longest_stretch_minutes=300,
        ),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_METHOD_NOT_AGE_APPROPRIATE.value, expected_status=422)

    res = api.create_plan(
        case_a["id"],
        create_plan_payload(
            version_a, method="FERBER_GRADUATED", target_night_wake_count=1,
            target_longest_stretch_minutes=300,
        ),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_METHOD_NOT_AGE_APPROPRIATE.value, expected_status=422)

    # The rejected attempts did not mutate the case, so version_a is still current.
    res = api.create_plan(case_a["id"], create_plan_payload(version_a), headers)
    plan_a = validate_success(res, 201)
    assert_plan(plan_a)
    assert plan_a["status"] == "ACTIVE"

    version_b = get_case(case_b["id"])["version"]
    res = api.create_plan(
        case_b["id"],
        create_plan_payload(
            version_b, method="FERBER_GRADUATED", target_night_wake_count=1,
            target_longest_stretch_minutes=300,
        ),
        headers,
    )
    plan_b = validate_success(res, 201)
    assert plan_b["status"] == "ACTIVE"


def test_plan_supersede_on_new_plan(api):
    """PRD §3.3: "Each plan carries a `plan_sequence`, a per-case ordinal that starts
    at 1 for the first plan and takes the highest existing `plan_sequence` of the
    case plus one thereafter. The new plan snapshots the case's current `age_band`
    onto itself and starts life `ACTIVE`. Any plan of the same case currently in
    `ACTIVE` or `NEEDS_ADJUSTMENT` is superseded by the creation, moving to
    `SUPERSEDED` and ceasing to be current."
    PRD §3.3: "In all three paths the case `version` increments by one."

    Design: Corner/state_machines/plan_supersede_on_new_plan
    """
    bundle = setup_case_in_planning(child_birth_date="2026-03-15")  # INFANT: FERBER allowed
    case, consultant = bundle["case"], bundle["consultant"]
    headers = make_consultant_headers(consultant["id"])

    v1 = get_case(case["id"])["version"]
    plan1 = validate_success(
        api.create_plan(case["id"], create_plan_payload(v1), headers), 201
    )
    v2 = get_case(case["id"])["version"]
    res = api.create_plan(
        case["id"],
        create_plan_payload(
            v2, method="FERBER_GRADUATED", target_night_wake_count=1,
            target_longest_stretch_minutes=300,
        ),
        headers,
    )
    plan2 = validate_success(res, 201)
    assert plan2["status"] == "ACTIVE"
    assert plan2["plan_sequence"] == 2

    plans, _ = validate_paginated(api.list_plans(case["id"], headers))
    by_id = {p["id"]: p for p in plans}
    assert by_id[plan1["id"]]["status"] == "SUPERSEDED"
    active_plans = [p for p in plans if p["status"] == "ACTIVE"]
    assert len(active_plans) == 1 and active_plans[0]["id"] == plan2["id"]

    case_after = get_case(case["id"])
    assert case_after["version"] == v2 + 1, (
        f"the superseding write must increment the case version by one: {v2} -> "
        f"{case_after['version']}"
    )


def test_resume_active_plan_rejected(api):
    """PRD §3.3: "A plan sitting in `NEEDS_ADJUSTMENT` can be resumed in place by the
    assigned consultant — resuming any other plan status is rejected with
    `ERR_PLAN_INVALID_STATE`."

    Design: Corner/state_machines/resume_active_plan_rejected
    """
    bundle = setup_case_in_active_support()
    plan = bundle["plan"]
    res = api.resume_plan(plan["id"], make_consultant_headers(bundle["consultant"]["id"]))
    validate_error(res, ApiErrorId.ERR_PLAN_INVALID_STATE.value, expected_status=409)
    plans, _ = validate_paginated(
        api.list_plans(bundle["case"]["id"], make_consultant_headers(bundle["consultant"]["id"]))
    )
    assert plans[0]["status"] == "ACTIVE", "a rejected resume changes nothing"


def test_plan_cycle_regression_then_resume_restores_active(api):
    """PRD §3.5: "A `REGRESSION` outcome moves it to `REVIEWED_REGRESSION` and fires
    the three-link regression cascade, with each link conditional on current state —
    a link already sitting in its target state is a no-op. Link one: the case's
    current plan, if `ACTIVE`, becomes `NEEDS_ADJUSTMENT`. Link two: the case, if
    `ACTIVE_SUPPORT`, becomes `NEEDS_ATTENTION`, incrementing the case `version`."
    PRD §3.3: "The plan returns to `ACTIVE`, and when that plan is the case's latest
    non-`SUPERSEDED` plan, the case moves from `NEEDS_ATTENTION` back to
    `ACTIVE_SUPPORT` with the consultant's count recomputed upward by one."

    Design: Difficulty/non_linear_state_machine/sleep_plan_adjustment_cycle
    """
    bundle = setup_case_in_active_support()
    case, family, consultant, plan = (
        bundle["case"], bundle["family"], bundle["consultant"], bundle["plan"],
    )
    cons_headers = make_consultant_headers(consultant["id"])

    log1 = submit_log_for_case(case["id"], family, "2026-08-01", night_wake_count=6)
    review_log_entry(log1["id"], consultant, outcome="REGRESSION")

    plans, _ = validate_paginated(api.list_plans(case["id"], cons_headers))
    assert plans[0]["status"] == "NEEDS_ADJUSTMENT"
    assert get_case(case["id"])["status"] == "NEEDS_ATTENTION"

    # Resume the very same plan in place: the cycle closes without superseding.
    resumed = validate_success(api.resume_plan(plan["id"], cons_headers), 200)
    assert resumed["id"] == plan["id"]
    assert resumed["status"] == "ACTIVE"
    assert resumed["plan_sequence"] == 1
    assert get_case(case["id"])["status"] == "ACTIVE_SUPPORT"
    assert get_consultant(consultant["id"])["active_case_count"] == 1


def test_plan_cycle_second_regression_flags_same_plan_again(api):
    """PRD §3.5: "A `REGRESSION` outcome moves it to `REVIEWED_REGRESSION` and fires
    the three-link regression cascade, with each link conditional on current state —
    a link already sitting in its target state is a no-op. Link one: the case's
    current plan, if `ACTIVE`, becomes `NEEDS_ADJUSTMENT`. Link two: the case, if
    `ACTIVE_SUPPORT`, becomes `NEEDS_ATTENTION`, incrementing the case `version`."

    After a resume, a second REGRESSION review drives the SAME plan (id and
    plan_sequence unchanged) back to NEEDS_ADJUSTMENT — the loop never supersedes.

    Design: Difficulty/non_linear_state_machine/sleep_plan_adjustment_cycle
    """
    bundle = setup_case_in_active_support()
    case, family, consultant, plan = (
        bundle["case"], bundle["family"], bundle["consultant"], bundle["plan"],
    )
    cons_headers = make_consultant_headers(consultant["id"])

    log1 = submit_log_for_case(case["id"], family, "2026-08-01", night_wake_count=6)
    review_log_entry(log1["id"], consultant, outcome="REGRESSION")
    validate_success(api.resume_plan(plan["id"], cons_headers), 200)

    set_logical_clock("2026-08-02T00:00:00Z")
    log2 = submit_log_for_case(case["id"], family, "2026-08-02", night_wake_count=7)
    review_log_entry(log2["id"], consultant, outcome="REGRESSION")

    plans, _ = validate_paginated(api.list_plans(case["id"], cons_headers))
    same_plan = [p for p in plans if p["id"] == plan["id"]][0]
    assert same_plan["status"] == "NEEDS_ADJUSTMENT"
    assert same_plan["plan_sequence"] == 1
    assert all(p["status"] != "SUPERSEDED" for p in plans), "the cycle never supersedes"
    assert get_case(case["id"])["status"] == "NEEDS_ATTENTION"


def test_plan_create_rejected_from_intake_accepted_from_planning(api):
    """PRD §3.3: "Plan creation is permitted whenever the case is in `PLANNING`,
    `ACTIVE_SUPPORT`, or `NEEDS_ATTENTION` — any other case status is rejected with
    `ERR_CASE_INVALID_STATE` — and it is concurrency-guarded by
    `expected_case_version` as described in §2.7."

    The identical payload is rejected while the case is INTAKE and accepted once the
    case reaches PLANNING.

    Design: Difficulty/cross_entity_state_dependency/plan_create_gated_by_case_state
    """
    consultant = create_consultant(certification_no="CERT-112")
    family = register_family(full_name="Fam K", email="k@x.com")
    case = open_case(family, consultant)
    headers = make_consultant_headers(consultant["id"])

    version_intake = get_case(case["id"])["version"]
    res = api.create_plan(case["id"], create_plan_payload(version_intake), headers)
    validate_error(res, ApiErrorId.ERR_CASE_INVALID_STATE.value, expected_status=409)

    questionnaire = submit_questionnaire(case, family)
    review_case_questionnaire(questionnaire["id"], consultant)
    version_planning = get_case(case["id"])["version"]
    res = api.create_plan(case["id"], create_plan_payload(version_planning), headers)
    plan = validate_success(res, 201)
    assert plan["status"] == "ACTIVE"
    assert get_case(case["id"])["status"] == "ACTIVE_SUPPORT"


def test_plan_create_rejected_from_completed(api):
    """PRD §3.3: "Plan creation is permitted whenever the case is in `PLANNING`,
    `ACTIVE_SUPPORT`, or `NEEDS_ATTENTION` — any other case status is rejected with
    `ERR_CASE_INVALID_STATE` — and it is concurrency-guarded by
    `expected_case_version` as described in §2.7."

    A COMPLETED case is outside the creatable set, so the same payload fails.

    Design: Difficulty/cross_entity_state_dependency/plan_create_gated_by_case_state
    """
    bundle = setup_completed_case()
    case, consultant = bundle["case"], bundle["consultant"]
    assert case["status"] == "COMPLETED"
    version_completed = get_case(case["id"])["version"]
    res = api.create_plan(
        case["id"],
        create_plan_payload(version_completed),
        make_consultant_headers(consultant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CASE_INVALID_STATE.value, expected_status=409)


def test_occ_plan_create_stale_version_rejected(api):
    """PRD §2.7: "Creating a sleep plan for a case requires the request to carry
    `expected_case_version`, holding the `version` of the case as the client last
    observed it; if the case's current `version` has advanced beyond that value, the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412), because a writer holding
    an outdated case version would unknowingly supersede a plan it never saw."

    Design: Corner/cross_cutting_layers/occ_plan_create_stale_version_rejected
    """
    bundle = setup_case_in_planning()
    case, consultant = bundle["case"], bundle["consultant"]
    headers = make_consultant_headers(consultant["id"])

    v1 = get_case(case["id"])["version"]
    plan1 = validate_success(
        api.create_plan(case["id"], create_plan_payload(v1), headers), 201
    )
    # The first write advanced the case version; v1 is now stale.
    res = api.create_plan(
        case["id"],
        create_plan_payload(v1, target_night_wake_count=3, target_longest_stretch_minutes=200),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    v2 = get_case(case["id"])["version"]
    assert v2 == v1 + 1, f"one successful plan write increments by exactly 1: {v1} -> {v2}"
    plan2 = validate_success(
        api.create_plan(
            case["id"],
            create_plan_payload(v2, target_night_wake_count=3, target_longest_stretch_minutes=200),
            headers,
        ),
        201,
    )
    assert plan2["status"] == "ACTIVE"
    plans, _ = validate_paginated(api.list_plans(case["id"], headers))
    by_id = {p["id"]: p for p in plans}
    assert by_id[plan1["id"]]["status"] == "SUPERSEDED"
