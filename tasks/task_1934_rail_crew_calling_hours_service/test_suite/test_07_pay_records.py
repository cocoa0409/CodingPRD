"""Agreement pay: two-variant rounding, dispute loop, finalization (PRD §2.7, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_pay_record_payload,
    make_employee_headers,
    set_clock,
    setup_tied_up_assignment,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]
CALLER = TEST_USERS["crew_caller_headers"]


def _submit(ctx):
    return api_client.submit_pay_record(
        ctx["pay_record"]["id"], make_employee_headers(ctx["employee"]["id"])
    )


def test_pay_provisional_variant_rounds_each_component(api):
    """PRD §2.7: "The **provisional** variant, used when a claim is submitted or
    resubmitted, rounds each of the three pay components — basic, overtime,
    deadhead — half-up to integer cents separately, then sums them."
    PRD §2.7: "The variants diverge whenever the components' fractional parts
    straddle a half-cent boundary: for a claim of 600 duty minutes with 100
    deadhead minutes traveled by `TRAIN`, the provisional computation yields
    74,867 cents while the final computation yields 74,866 cents."

    Design: Difficulty/dual_variant_calc/pay_provisional_vs_final_divergence_on_train_deadhead
    """
    set_clock()
    # 600-minute tour with 100 deadhead minutes by TRAIN -> auto-claim 600/100.
    ctx = setup_tied_up_assignment(tour_minutes=600,
                                   report_time="2026-08-02T08:00:00Z",
                                   deadhead_minutes=100, deadhead_mode="TRAIN")
    assert ctx["pay_record"]["claimed_minutes"] == 600
    assert ctx["pay_record"]["claimed_deadhead_minutes"] == 100

    resp = _submit(ctx)
    data = validate_success(resp)
    assert data["record_status"] == "SUBMITTED"
    # rhu(30010) + rhu(11253.75) + rhu(33602.7083) = 30010 + 11254 + 33603
    assert data["gross_pay_cents"] == 74867, (
        f"provisional per-component rounding must yield 74867, got {data['gross_pay_cents']}"
    )


def test_pay_final_variant_rounds_once_and_diverges(api):
    """PRD §2.7: "The **final** variant, used at finalization, sums the three
    unrounded exact components and rounds half-up to integer cents once."
    PRD §3.6: "For the worked example above, the exact sum is 74,866.4583…
    cents, rounding once to 74,866, one cent below the provisional figure; the
    record's `gross_pay_cents` is updated accordingly."

    Design: Difficulty/dual_variant_calc/pay_provisional_vs_final_divergence_on_train_deadhead
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=600,
                                   report_time="2026-08-02T08:00:00Z",
                                   deadhead_minutes=100, deadhead_mode="TRAIN")
    resp = _submit(ctx)
    submitted = validate_success(resp)
    provisional = submitted["gross_pay_cents"]

    resp = api_client.finalize_pay_record(
        ctx["pay_record"]["id"],
        {"expected_pay_record_version": submitted["version"]},
        MANAGER,
    )
    final = validate_success(resp)
    assert final["record_status"] == "FINALIZED"
    assert final["gross_pay_cents"] == 74866, (
        f"final round-once variant must yield 74866, got {final['gross_pay_cents']}"
    )
    assert final["gross_pay_cents"] != provisional, (
        "the two pinned variants must diverge by exactly one cent on this claim"
    )


def test_provisional_per_component_rounding_on_short_claim(api):
    """PRD §3.6: "The basic component is the basic-day rate of 30,010 cents
    multiplied by the smaller of `claimed_minutes` and 480, divided by 480."
    PRD §3.6: "The deadhead component is the deadhead hourly rate of 18,755
    cents multiplied by `claimed_deadhead_minutes` divided by 60, and then
    multiplied further by 1.075 when the assignment's `deadhead_mode` is `TRAIN`
    (by 1.0 otherwise)."
    PRD §3.6: "The provisional variant rounds each component half-up to integer
    cents and then sums the three rounded values."

    Design: Difficulty/combinatorial_formula/pay_rounding_order_per_component_vs_sum
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=480,
                                   report_time="2026-08-02T06:00:00Z",
                                   deadhead_minutes=3, deadhead_mode="TRAIN")
    _submit(ctx)
    api_client.dispute_pay_record(ctx["pay_record"]["id"], MANAGER)
    resp = api_client.resubmit_pay_record(
        ctx["pay_record"]["id"],
        {"claimed_minutes": 479, "claimed_deadhead_minutes": 3},
        make_employee_headers(ctx["employee"]["id"]),
    )
    data = validate_success(resp)
    # rhu(30010*479/480) + rhu(0) + rhu(18755*3/60*1.075) = 29947 + 0 + 1008
    assert data["gross_pay_cents"] == 30955, (
        f"provisional per-component rounding must yield 30955, got {data['gross_pay_cents']}"
    )


def test_final_single_rounding_on_short_claim_differs_by_one(api):
    """PRD §2.7: "The **final** variant, used at finalization, sums the three
    unrounded exact components and rounds half-up to integer cents once."
    PRD §3.6: "It recomputes `gross_pay_cents` under the final variant —
    summing the three exact, unrounded components and rounding half-up to
    integer cents once — and writes the delta between provisional and final
    back into `gross_pay_cents`."

    Design: Difficulty/combinatorial_formula/pay_rounding_order_per_component_vs_sum
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=480,
                                   report_time="2026-08-02T06:00:00Z",
                                   deadhead_minutes=3, deadhead_mode="TRAIN")
    _submit(ctx)
    api_client.dispute_pay_record(ctx["pay_record"]["id"], MANAGER)
    resp = api_client.resubmit_pay_record(
        ctx["pay_record"]["id"],
        {"claimed_minutes": 479, "claimed_deadhead_minutes": 3},
        make_employee_headers(ctx["employee"]["id"]),
    )
    resubmitted = validate_success(resp)

    resp = api_client.finalize_pay_record(
        ctx["pay_record"]["id"],
        {"expected_pay_record_version": resubmitted["version"]},
        MANAGER,
    )
    final = validate_success(resp)
    # rhu(29947.4791667 + 0 + 1008.08125) = rhu(30955.5604167) = 30956
    assert final["gross_pay_cents"] == 30956, (
        f"final round-once variant must yield 30956, got {final['gross_pay_cents']}"
    )
    assert final["gross_pay_cents"] - resubmitted["gross_pay_cents"] == 1


def test_dispute_moves_submitted_record_to_disputed(api):
    """PRD §3.6: "A manager who questions a submitted claim disputes it, moving
    the record to `DISPUTED` with no other effect."
    PRD §3.6: "The record lifecycle runs `DRAFT` to `SUBMITTED` to `FINALIZED`,
    with a dispute loop from `SUBMITTED` to `DISPUTED` and back to `SUBMITTED`;
    `FINALIZED` is terminal."

    Design: Difficulty/non_linear_state_machine/payrecord_dispute_resubmit_cycle
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=480,
                                   report_time="2026-08-02T06:00:00Z")
    resp = _submit(ctx)
    submitted = validate_success(resp)
    # 480 minutes, no deadhead: provisional = rhu(30010) + 0 + 0
    assert submitted["gross_pay_cents"] == 30010

    resp = api_client.dispute_pay_record(ctx["pay_record"]["id"], MANAGER)
    data = validate_success(resp)
    assert data["record_status"] == "DISPUTED"


def test_resubmit_recomputes_provisional_and_closes_loop(api):
    """PRD §3.6: "The employee then resubmits with amended `claimed_minutes` and
    optionally amended `claimed_deadhead_minutes`; resubmission returns the
    record to `SUBMITTED` and recomputes `gross_pay_cents` under the same
    provisional variant against the amended figures."
    PRD §3.6: "The overtime component is 1.5 times the basic-day rate,
    multiplied by the excess of `claimed_minutes` over 480 (zero when the claim
    is 480 minutes or less), divided by 480."

    Design: Difficulty/non_linear_state_machine/payrecord_dispute_resubmit_cycle
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=480,
                                   report_time="2026-08-02T06:00:00Z")
    _submit(ctx)
    api_client.dispute_pay_record(ctx["pay_record"]["id"], MANAGER)
    resp = api_client.resubmit_pay_record(
        ctx["pay_record"]["id"], {"claimed_minutes": 490},
        make_employee_headers(ctx["employee"]["id"]),
    )
    data = validate_success(resp)
    assert data["record_status"] == "SUBMITTED", "dispute loop must close"
    # rhu(30010) + rhu(1.5*30010*10/480) + 0 = 30010 + 938
    assert data["gross_pay_cents"] == 30948, (
        f"amended 490-minute claim must recompute to 30948, got {data['gross_pay_cents']}"
    )


def test_finalize_replaces_provisional_with_final(api):
    """PRD §3.6: "It recomputes `gross_pay_cents` under the final variant —
    summing the three exact, unrounded components and rounding half-up to
    integer cents once — and writes the delta between provisional and final
    back into `gross_pay_cents`."

    Design: Difficulty/compensating_invariant/pay_finalize_reconciles_provisional_delta
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=480,
                                   report_time="2026-08-02T08:00:00Z",
                                   deadhead_minutes=100, deadhead_mode="TRAIN")
    _submit(ctx)
    api_client.dispute_pay_record(ctx["pay_record"]["id"], MANAGER)
    resp = api_client.resubmit_pay_record(
        ctx["pay_record"]["id"],
        {"claimed_minutes": 600, "claimed_deadhead_minutes": 100},
        make_employee_headers(ctx["employee"]["id"]),
    )
    resubmitted = validate_success(resp)
    assert resubmitted["gross_pay_cents"] == 74867

    resp = api_client.finalize_pay_record(
        ctx["pay_record"]["id"],
        {"expected_pay_record_version": resubmitted["version"]},
        MANAGER,
    )
    final = validate_success(resp)
    assert final["record_status"] == "FINALIZED"
    assert final["gross_pay_cents"] == 74866, (
        "the final value must fully replace the provisional 74867 "
        f"(delta absorbed, not stacked), got {final['gross_pay_cents']}"
    )


def test_finalize_increments_record_version(api):
    """PRD §3.6: "Finalization increments the record's `version` by one."

    Design: Difficulty/compensating_invariant/pay_finalize_reconciles_provisional_delta
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=480,
                                   report_time="2026-08-02T08:00:00Z",
                                   deadhead_minutes=100, deadhead_mode="TRAIN")
    _submit(ctx)
    api_client.dispute_pay_record(ctx["pay_record"]["id"], MANAGER)
    resp = api_client.resubmit_pay_record(
        ctx["pay_record"]["id"],
        {"claimed_minutes": 600, "claimed_deadhead_minutes": 100},
        make_employee_headers(ctx["employee"]["id"]),
    )
    resubmitted = validate_success(resp)

    resp = api_client.finalize_pay_record(
        ctx["pay_record"]["id"],
        {"expected_pay_record_version": resubmitted["version"]},
        MANAGER,
    )
    final = validate_success(resp)
    assert final["version"] == resubmitted["version"] + 1, (
        f"finalize must increment version by one: {resubmitted['version']} -> "
        f"{final['version']}"
    )


def test_agreement_pay_basic_day_under_threshold(api):
    """PRD §3.6: "The basic component is the basic-day rate of 30,010 cents
    multiplied by the smaller of `claimed_minutes` and 480, divided by 480."
    PRD §3.6: "The overtime component is 1.5 times the basic-day rate,
    multiplied by the excess of `claimed_minutes` over 480 (zero when the claim
    is 480 minutes or less), divided by 480."
    PRD §3.6: "The provisional variant rounds each component half-up to integer
    cents and then sums the three rounded values."

    Design: Corner/calculations/agreement_pay_basic_day_under_threshold
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=240,
                                   report_time="2026-08-02T06:00:00Z")
    resp = _submit(ctx)
    data = validate_success(resp)
    # rhu(30010 * 240/480) + 0 + 0 = 15005
    assert data["gross_pay_cents"] == 15005, (
        f"half a basic day must pay 15005, got {data['gross_pay_cents']}"
    )


def test_pay_submit_zero_minutes_rejected(api):
    """PRD §3.6: "Submitting a draft requires `claimed_minutes` strictly greater
    than zero — otherwise `ERR_PAY_INCOMPLETE` (HTTP 422) — and triggers the
    provisional pay computation, writing `gross_pay_cents`."

    Design: Corner/validations/pay_submit_zero_minutes_rejected
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=240,
                                   report_time="2026-08-02T06:00:00Z")
    emp_id = ctx["employee"]["id"]
    payload = create_pay_record_payload(
        emp_id, ctx["assignment"]["id"], claimed_minutes=0
    )
    resp = api_client.create_pay_record(payload, make_employee_headers(emp_id))
    manual = validate_success(resp, expected_status=201)

    resp = api_client.submit_pay_record(manual["id"], make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_PAY_INCOMPLETE)


def test_payrecord_finalize_from_draft_rejected(api):
    """PRD §3.6: "The record lifecycle runs `DRAFT` to `SUBMITTED` to
    `FINALIZED`, with a dispute loop from `SUBMITTED` to `DISPUTED` and back to
    `SUBMITTED`; `FINALIZED` is terminal."
    PRD §2.9: "Sixth, state validity: the target entity must sit in a from-state
    listed for the requested transition — a call must be `OFFERED` to accept,
    decline, rescind, or record no-answer; an assignment must be `MARKED_UP` to
    go on duty or lay off; a job must be `BULLETINED` or `CALLING` to issue a
    call — rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/payrecord_finalize_from_draft_rejected
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=240,
                                   report_time="2026-08-02T06:00:00Z")
    pay = ctx["pay_record"]
    assert pay["record_status"] == "DRAFT"
    resp = api_client.finalize_pay_record(
        pay["id"], {"expected_pay_record_version": pay["version"]}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
