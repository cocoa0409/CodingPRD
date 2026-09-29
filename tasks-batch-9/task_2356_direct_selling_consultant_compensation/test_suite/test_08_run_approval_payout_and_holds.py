"""Turning a calculated run into money: the approval guards, the disbursement boundary, the
payout hold read before recovery, and the gates that refuse a request before any of it."""

from test_helpers import (
    assert_commission_run,
    constants as k,
    factories as f,
    fixtures as fx,
    make_applicant_headers,
    make_consultant_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]
CONTROLLER = TEST_USERS["finance_controller_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def _second_run_after_reversal(api):
    """The three-generation run paid then reversed, with a second run paid over the same period.

    The reversal turns every disbursement into a clawback balance and puts both paid earners on
    payout hold, which is the state the second run has to settle against.
    """
    state = fx.setup_paid_run(api)
    assert state["run"]["paid_total_cents"] == 47000, "A and C were disbursed, B was carried"
    assert state["run"]["carry_forward_total_cents"] == 500, "B's 500 cents fell below the minimum"

    reversed_run = fx.reverse_run(api, state["run"])
    assert reversed_run["status"] == "REVERSED", "the paid run was reversed"
    assert reversed_run["reversed_total_cents"] == 47000, "reversed_total takes over paid_total"
    assert fx.read_consultant(api, state["a"]["id"])["clawback_balance_cents"] == 23800, (
        "A's disbursement became a receivable"
    )
    assert fx.read_consultant(api, state["c"]["id"])["clawback_balance_cents"] == 23200, (
        "C's disbursement became a receivable"
    )

    run2 = fx.create_run(api, state["period"])
    run2 = fx.calculate_run(api, run2)
    run2 = fx.approve_run(api, run2, decision_note="second pass after reversal")
    state["run1"] = reversed_run
    state["run2"] = fx.pay_run(api, run2)
    return state


def test_the_hold_is_read_before_recovery_so_the_net_amount_is_carried_not_paid(api):
    """A owes 23,800 and is on hold, so her 17,850 of net pay is carried forward even though the
    same transition has already recovered 5,950 against the debt.

    PRD: "Per `ACTIVE` statement, the disbursement test is evaluated against the consultant's
    `payout_hold` **as it stood at the start of the transition**, before any recovery from this run
    has been applied."

    Design: Difficulty/combinatorial_formula/payout_hold_evaluated_before_clawback_recovery_pinned_order
    """
    state = _second_run_after_reversal(api)
    statement = fx.statement_of(api, state["run2"]["id"], state["a"]["id"])
    assert statement["gross_commission_cents"] == 23800, "the same volume earns the same gross"
    assert statement["withhold_rate_bp"] == 2500, "23,800 is strictly above the tier threshold"
    assert statement["withholding_cents"] == 5950, (
        "2,500 basis points of 23,800 is 5,950, below the 23,800 owed, so the tier amount governs"
    )
    assert statement["net_payable_cents"] == 17850, "23,800 gross less 5,950 withheld"
    assert statement["paid_cents"] == 0, (
        "the hold stood at the start of the transition, so nothing is disbursed"
    )
    assert statement["carry_forward_cents"] == 17850, "the whole net amount is carried instead"
    assert statement["payout_status"] == "CARRIED_FORWARD", "a held earner is never paid"

    consultant = fx.read_consultant(api, state["a"]["id"])
    assert consultant["clawback_balance_cents"] == 17850, (
        "23,800 less the 5,950 recovered: recovery happens even though nothing was disbursed"
    )
    assert consultant["payout_hold"] is True, "a balance above zero re-derives the hold as true"
    assert consultant["lifetime_commission_paid_cents"] == 0, (
        "a carried-forward statement never touches lifetime commission paid"
    )
    assert consultant["carry_forward_cents"] == 17850, (
        "reading recovery first would have disbursed this 17,850 in cash instead"
    )


def test_every_statement_recovers_its_debt_while_the_run_disburses_nothing(api):
    """All three earners recover against their balances, yet the run pays out zero: two are held
    and the third is below the minimum payout.

    PRD: "The clawback recovery itself happens for every statement regardless of whether the net
    amount is disbursed: the consultant's `clawback_balance_cents` is decreased by the statement's
    `withholding_cents`, and `payout_hold` is then re-derived as true exactly when
    `clawback_balance_cents` is greater than 0."

    Design: Difficulty/combinatorial_formula/payout_hold_evaluated_before_clawback_recovery_pinned_order
    """
    state = _second_run_after_reversal(api)
    run2 = state["run2"]
    assert_commission_run(run2)
    assert run2["status"] == "PAID", "the run completed its payment transition"
    assert run2["gross_total_cents"] == 47500, "the second pass earns exactly what the first did"
    assert run2["withheld_total_cents"] == 11750, "5,950 for A plus 5,800 for C plus 0 for B"
    assert run2["net_payable_total_cents"] == 35750, "47,500 gross less 11,750 withheld"
    assert run2["paid_total_cents"] == 0, "not one cent left the company on this run"
    assert run2["carry_forward_total_cents"] == 35750, "the whole net total was carried forward"

    grandchild = fx.statement_of(api, run2["id"], state["c"]["id"])
    assert grandchild["withholding_cents"] == 5800, "2,500 basis points of C's 23,200 gross"
    assert grandchild["net_payable_cents"] == 17400, "23,200 less 5,800"
    assert grandchild["payout_status"] == "CARRIED_FORWARD", "C was on hold as well"
    assert fx.read_consultant(api, state["c"]["id"])["clawback_balance_cents"] == 17400, (
        "C's balance falls by exactly the amount withheld from her"
    )

    middle = fx.statement_of(api, run2["id"], state["b"]["id"])
    assert middle["withhold_rate_bp"] == 1000, "B's 500-cent gross is below the tier threshold"
    assert middle["withholding_cents"] == 0, (
        "B was carried forward on the first run, so she owes nothing and nothing is recovered"
    )
    assert middle["net_payable_cents"] == 500, "with nothing withheld the net equals the gross"
    assert middle["payout_status"] == "CARRIED_FORWARD", "500 cents is below the minimum payout"
    assert fx.read_consultant(api, state["b"]["id"])["payout_hold"] is False, (
        "a consultant who never received cash carries no balance and no hold"
    )


def _boundary_payout_run(api):
    """Two unrelated roots earning 2,500 and 2,495 cents, with the run APPROVED and unpaid."""
    env = fx.setup_environment(api)
    dana = fx.enroll_consultant(api, env, "dana@example.com", "Dana Root")
    eli = fx.enroll_consultant(api, env, "eli@example.com", "Eli Root")
    order_d = fx.place_and_pay_order(
        api, env, dana, [("SERUM", 25)], order_type="BUSINESS_SUPPLY", reference="PAY-D"
    )
    order_e = fx.place_and_pay_order(
        api, env, eli, [("SAMPLE", 499)], order_type="BUSINESS_SUPPLY", reference="PAY-E"
    )
    assert order_d["total_volume_points"] == 500, "twenty-five SERUM at twenty points each"
    assert order_e["total_volume_points"] == 499, "499 SAMPLE at one point each"

    closed = fx.lock_and_close(api, env["periods"]["2026-08"])
    run = fx.calculate_run(api, fx.create_run(api, closed))
    assert run["gross_total_cents"] == 4995, (
        "500 points band to 2,500 cents and 499 points to 2,495, with no override anywhere"
    )
    return {"env": env, "d": dana, "e": eli, "run": fx.approve_run(api, run)}


def test_a_net_amount_exactly_at_the_minimum_payout_is_disbursed(api):
    """2,500 cents of net pay is exactly the plan's minimum, and the comparison is at-or-above, so
    the money leaves and lifetime commission paid rises by it.

    PRD: "Then, when the statement's `net_payable_cents` is at or above the plan's
    `min_payout_cents` and the consultant's `payout_hold` was false at the start of the transition,
    `paid_cents` is set to `net_payable_cents`, `carry_forward_cents` is 0, `payout_status` becomes
    `PAID`, and the consultant's `lifetime_commission_paid_cents` rises by the paid amount."

    Design: Difficulty/boundary_precision_check/net_payable_at_min_payout_cents_pays_and_one_cent_below_carries_forward
    """
    state = _boundary_payout_run(api)
    assert k.PLAN_DEFAULTS["min_payout_cents"] == 2500, "the boundary the two earners straddle"
    paid_run = fx.pay_run(api, state["run"])
    assert paid_run["withheld_total_cents"] == 0, (
        "withholding is the smaller of the tier amount and a clawback balance of 0"
    )

    statement = fx.statement_of(api, paid_run["id"], state["d"]["id"])
    assert statement["withhold_rate_bp"] == 1000, "2,500 is below the withholding tier threshold"
    assert statement["net_payable_cents"] == 2500, "nothing is recovered from a debt-free earner"
    assert statement["payout_status"] == "PAID", "landing exactly on the minimum disburses"
    assert statement["paid_cents"] == 2500, "the whole net amount is paid"
    assert statement["carry_forward_cents"] == 0, "nothing is carried when everything is paid"
    assert statement["paid_as_rank_code"] == "CONSULTANT", "a lone root holds the first rung"
    assert statement["override_total_cents"] == 0, "there is no downline to draw an override from"

    consultant = fx.read_consultant(api, state["d"]["id"])
    assert consultant["lifetime_commission_paid_cents"] == 2500, "lifetime rises by the paid amount"
    assert consultant["carry_forward_cents"] == 0, "nothing was carried for this earner"
    assert consultant["payout_hold"] is False, "no balance was created by a clean payment"


def test_five_cents_below_the_minimum_payout_carries_the_whole_amount_forward(api):
    """2,495 cents is below the minimum, so the identical run carries it in full and the run's paid
    and carried totals partition the gross exactly.

    PRD: "Otherwise — a net amount below the minimum payout, or a consultant who was on hold —
    `paid_cents` is 0, `carry_forward_cents` is set to `net_payable_cents`, `payout_status` becomes
    `CARRIED_FORWARD`, and the consultant's own `carry_forward_cents` rises by that amount."

    Design: Difficulty/boundary_precision_check/net_payable_at_min_payout_cents_pays_and_one_cent_below_carries_forward
    """
    state = _boundary_payout_run(api)
    paid_run = fx.pay_run(api, state["run"])
    assert paid_run["status"] == "PAID", "the run reaches PAID even when part of it is carried"

    statement = fx.statement_of(api, paid_run["id"], state["e"]["id"])
    assert statement["net_payable_cents"] == 2495, "499 points band to five cents less than 2,500"
    assert statement["payout_status"] == "CARRIED_FORWARD", "below the minimum nothing is disbursed"
    assert statement["paid_cents"] == 0, "not a cent of it is paid"
    assert statement["carry_forward_cents"] == 2495, "the whole net amount is carried"

    consultant = fx.read_consultant(api, state["e"]["id"])
    assert consultant["lifetime_commission_paid_cents"] == 0, "a carry never touches lifetime paid"
    assert consultant["carry_forward_cents"] == 2495, "the consultant's own carry rises by it"

    assert paid_run["paid_total_cents"] == 2500, "only the boundary earner was disbursed"
    assert paid_run["carry_forward_total_cents"] == 2495, "only the earner below it was carried"
    assert paid_run["paid_total_cents"] + paid_run["carry_forward_total_cents"] == 4995, (
        "a five-cent step decides which side of the partition each earner falls on"
    )


def _calculated_run_with_suspended_grandchild(api):
    """The three-generation run CALCULATED, then C sanctioned to SUSPENSION."""
    state = fx.setup_calculated_run(api)
    assert state["run"]["status"] == "CALCULATED", "the run itself is in order"
    assert state["run"]["statement_count"] == 3, "one statement per qualification row"
    case = fx.sanction_consultant(
        api,
        state["c"],
        sanction_level="SUSPENSION",
        effective_from="2026-08-05T00:00:00Z",
        effective_until="2026-08-25T00:00:00Z",
    )
    assert case["status"] == "SANCTIONED", "the sanction was imposed on the grandchild"
    assert fx.read_consultant(api, state["c"]["id"])["status"] == "SUSPENDED", (
        "the SUSPENSION drove the earner to SUSPENDED"
    )
    state["case"] = case
    return state


def test_one_suspended_earner_blocks_approval_of_an_otherwise_perfect_run(api):
    """Nothing is wrong inside the run, yet a third party's status refuses the approval; a REJECT
    decision on the very same run is not blocked at all.

    PRD: "The run must be `CALCULATED`; then the segregation rule of §2.11 applies, and a caller
    whose `X-User-ID` equals `calculated_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`;
    then, for an `APPROVE` decision only, no consultant holding an `ACTIVE` statement of the run
    may have status `SUSPENDED`, or the decision is refused with
    `ERR_SUSPENDED_EARNER_BLOCKS_APPROVAL` — a suspended earner must be resolved before the money
    moves. A `REJECT` decision is never blocked by a suspended earner."

    Design: Difficulty/cross_entity_state_dependency/run_approval_blocked_while_a_downline_earner_is_suspended
    """
    state = _calculated_run_with_suspended_grandchild(api)
    run_id = state["run"]["id"]

    validate_error(
        api.decide_commission_run_approval(
            run_id, f.approval_decision_payload("APPROVE", "first attempt"), CONTROLLER
        ),
        "ERR_SUSPENDED_EARNER_BLOCKS_APPROVAL",
        409,
    )

    unchanged = validate_success(api.get_commission_run(run_id, CONTROLLER))
    assert unchanged["status"] == "CALCULATED", "the refused decision left the run where it was"
    assert unchanged["approved_by_user_id"] is None, "no approver was recorded"
    assert unchanged["gross_total_cents"] == 47500, "the blocking condition never touched the run"

    grandchild_statement = fx.statement_of(api, run_id, state["c"]["id"])
    assert grandchild_statement["status"] == "ACTIVE", "the suspended earner still holds a live row"
    assert grandchild_statement["gross_commission_cents"] == 23200, "her earnings are untouched"
    assert grandchild_statement["payout_status"] == "PENDING", "no payout status was promoted"

    rejected = validate_success(
        api.decide_commission_run_approval(
            run_id, f.approval_decision_payload("REJECT", "recalculate later"), CONTROLLER
        )
    )
    assert rejected["status"] == "DRAFT", "a rejection is admitted while the earner is suspended"
    assert rejected["statement_count"] == 0, "the rejection reset the run's statement count"


def test_dismissing_the_sanction_lets_the_identical_approval_call_succeed(api):
    """With no write of any kind to the run, returning the grandchild to ACTIVE makes the byte-wise
    identical approval succeed and promotes every statement to PAYABLE.

    PRD: "`APPROVE` drives `CALCULATED → APPROVED`, records `approved_by_user_id`, and sets every
    `ACTIVE` statement's `payout_status` to `PAYABLE`."

    Design: Difficulty/cross_entity_state_dependency/run_approval_blocked_while_a_downline_earner_is_suspended
    """
    state = _calculated_run_with_suspended_grandchild(api)
    run_id = state["run"]["id"]
    payload = f.approval_decision_payload("APPROVE", "settle the period")

    validate_error(
        api.decide_commission_run_approval(run_id, payload, CONTROLLER),
        "ERR_SUSPENDED_EARNER_BLOCKS_APPROVAL",
        409,
    )

    fx.appeal_case(api, state["c"], state["case"], "the wording came from the approved brochure")
    fx.review_case(api, state["case"])
    dismissed = fx.dismiss_case(api, state["case"], decision_reason="appeal upheld")
    assert dismissed["status"] == "DISMISSED", "the appeal was upheld"
    assert fx.read_consultant(api, state["c"]["id"])["status"] == "ACTIVE", (
        "dismissing a case that imposed SUSPENSION returns the consultant to ACTIVE"
    )

    approved = validate_success(api.decide_commission_run_approval(run_id, payload, CONTROLLER))
    assert approved["status"] == "APPROVED", (
        "the identical call now succeeds: the blocking condition lived in the consultant row"
    )
    assert approved["approved_by_user_id"] == k.CONTROLLER_USER_ID, "the controller is recorded"
    assert approved["gross_total_cents"] == 47500, "no recalculation happened in between"
    for label, consultant in (("A", state["a"]), ("B", state["b"]), ("C", state["c"])):
        statement = fx.statement_of(api, run_id, consultant["id"])
        assert statement["payout_status"] == "PAYABLE", f"{label}: approval promotes every statement"


def test_an_approved_run_freezes_its_period_its_earners_and_its_own_uniqueness(api):
    """While a run sits APPROVED and unpaid, a second run, a reopen and a termination are each
    refused, and none of the three refusals moves anything.

    PRD: "It requires `status` `CLOSED`, refusing anything else with `ERR_PERIOD_NOT_CLOSED`, and
    it is additionally blocked while any commission run of the period is in `DRAFT`, `CALCULATED`,
    `APPROVED` or `PAID`: a paid period must have its run reversed before its volume can be
    corrected, and an attempt is refused with `ERR_ACTIVE_RUN_BLOCKS_REOPEN`."

    Design: Corner/state_machines/an_approved_run_guards_its_period_and_its_earners
    """
    state = fx.setup_single_earner_closed_period(api)
    run = fx.approve_run(api, fx.calculate_run(api, fx.create_run(api, state["period"])))
    assert run["status"] == "APPROVED", "the run is approved and awaiting payment"

    period = fx.read_period(api, state["period"]["id"])
    validate_error(
        api.create_commission_run(
            f.commission_run_payload(period["id"], period["version"]), ANALYST
        ),
        "ERR_RUN_ALREADY_EXISTS",
        409,
    )
    validate_error(
        api.reopen_qualification_period(period["id"], f.reopen_payload("LATE_ORDER"), ADMIN),
        "ERR_ACTIVE_RUN_BLOCKS_REOPEN",
        409,
    )
    validate_error(
        api.terminate_consultant(
            state["a"]["id"], f.termination_payload("DISCIPLINARY"), COMPLIANCE
        ),
        "ERR_APPROVED_RUN_BLOCKS_TERMINATION",
        409,
    )

    after_run = validate_success(api.get_commission_run(run["id"], ANALYST))
    assert after_run["status"] == "APPROVED", "the run is still awaiting payment"
    after_period = fx.read_period(api, period["id"])
    assert after_period["status"] == "CLOSED", "the period was never reopened"
    assert after_period["reopen_count"] == 0, "no reopen was recorded"
    assert fx.read_consultant(api, state["a"]["id"])["status"] == "ACTIVE", (
        "the earner cannot be terminated between approval and payment"
    )
    runs, meta = validate_paginated(
        api.list_commission_runs(ANALYST, params={"qualification_period_id": period["id"]})
    )
    assert meta["total_count"] == 1, "the period still holds exactly one run"
    assert runs[0]["id"] == run["id"], "and it is the approved one"


def test_the_gate_keeping_errors_fire_in_their_own_order_before_any_domain_rule(api):
    """Missing credentials, a wrong role, a resource the caller does not own and a malformed page
    request are each refused on their own rung, and the owner's identical read succeeds.

    PRD: "A `Consultant` or `Applicant` caller that addresses a resource they do not own is
    rejected with `ERR_FORBIDDEN_RESOURCE` (HTTP 403), and this row-level check runs before any
    body validation."

    Design: Corner/errors/the_four_gate_keeping_errors_fire_in_priority_order
    """
    env = fx.setup_environment(api)
    alice = fx.enroll_root(api, env)
    bob = fx.enroll_consultant(
        api, env, "bob@example.com", "Bob Leg", sponsor_consultant_id=alice["id"]
    )
    bob_order = fx.place_and_pay_order(
        api, env, bob, [("SERUM", 5)], order_type="PERSONAL_INVENTORY", reference="PAY-OB"
    )
    cara = fx.create_application(api, env, "cara@example.com", "Cara Wait",
                                 sponsor_consultant_id=alice["id"])
    assert cara["status"] == "DRAFT", "Cara's application has cleared no gate yet"

    validate_error(api.list_compensation_plans(None), "ERR_UNAUTHENTICATED", 401)

    validate_error(
        api.create_compensation_plan(
            f.compensation_plan_payload("PLAN-X", "Sneaky Plan"),
            make_consultant_headers(alice["id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_commission_run(
            f.commission_run_payload(env["periods"]["2026-08"]["id"], 1), LEGAL
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.list_consultants(make_applicant_headers("cara@example.com")),
        "ERR_UNAUTHORIZED",
        403,
    )

    validate_error(
        api.get_product_order(bob_order["id"], make_consultant_headers(alice["id"])),
        "ERR_FORBIDDEN_RESOURCE",
        403,
    )
    validate_error(
        api.accept_agreement(
            cara["id"], f.accept_agreement_payload(), make_applicant_headers("alice@example.com")
        ),
        "ERR_FORBIDDEN_RESOURCE",
        403,
    )

    validate_error(api.list_consultants(ADMIN, params={"limit": 0}), "ERR_VALIDATION", 400)

    owned = validate_success(
        api.get_product_order(bob_order["id"], make_consultant_headers(bob["id"]))
    )
    assert owned["consultant_id"] == bob["id"], (
        "the same read from the owning consultant succeeds, so ownership is not a blanket deny"
    )
    assert validate_success(api.get_enrollment_application(cara["id"], ADMIN))["status"] == "DRAFT", (
        "the refused agreement acceptance left Cara's application in DRAFT"
    )


def test_a_version_that_was_correct_before_the_close_is_refused_after_it(api):
    """The close is itself a write, so the version an analyst held while the period was LOCKED is
    stale against the CLOSED period, and creating the run bumps the version once more.

    PRD: "The run is created only when that value equals the period's current `version`; otherwise
    nothing is written and the request is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_period_version_on_run_creation_is_refused_with_412
    """
    env = fx.setup_environment(api)
    alice = fx.enroll_root(api, env)
    fx.place_and_pay_order(api, env, alice, [("SERUM", 30)], order_type="PERSONAL_INVENTORY")
    period = env["periods"]["2026-08"]

    locked = fx.lock_period(api, period)
    assert locked["status"] == "LOCKED", "the period is frozen but not yet settled"

    validate_error(
        api.create_commission_run(
            f.commission_run_payload(period["id"], locked["version"]), ANALYST
        ),
        "ERR_PERIOD_NOT_CLOSED",
        409,
    )

    closed = fx.close_period(api, locked)
    assert closed["version"] == locked["version"] + 1, (
        "the close transition is a write and bumps the period version"
    )

    validate_error(
        api.create_commission_run(
            f.commission_run_payload(period["id"], locked["version"]), ANALYST
        ),
        "ERR_STALE_PERIOD_VERSION",
        412,
    )
    assert fx.read_period(api, period["id"])["version"] == closed["version"], (
        "the refused creation wrote nothing at all"
    )

    run = validate_success(
        api.create_commission_run(
            f.commission_run_payload(period["id"], closed["version"]), ANALYST
        ),
        201,
    )
    assert run["period_code"] == "2026-08", "period_code is denormalised from the period"
    assert run["status"] == "DRAFT", "a fresh run starts in DRAFT"
    assert fx.read_period(api, period["id"])["version"] == closed["version"] + 1, (
        "creating the run increments the version again, so the next analyst is stale in turn"
    )
