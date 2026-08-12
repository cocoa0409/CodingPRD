"""Remediation pool allocation, CAP lifecycle, funds conservation, cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cap_funds_invariant,
    create_cap,
    create_executing_cap,
    create_submitted_cap,
    get_payment_for_application,
    list_payments_for_cap,
    make_specialist_headers,
    setup_executing_cap,
    setup_run_with_substantiated_finding,
    validate_error,
    validate_success,
)

def test_remediation_allocation_rounds_per_line_then_residual(api):
    """PRD §3.8: "Approval is also the moment the remediation waterfall
    runs: with n the number of entries in the finding's
    `harmed_application_ids`, each entry spawns one `AUTO_ALLOCATED`
    payment in `PENDING` whose amount is the pool divided by n, rounded
    half-up to whole cents; the residual — the pool minus n times that
    rounded share, possibly negative — is applied to the payment whose
    application appears first in the client-pinned array order."

    Design: Difficulty/combinatorial_formula/remediation_allocation_per_line_rounding_then_residual
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2", "p3"), pool_cents=10_000)
    cap_id = ctx["cap"]["id"]
    pay1 = get_payment_for_application(cap_id, ctx["apps"]["p1"]["id"])
    pay2 = get_payment_for_application(cap_id, ctx["apps"]["p2"]["id"])
    pay3 = get_payment_for_application(cap_id, ctx["apps"]["p3"]["id"])
    # round_half_up(10000 / 3) = 3333 per line; residual +1 lands on the
    # application appearing FIRST in harmed_application_ids.
    assert pay1["amount_cents"] == 3334, (
        f"first-listed application receives share 3333 + residual 1, got "
        f"{pay1['amount_cents']}"
    )
    assert pay2["amount_cents"] == 3333
    assert pay3["amount_cents"] == 3333


def test_remediation_allocation_sums_to_pool_exactly(api):
    """PRD §3.8: "After allocation the payment amounts sum exactly to
    `pool_cents`, so `remaining_cents` is 0 whenever at least one harmed
    application exists; an empty harmed set generates no payments and
    leaves `remaining_cents` equal to `pool_cents`."

    Design: Difficulty/combinatorial_formula/remediation_allocation_per_line_rounding_then_residual
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2", "p3"), pool_cents=10_000)
    cap_id = ctx["cap"]["id"]
    payments = list_payments_for_cap(cap_id)
    assert len(payments) == 3
    for payment in payments:
        assert payment["origin"] == "AUTO_ALLOCATED"
        assert payment["status"] == "PENDING"
    total = sum(p["amount_cents"] for p in payments)
    assert total == 10_000, f"allocation sums to pool exactly, got {total}"
    cap = validate_success(
        api.get_corrective_action_plan(cap_id, TEST_USERS["specialist_headers"])
    )
    assert cap["status"] == "EXECUTING"
    assert cap["remaining_cents"] == 0


def test_cap_return_revise_cycle(api, analyst_headers, officer_headers):
    """PRD §3.8: "Return moves `SUBMITTED` → `RETURNED` (payload `reason`),
    revision re-enters `DRAFT`, and cancellation from either `DRAFT` or
    `RETURNED` terminates the plan at `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/cap_return_revise_cycle_and_auto_complete
    """
    ctx = setup_run_with_substantiated_finding(harmed_keys=("p1",))
    cap = create_cap(ctx["finding"], pool_cents=3_000)
    s1 = validate_success(
        api.submit_corrective_action_plan(cap["id"], analyst_headers)
    )
    assert s1["status"] == "SUBMITTED"
    s2 = validate_success(
        api.return_corrective_action_plan(
            cap["id"], {"reason": "strengthen monitoring milestone"},
            officer_headers,
        )
    )
    assert s2["status"] == "RETURNED"
    s3 = validate_success(
        api.revise_corrective_action_plan(cap["id"], analyst_headers)
    )
    assert s3["status"] == "DRAFT", "returned plans re-enter DRAFT for revision"
    s4 = validate_success(
        api.submit_corrective_action_plan(cap["id"], analyst_headers)
    )
    assert s4["status"] == "SUBMITTED"


def test_cap_auto_completes_and_closes_finding(api, officer_headers,
                                               specialist_headers):
    """PRD §3.8: "Completion is automatic: when every payment of the plan
    is terminal (`DISBURSED`, `VOIDED`, or `RETURNED`) and at least one is
    `DISBURSED`, the plan — whether `EXECUTING` or `OVERDUE` — moves to
    `COMPLETED`, its linked finding moves to `CLOSED`, and the finding's
    run has its `open_finding_count` decremented."

    Design: Difficulty/non_linear_state_machine/cap_return_revise_cycle_and_auto_complete
    """
    ctx = setup_run_with_substantiated_finding(harmed_keys=("p1",))
    cap = create_executing_cap(ctx["finding"], pool_cents=3_000,
                               approver_user_id="officer-1")
    payment = get_payment_for_application(cap["id"], ctx["apps"]["p1"]["id"])
    assert payment["amount_cents"] == 3_000, "pool/n = 3000/1, residual 0"
    disbursed = validate_success(
        api.disburse_remediation_payment(
            payment["id"], make_specialist_headers("specialist-1")
        )
    )
    assert disbursed["status"] == "DISBURSED"
    cap_now = validate_success(
        api.get_corrective_action_plan(cap["id"], specialist_headers)
    )
    assert cap_now["status"] == "COMPLETED"
    assert cap_now["disbursed_cents"] == 3_000
    finding_now = validate_success(
        api.get_finding(ctx["finding"]["id"], officer_headers)
    )
    assert finding_now["status"] == "CLOSED", "completion cascades to the finding"
    run_now = validate_success(
        api.get_analysis_run(ctx["run"]["id"], officer_headers)
    )
    assert run_now["open_finding_count"] == 0
    assert run_now["status"] == "UNDER_REVIEW", "run awaits officer finalize"


def test_disburse_chain_mid_state_keeps_finding_open(api, officer_headers):
    """PRD §3.8: "Completion is automatic: when every payment of the plan
    is terminal (`DISBURSED`, `VOIDED`, or `RETURNED`) and at least one is
    `DISBURSED`, the plan — whether `EXECUTING` or `OVERDUE` — moves to
    `COMPLETED`, its linked finding moves to `CLOSED`, and the finding's
    run has its `open_finding_count` decremented."

    Design: Difficulty/transitive_cascade/disburse_to_cap_complete_to_finding_close_to_run_rollup
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2"), pool_cents=2_000,
                              approver_user_id="officer-1")
    pay1 = get_payment_for_application(
        ctx["cap"]["id"], ctx["apps"]["p1"]["id"]
    )
    validate_success(
        api.disburse_remediation_payment(
            pay1["id"], make_specialist_headers("specialist-1")
        )
    )
    run_mid = validate_success(
        api.get_analysis_run(ctx["run"]["id"], officer_headers)
    )
    assert run_mid["open_finding_count"] == 1, (
        "one payment still PENDING: the chain has not fired yet"
    )
    finding_mid = validate_success(
        api.get_finding(ctx["finding"]["id"], officer_headers)
    )
    assert finding_mid["status"] == "SUBSTANTIATED"


def test_disburse_chain_completes_cap_closes_finding_rolls_run_up(api,
                                                                  officer_headers):
    """PRD §3.8: "Completion is automatic: when every payment of the plan
    is terminal (`DISBURSED`, `VOIDED`, or `RETURNED`) and at least one is
    `DISBURSED`, the plan — whether `EXECUTING` or `OVERDUE` — moves to
    `COMPLETED`, its linked finding moves to `CLOSED`, and the finding's
    run has its `open_finding_count` decremented."

    Design: Difficulty/transitive_cascade/disburse_to_cap_complete_to_finding_close_to_run_rollup
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2"), pool_cents=2_000,
                              approver_user_id="officer-1")
    pay1 = get_payment_for_application(
        ctx["cap"]["id"], ctx["apps"]["p1"]["id"]
    )
    pay2 = get_payment_for_application(
        ctx["cap"]["id"], ctx["apps"]["p2"]["id"]
    )
    validate_success(
        api.disburse_remediation_payment(
            pay1["id"], make_specialist_headers("specialist-1")
        )
    )
    second = validate_success(
        api.disburse_remediation_payment(
            pay2["id"], make_specialist_headers("specialist-1")
        )
    )
    assert second["status"] == "DISBURSED"
    cap_now = validate_success(
        api.get_corrective_action_plan(ctx["cap"]["id"], officer_headers)
    )
    assert cap_now["status"] == "COMPLETED"
    assert cap_now["disbursed_cents"] == 2_000
    assert cap_now["remaining_cents"] == 0
    finding_now = validate_success(
        api.get_finding(ctx["finding"]["id"], officer_headers)
    )
    assert finding_now["status"] == "CLOSED"
    run_now = validate_success(
        api.get_analysis_run(ctx["run"]["id"], officer_headers)
    )
    assert run_now["open_finding_count"] == 0


def test_payment_exactly_remaining_budget_accepted(api, specialist_headers):
    """PRD §3.9: "the amount must not exceed the plan's `remaining_cents`,
    else `ERR_CAP_BUDGET_EXCEEDED` (HTTP 422). A created manual payment
    lands in `PENDING` and immediately reduces `remaining_cents` by its
    amount."
    PRD §3.9: "Voiding a `PENDING` payment moves it to terminal `VOIDED`
    with the supplied `reason` kept in `disposition_reason`, returning its
    amount to `remaining_cents`, and likewise triggers the completion
    check."

    Design: Difficulty/boundary_precision_check/payment_exactly_remaining_budget
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2", "p3"), pool_cents=10_000,
                              approver_user_id="officer-1")
    pay1 = get_payment_for_application(
        ctx["cap"]["id"], ctx["apps"]["p1"]["id"]
    )
    voided = validate_success(
        api.void_remediation_payment(
            pay1["id"], {"reason": "duplicate allocation"},
            make_specialist_headers("specialist-1"),
        )
    )
    assert voided["status"] == "VOIDED"
    cap_mid = validate_success(
        api.get_corrective_action_plan(ctx["cap"]["id"], specialist_headers)
    )
    assert cap_mid["remaining_cents"] == 3334, "void returns 3334 to the pool"
    manual = validate_success(
        api.create_remediation_payment(
            {"corrective_action_plan_id": ctx["cap"]["id"],
             "application_id": ctx["apps"]["p1"]["id"], "amount_cents": 3334},
            make_specialist_headers("specialist-1"),
        ),
        expected_status=201,
    )
    assert manual["status"] == "PENDING", "amount == remaining_cents passes <="
    cap_now = validate_success(
        api.get_corrective_action_plan(ctx["cap"]["id"], specialist_headers)
    )
    assert cap_now["remaining_cents"] == 0


def test_payment_one_cent_over_zero_remaining_rejected(api, specialist_headers):
    """PRD §3.9: "the amount must not exceed the plan's `remaining_cents`,
    else `ERR_CAP_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/payment_exactly_remaining_budget
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2", "p3"), pool_cents=10_000,
                              approver_user_id="officer-1")
    pay1 = get_payment_for_application(
        ctx["cap"]["id"], ctx["apps"]["p1"]["id"]
    )
    validate_success(
        api.void_remediation_payment(
            pay1["id"], {"reason": "duplicate allocation"},
            make_specialist_headers("specialist-1"),
        )
    )
    validate_success(
        api.create_remediation_payment(
            {"corrective_action_plan_id": ctx["cap"]["id"],
             "application_id": ctx["apps"]["p1"]["id"], "amount_cents": 3334},
            make_specialist_headers("specialist-1"),
        ),
        expected_status=201,
    )
    resp = api.create_remediation_payment(
        {"corrective_action_plan_id": ctx["cap"]["id"],
         "application_id": ctx["apps"]["p2"]["id"], "amount_cents": 1},
        make_specialist_headers("specialist-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CAP_BUDGET_EXCEEDED, expected_status=422)


def test_cap_pool_cents_conserved_under_void(api, specialist_headers):
    """PRD §2.10: "Remediation money obeys a conservation invariant on
    every corrective action plan: at all times, `pool_cents` equals
    `remaining_cents` plus the sum of `amount_cents` over that plan's
    payments in `PENDING` or `DISBURSED` status."
    PRD §3.9: "Voiding a `PENDING` payment moves it to terminal `VOIDED`
    with the supplied `reason` kept in `disposition_reason`, returning its
    amount to `remaining_cents`, and likewise triggers the completion
    check."

    Design: Difficulty/compensating_invariant/cap_pool_cents_conserved_under_void_and_return
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2", "p3"), pool_cents=10_000,
                              approver_user_id="officer-1")
    cap_id = ctx["cap"]["id"]
    cap0 = validate_success(api.get_corrective_action_plan(cap_id, specialist_headers))
    assert cap0["remaining_cents"] == 0
    assert_cap_funds_invariant(cap0, list_payments_for_cap(cap_id))
    pay1 = get_payment_for_application(cap_id, ctx["apps"]["p1"]["id"])
    pay2 = get_payment_for_application(cap_id, ctx["apps"]["p2"]["id"])
    validate_success(
        api.void_remediation_payment(
            pay1["id"], {"reason": "misallocated"},
            make_specialist_headers("specialist-1"),
        )
    )
    cap1 = validate_success(api.get_corrective_action_plan(cap_id, specialist_headers))
    assert cap1["remaining_cents"] == 3334
    assert cap1["disbursed_cents"] == 0
    assert_cap_funds_invariant(cap1, list_payments_for_cap(cap_id))
    validate_success(
        api.disburse_remediation_payment(
            pay2["id"], make_specialist_headers("specialist-1")
        )
    )
    cap2 = validate_success(api.get_corrective_action_plan(cap_id, specialist_headers))
    assert cap2["remaining_cents"] == 3334
    assert cap2["disbursed_cents"] == 3333
    assert_cap_funds_invariant(cap2, list_payments_for_cap(cap_id))


def test_cap_pool_cents_conserved_under_return(api, specialist_headers):
    """PRD §3.9: "Marking a `DISBURSED` payment returned moves it to
    terminal `RETURNED` — the funds are clawed back: `remaining_cents`
    grows and `disbursed_cents` shrinks by the amount."
    PRD §2.10: "Remediation money obeys a conservation invariant on every
    corrective action plan: at all times, `pool_cents` equals
    `remaining_cents` plus the sum of `amount_cents` over that plan's
    payments in `PENDING` or `DISBURSED` status."

    Design: Difficulty/compensating_invariant/cap_pool_cents_conserved_under_void_and_return
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2", "p3"), pool_cents=10_000,
                              approver_user_id="officer-1")
    cap_id = ctx["cap"]["id"]
    pay1 = get_payment_for_application(cap_id, ctx["apps"]["p1"]["id"])
    pay2 = get_payment_for_application(cap_id, ctx["apps"]["p2"]["id"])
    validate_success(
        api.void_remediation_payment(
            pay1["id"], {"reason": "misallocated"},
            make_specialist_headers("specialist-1"),
        )
    )
    validate_success(
        api.disburse_remediation_payment(
            pay2["id"], make_specialist_headers("specialist-1")
        )
    )
    validate_success(
        api.mark_returned_remediation_payment(
            pay2["id"], {"reason": "check returned undeliverable"},
            make_specialist_headers("specialist-1"),
        )
    )
    cap = validate_success(api.get_corrective_action_plan(cap_id, specialist_headers))
    assert cap["remaining_cents"] == 6667, "clawback returns the disbursed share"
    assert cap["disbursed_cents"] == 0
    payments = list_payments_for_cap(cap_id)
    assert_cap_funds_invariant(cap, payments)
    assert cap["pool_cents"] == 10_000, "no drift in the conserved money quantity"


def test_payment_terminal_lockdown(api, specialist_headers):
    """PRD §2.8: "(`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` when the
    target is already in a terminal state)".
    PRD §3.9: "Voiding a `PENDING` payment moves it to terminal `VOIDED`
    with the supplied `reason` kept in `disposition_reason`, returning its
    amount to `remaining_cents`, and likewise triggers the completion
    check."

    Design: Corner/state_machines/payment_terminal_lockdown
    """
    ctx = setup_executing_cap(harmed_keys=("p1", "p2"), pool_cents=2_000,
                              approver_user_id="officer-1")
    pay1 = get_payment_for_application(
        ctx["cap"]["id"], ctx["apps"]["p1"]["id"]
    )
    voided = validate_success(
        api.void_remediation_payment(
            pay1["id"], {"reason": "misallocated"},
            make_specialist_headers("specialist-1"),
        )
    )
    assert voided["status"] == "VOIDED"
    resp = api.disburse_remediation_payment(
        pay1["id"], make_specialist_headers("specialist-1")
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
    current = validate_success(
        api.get_remediation_payment(pay1["id"], specialist_headers)
    )
    assert current["status"] == "VOIDED"
    cap = validate_success(
        api.get_corrective_action_plan(ctx["cap"]["id"], specialist_headers)
    )
    assert cap["remaining_cents"] == 1000, "rollups do not move on the rejection"
