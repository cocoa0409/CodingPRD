"""Compliance gates: validation priority pairs, finalized-run freeze,
single-active-CAP rule, payment gating, benchmark uniqueness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_application,
    create_cap,
    create_executing_cap,
    create_pricing_exception,
    create_substantiated_finding,
    create_submitted_cap,
    make_loan_officer_headers,
    make_specialist_headers,
    setup_executing_cap,
    setup_market_branch_officer,
    setup_run_with_substantiated_finding,
    validate_applications,
    validate_error,
    validate_success,
)

def test_state_check_beats_suspended_officer_gate(api, director_headers):
    """PRD §2.8: "Only then are resource existence checks performed left
    to right (`ERR_NOT_FOUND`), followed by lifecycle-state permission
    (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` when the target is
    already in a terminal state). Next come compliance gates such as the
    privilege gate, the suspended-officer block, conditional director
    authority, and the finalized-run freeze; then interval conflicts
    (`ERR_SCOPE_OVERLAP`, `ERR_SELF_TEST_WINDOW_OVERLAP`, `ERR_PERIOD_GAP`,
    `ERR_PERIOD_OVERLAP`); then structural business rules (quarter
    alignment, non-empty scope, the all-validated lock requirement, the
    one-active-CAP rule, the differing-decision-pair rule, and the like);
    then cross-entity coherence (matched-pair comparability, control-pool
    emptiness, payee membership, dataset staleness); and finally fiscal
    checks (a manual payment exceeding the plan's remaining funds)."
    PRD §3.6: "Creation requires the application to be `VALIDATED` and
    the owning officer `ACTIVE` — a suspended officer's attempt is rejected
    with `ERR_OFFICER_SUSPENDED`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_exception_create
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    validate_success(
        api.exclude_application(app["id"], TEST_USERS["data_ops_headers"])
    )
    validate_success(api.suspend_loan_officer(officer["id"], director_headers))
    resp = api.create_pricing_exception(
        {"application_id": app["id"], "kind": "RATE_ABOVE_CAP",
         "requested_rate_bps": 770, "justification": "strategic"},
        make_loan_officer_headers(officer["id"]),
    )
    # The request fails both the state check (application EXCLUDED) and the
    # safety gate (officer SUSPENDED); lifecycle-state permission is
    # evaluated before compliance gates.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_suspended_officer_gate_fires_when_state_check_passes(api,
                                                              director_headers):
    """PRD §3.6: "Creation requires the application to be `VALIDATED` and
    the owning officer `ACTIVE` — a suspended officer's attempt is rejected
    with `ERR_OFFICER_SUSPENDED`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_exception_create
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    validate_success(api.suspend_loan_officer(officer["id"], director_headers))
    resp = api.create_pricing_exception(
        {"application_id": app["id"], "kind": "RATE_ABOVE_CAP",
         "requested_rate_bps": 770, "justification": "strategic"},
        make_loan_officer_headers(officer["id"]),
    )
    # Only the safety gate can fail here (application is VALIDATED).
    validate_error(resp, ApiErrorId.ERR_OFFICER_SUSPENDED, expected_status=409)


def _setup_executing_cap_zero_remaining(api):
    """CAP EXECUTING with remaining_cents == 0 (pool 10000 fully allocated
    over three harmed applications), plus an outsider VALIDATED application
    that is NOT in the harmed set."""
    ctx = setup_run_with_substantiated_finding(harmed_keys=("p1", "p2", "p3"))
    outsider = create_application(
        ctx["market"]["id"], ctx["branch"]["id"], ctx["officer"]["id"],
        applicant_group="PROTECTED_1", outcome="ORIGINATED", credit_score=718,
        application_date="2026-02-04", decision_date="2026-02-13",
    )
    validate_applications([outsider["id"]])
    cap = create_executing_cap(ctx["finding"], pool_cents=10_000,
                               approver_user_id="officer-1")
    ctx["cap"] = cap
    ctx["outsider"] = outsider
    return ctx


def test_referential_check_beats_fiscal_check_on_manual_payment(
    api, specialist_headers
):
    """PRD §2.8: "Next come compliance gates such as the privilege gate,
    the suspended-officer block, conditional director authority, and the
    finalized-run freeze; then interval conflicts (`ERR_SCOPE_OVERLAP`,
    `ERR_SELF_TEST_WINDOW_OVERLAP`, `ERR_PERIOD_GAP`, `ERR_PERIOD_OVERLAP`);
    then structural business rules (quarter alignment, non-empty scope,
    the all-validated lock requirement, the one-active-CAP rule, the
    differing-decision-pair rule, and the like); then cross-entity
    coherence (matched-pair comparability, control-pool emptiness, payee
    membership, dataset staleness); and finally fiscal checks (a manual
    payment exceeding the plan's remaining funds)."
    PRD §3.9: "the payee must belong to the finding's
    `harmed_application_ids`, else `ERR_PAYEE_NOT_IN_CAP_SCOPE` (HTTP 422);
    and the amount must not exceed the plan's `remaining_cents`, else
    `ERR_CAP_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_manual_payment
    """
    ctx = _setup_executing_cap_zero_remaining(api)
    assert ctx["cap"]["remaining_cents"] == 0
    resp = api.create_remediation_payment(
        {"corrective_action_plan_id": ctx["cap"]["id"],
         "application_id": ctx["outsider"]["id"], "amount_cents": 1},
        make_specialist_headers("specialist-1"),
    )
    # The request fails both the payee-membership check and the fiscal
    # check; cross-entity coherence is evaluated before fiscal checks.
    validate_error(resp, ApiErrorId.ERR_PAYEE_NOT_IN_CAP_SCOPE,
                   expected_status=422)


def test_fiscal_check_fires_when_payee_is_in_scope(api, specialist_headers):
    """PRD §3.9: "the amount must not exceed the plan's `remaining_cents`,
    else `ERR_CAP_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_manual_payment
    """
    ctx = _setup_executing_cap_zero_remaining(api)
    assert ctx["cap"]["remaining_cents"] == 0
    resp = api.create_remediation_payment(
        {"corrective_action_plan_id": ctx["cap"]["id"],
         "application_id": ctx["apps"]["p1"]["id"], "amount_cents": 1},
        make_specialist_headers("specialist-1"),
    )
    # Payee is in the harmed set; only the fiscal check can fail.
    validate_error(resp, ApiErrorId.ERR_CAP_BUDGET_EXCEEDED, expected_status=422)


def test_correction_blocked_after_run_finalized(api, data_ops_headers,
                                                analyst_headers,
                                                officer_headers):
    """PRD §2.10: "Once an analysis run reaches `FINALIZED` or `ARCHIVED`,
    every application frozen in its snapshot is immutable: correction,
    exclusion, and rescission of an approved exception on such an
    application are all rejected with `ERR_APPLICATION_LOCKED` (HTTP 409)."

    Design: Corner/validations/correction_blocked_after_run_finalized
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    exception = create_pricing_exception(app["id"], officer["id"])
    validate_success(
        api.approve_pricing_exception(exception["id"], officer_headers)
    )
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    validate_success(api.finalize_analysis_run(run["id"], officer_headers))
    current = validate_success(api.get_application(app["id"], data_ops_headers))
    resp1 = api.correct_application(
        app["id"],
        {"note_rate_bps": 705,
         "expected_application_version": current["version"]},
        data_ops_headers,
    )
    validate_error(resp1, ApiErrorId.ERR_APPLICATION_LOCKED, expected_status=409)
    resp2 = api.exclude_application(app["id"], data_ops_headers)
    validate_error(resp2, ApiErrorId.ERR_APPLICATION_LOCKED, expected_status=409)
    resp3 = api.rescind_pricing_exception(exception["id"], officer_headers)
    validate_error(resp3, ApiErrorId.ERR_APPLICATION_LOCKED, expected_status=409)


def test_cap_active_blocks_second_cap(api, analyst_headers):
    """PRD §3.8: "At most one plan per finding may sit in `SUBMITTED`,
    `EXECUTING`, or `OVERDUE` at a time; drafting while one occupies those
    states is rejected with `ERR_CAP_ACTIVE` (HTTP 409)."

    Design: Corner/validations/cap_active_blocks_second_cap
    """
    ctx = setup_run_with_substantiated_finding(harmed_keys=("p1",))
    create_submitted_cap(ctx["finding"], pool_cents=5_000, title="cap one")
    current = validate_success(
        api.get_finding(ctx["finding"]["id"], analyst_headers)
    )
    resp = api.create_corrective_action_plan(
        {"finding_id": ctx["finding"]["id"], "title": "cap two",
         "pool_cents": 7_000, "due_date": "2026-07-31",
         "expected_finding_version": current["version"]},
        analyst_headers,
    )
    # OCC passes (current version) but the SUBMITTED plan blocks a second.
    validate_error(resp, ApiErrorId.ERR_CAP_ACTIVE, expected_status=409)


def test_payment_create_blocked_before_cap_executing(api, specialist_headers):
    """PRD §3.9: "The plan must be `EXECUTING` or `OVERDUE`, else
    `ERR_CAP_NOT_EXECUTING` (HTTP 409)".

    Design: Corner/validations/payment_create_blocked_before_cap_executing
    """
    ctx = setup_run_with_substantiated_finding(harmed_keys=("p1",))
    cap = create_cap(ctx["finding"], pool_cents=5_000)
    resp = api.create_remediation_payment(
        {"corrective_action_plan_id": cap["id"],
         "application_id": ctx["apps"]["p1"]["id"], "amount_cents": 100},
        make_specialist_headers("specialist-1"),
    )
    # The CAP is DRAFT; payee and amount are otherwise valid.
    validate_error(resp, ApiErrorId.ERR_CAP_NOT_EXECUTING, expected_status=409)


def test_benchmark_period_conflict(api, data_ops_headers):
    """PRD §3.7: "One benchmark per market and period start: a second load
    for the same `market_id` and `period_start` is rejected with
    `ERR_BENCHMARK_PERIOD_CONFLICT` (HTTP 409)."

    Design: Corner/validations/benchmark_period_conflict
    """
    market, _branch, _officer = setup_market_branch_officer()
    validate_success(
        api.create_peer_benchmark(
            {"market_id": market["id"], "period_start": "2026-04-01",
             "period_end": "2026-07-01", "peer_protected_origination_rate": 0.625,
             "peer_origination_count": 5000, "source": "HMDA"},
            data_ops_headers,
        ),
        expected_status=201,
    )
    resp = api.create_peer_benchmark(
        {"market_id": market["id"], "period_start": "2026-04-01",
         "period_end": "2026-07-01", "peer_protected_origination_rate": 0.60,
         "peer_origination_count": 5100, "source": "HMDA refresh"},
        data_ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BENCHMARK_PERIOD_CONFLICT,
                   expected_status=409)
    other = validate_success(
        api.create_peer_benchmark(
            {"market_id": market["id"], "period_start": "2026-07-01",
             "period_end": "2026-10-01", "peer_protected_origination_rate": 0.60,
             "peer_origination_count": 5100, "source": "HMDA Q3"},
            data_ops_headers,
        ),
        expected_status=201,
    )
    assert other["period_start"] == "2026-07-01"
