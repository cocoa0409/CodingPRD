"""Probation cycle evaluation, extension budget, and terminal cascades."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    setup_in_progress,
    setup_probation,
    setup_probation_with_handoff,
    get_case_cycles,
    get_case_trainings,
    get_case_checkins,
    get_case_handoffs,
    get_summary,
    make_new_hire_headers,
    make_hiring_manager_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_probation_extend_regenerates_cycle_until_budget(api):
    """PRD §3.8: "An `EXTEND` outcome is budget-checked against the pinned
    profile: the current `cycle_index` must not exceed `max_probation_extensions`
    — so a first cycle may extend when the budget is at least 1, a second when
    it is at least 2, and so on — otherwise the evaluation is rejected with
    `ERR_MAX_EXTENSIONS_REACHED`. A permitted extension moves the cycle to
    `EVALUATED_EXTEND`, creates the successor cycle with `cycle_index`
    incremented by 1 in `ACTIVE` status and an `evaluation_due_at` of 17:00:00
    UTC on the day `extension_days` after the previous cycle's deadline"

    Design: Corner/state_machines/probation_extend_regenerates_cycle_until_budget
    """
    ctx = setup_probation(clock_after="2026-08-03T00:00:00Z")
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    cy1 = ctx["cycles"][0]
    assert cy1["status"] == "EVALUATION_DUE"

    # Cycle 1 EXTEND: allowed (cycle_index 1 <= max 1).
    r = api.evaluate_probation_cycle(cy1["id"], {"outcome": "EXTEND", "rating": 3}, mgr)
    assert validate_success(r)["status"] == "EVALUATED_EXTEND"

    cycles = get_case_cycles(case_id)
    assert len(cycles) == 2
    cy2 = cycles[1]
    assert cy2["status"] == "ACTIVE"
    assert cy2["cycle_index"] == 2
    # Previous due 2026-08-02T17:00:00Z + 30 extension days -> 2026-09-01T17:00:00Z.
    assert cy2["evaluation_due_at"] == "2026-09-01T17:00:00Z"

    # Advance clock so cycle 2 is EVALUATION_DUE; attempt EXTEND again.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-09-02T00:00:00Z"}, HR))
    resp = api.evaluate_probation_cycle(cy2["id"], {"outcome": "EXTEND", "rating": 3}, mgr)
    validate_error(resp, ApiErrorId.ERR_MAX_EXTENSIONS_REACHED)


def test_probation_fail_separates_case_and_withdraws_handoff(api):
    """PRD §3.8: "A `FAIL` outcome moves the cycle to `EVALUATED_FAIL` and
    separates the case."
    PRD §3.8: "Separation is the second full teardown: the case moves from
    `PROBATION` to `SEPARATED`; its training assignments in `ASSIGNED` or
    `OVERDUE`, check-ins in `SCHEDULED` or `MISSED`, and remaining probation
    cycles in `ACTIVE` or `EVALUATION_DUE` are all cancelled; a survey still
    `SENT` is cancelled; payroll handoffs in `DRAFT` or `TRANSMITTED` are
    withdrawn; the new hire's status becomes `SEPARATED`"

    Design: Corner/state_machines/probation_fail_separates_case_and_withdraws_handoff
    """
    ctx = setup_probation_with_handoff(clock_after="2026-08-03T00:00:00Z")
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    cy1 = ctx["cycles"][0]

    r = api.evaluate_probation_cycle(cy1["id"], {"outcome": "FAIL", "rating": 1}, mgr)
    assert validate_success(r)["status"] == "EVALUATED_FAIL"

    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "SEPARATED"

    nh = get_success_data(api.get_new_hire(ctx["new_hire"]["id"], HR))
    assert nh["status"] == "SEPARATED"

    handoff = get_success_data(api.get_payroll_handoff(ctx["handoff"]["id"], HR))
    assert handoff["status"] == "WITHDRAWN"


def test_evaluate_active_cycle_rejected(api):
    """PRD §3.8: "the cycle must be `EVALUATION_DUE` (`ERR_CYCLE_NOT_EVALUABLE`)"

    Design: Corner/state_machines/evaluate_active_cycle_rejected
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    cy1 = get_case_cycles(case_id)[0]
    assert cy1["status"] == "ACTIVE"

    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    resp = api.evaluate_probation_cycle(cy1["id"], {"outcome": "PASS", "rating": 5}, mgr)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_EVALUABLE)


def test_probation_evaluate_requires_case_in_probation(api):
    """PRD §3.8: "the owning case must be in phase `PROBATION`
    (`ERR_INVALID_CASE_PHASE`)"

    Cycle reaches EVALUATION_DUE while the case is still IN_PROGRESS; evaluation
    rejected. After remediation pushes the case to PROBATION, evaluation succeeds.

    Design: Difficulty/cross_entity_state_dependency/probation_evaluate_requires_case_in_probation
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    nh = make_new_hire_headers(ctx["new_hire"]["id"])

    cy1 = get_case_cycles(case_id)[0]
    # Advance well past the cycle's evaluation_due_at (2026-08-02T17:00:00Z).
    get_success_data(api.set_current_utc({"to_iso8601": "2026-08-03T00:00:00Z"}, HR))

    # Cycle is EVALUATION_DUE but case is still IN_PROGRESS (trainings not completed).
    resp = api.evaluate_probation_cycle(cy1["id"], {"outcome": "PASS", "rating": 4}, mgr)
    validate_error(resp, ApiErrorId.ERR_INVALID_CASE_PHASE)

    # Remediate: complete one MANAGER check-in + both trainings.
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER")
    # c_m1 was scheduled for 2026-05-05T09:00:00Z — long past 24h grace; reschedule first.
    get_success_data(api.reschedule_check_in(c_m1["id"], {"scheduled_at": "2026-08-04T09:00:00Z"}, HR))
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    trainings = get_case_trainings(case_id)
    for tr in trainings:
        get_success_data(api.complete_training(tr["id"], {"score": 90}, nh))

    # Case is now PROBATION; evaluation succeeds and case completes.
    resp2 = api.evaluate_probation_cycle(cy1["id"], {"outcome": "PASS", "rating": 4}, mgr)
    assert validate_success(resp2)["status"] == "EVALUATED_PASS"
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "COMPLETED"


def test_probation_gate_fires_after_remediation(api):
    """PRD §3.7: "the case advances from `IN_PROGRESS` to `PROBATION` once every
    training assignment is `COMPLETED` and at least one `MANAGER` check-in is
    `COMPLETED`"

    Design: Difficulty/cross_entity_state_dependency/probation_evaluate_requires_case_in_probation
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    nh = make_new_hire_headers(ctx["new_hire"]["id"])

    get_success_data(api.set_current_utc({"to_iso8601": "2026-08-03T00:00:00Z"}, HR))
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER")
    get_success_data(api.reschedule_check_in(c_m1["id"], {"scheduled_at": "2026-08-04T09:00:00Z"}, HR))
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    for tr in get_case_trainings(case_id):
        get_success_data(api.complete_training(tr["id"], {"score": 90}, nh))
    summary = get_summary(case_id)
    assert summary["phase"] == "PROBATION"
