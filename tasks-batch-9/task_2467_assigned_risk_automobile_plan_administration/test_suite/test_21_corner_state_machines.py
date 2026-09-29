"""The plan's state machines: declared openings, lawful walks, refused triggers.

Every row in this system opens in a state the server chooses, walks only the
edges its own machine declares, and stops dead once it reaches a terminal state.
The tests below exercise those machines one entity at a time — the application
and its assignment, the policy on both of its axes, the claim, the cyclic
complaint review, and the two parents (the quota period and the carrier) that
reach their states because of the aggregate condition of their children.
"""
from test_helpers import (
    EXAMINER_ONE_USER_ID,
    EXAMINER_TWO_USER_ID,
    ApiErrorId,
    accept_assignment,
    acknowledge_claim,
    api_client,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_applicant_with_vehicle,
    create_cancellation_payload,
    create_claim_closure_payload,
    create_cure_return_payload,
    create_non_renewal_payload,
    create_policy_payload,
    create_quota_reconciliation_payload,
    create_rescission_payload,
    create_resolution_payload,
    create_resubmission_payload,
    create_voluntary_exit_payload,
    docket_complaint,
    make_compliance_examiner_headers,
    make_plan_administrator_headers,
    make_producer_agent_headers,
    make_servicing_carrier_headers,
    place_and_accept,
    read_applicant,
    read_application,
    read_assignment,
    read_assignment_cycle,
    read_carrier,
    read_claim,
    read_complaint,
    read_plan_period,
    read_policy,
    read_quota_reconciliation,
    record_deposit,
    record_findings,
    report_claim,
    resolve_complaint,
    run_cycle,
    schedule_cycle,
    set_clock,
    setup_policy_in_force,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

# The ADULT / PLEASURE / T02 clean risk the whole file rates against.
FINAL_PREMIUM_CENTS = 148337
EXPENSE_CHARGE_CENTS = 7417
TOTAL_ANNUAL_CHARGE_CENTS = 155754
REQUIRED_DEPOSIT_CENTS = 38939
UNCREDITED_CENTS = TOTAL_ANNUAL_CHARGE_CENTS - REQUIRED_DEPOSIT_CENTS

ADMIN = make_plan_administrator_headers()


# --------------------------------------------------------------------------
# Module-private setup helpers
# --------------------------------------------------------------------------
def _certified_risk():
    """A plan with two carriers and one certified ADULT T02 risk awaiting placement."""
    env = bootstrap_plan()
    risk = bring_application_to_certified(env)
    env.update(risk)
    return env


def _placed_risk():
    """The certified risk placed by a September cycle and still awaiting acceptance."""
    env = _certified_risk()
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    env["cycle"] = cycle
    env["assignment"] = assignment_for_application(env["application"]["id"])
    return env


def _claim_on_a_live_policy(**overrides):
    """An in-force policy carrying one OPEN claim reported the day after inception."""
    env = setup_policy_in_force()
    set_clock("2026-09-16T00:00:00Z")
    payload = dict(loss_date="2026-09-16T00:00:00Z", at_fault=False,
                   coverage_line="PD", reserve_cents=90000)
    payload.update(overrides)
    env["claim"] = report_claim(env["policy"]["id"], env["carrier"]["id"], **payload)
    return env


def _complaint_at_the_third_round():
    """Docket a complaint and return it for further review twice, reaching round 3.

    Each round is worked by examiner EX-1 and returned by examiner EX-2, so the
    segregation rule is never tripped. The complaint ends in FINDINGS_RECORDED
    with ``review_round`` at 3 and the round-3 note on file.
    """
    env = setup_policy_in_force()
    complaint = docket_complaint(env["policy"]["id"], env["carrier"]["id"])
    record_findings(complaint["id"], EXAMINER_ONE_USER_ID,
                    findings_note="Carrier records confirm the delay.")
    resolve_complaint(complaint["id"], "RETURNED_FOR_FURTHER_REVIEW", EXAMINER_TWO_USER_ID,
                      resolution_note="Obtain the carrier log.")
    env["after_first_return"] = read_complaint(complaint["id"])
    record_findings(complaint["id"], EXAMINER_ONE_USER_ID,
                    findings_note="Carrier log obtained.")
    resolve_complaint(complaint["id"], "RETURNED_FOR_FURTHER_REVIEW", EXAMINER_TWO_USER_ID,
                      resolution_note="Interview the insured.")
    record_findings(complaint["id"], EXAMINER_ONE_USER_ID,
                    findings_note="Final review complete.")
    env["complaint"] = read_complaint(complaint["id"])
    return env


def _file_reconciliation(carrier_id: str, plan_period_id: str, basis: str):
    """File a reconciliation, pinning the carrier version as it reads right now."""
    version = read_carrier(carrier_id)["version"]
    return api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(carrier_id, plan_period_id, basis, version), ADMIN)


def _period_in_reconciliation():
    """One written policy, the clock at the period's window_end, the period closed."""
    env = setup_policy_in_force()
    set_clock("2026-11-30T00:00:00Z")
    validate_success(api_client.close_plan_period(env["plan_period"]["id"], ADMIN))
    return env


# --------------------------------------------------------------------------
# Declared initial states
# --------------------------------------------------------------------------
def test_a_newly_enrolled_carrier_opens_active_with_a_perfect_score_and_an_open_posture():
    """Enrolment alone fixes a carrier's standing; the client supplies none of it.

    Neither carrier has been handed a risk, acknowledged a claim or answered a
    complaint, so both open on the top rung of the ladder with a pristine score,
    and the registration ordinal follows the order they were enrolled in.

    PRD: "A newly enrolled carrier starts with `status` `ACTIVE`,
    `performance_score` 100 and `posture` `OPEN`, receives the next
    `enrollment_sequence`"
    Design: Corner/state_machines/every_entity_opens_in_its_declared_initial_state
    """
    env = bootstrap_plan()

    atlas, beacon = env["carriers"]
    for carrier, sequence in ((atlas, 1), (beacon, 2)):
        assert carrier["status"] == "ACTIVE"
        assert carrier["performance_score"] == 100
        assert carrier["posture"] == "OPEN"
        assert carrier["enrollment_sequence"] == sequence
        assert carrier["assigned_risk_count"] == 0
        assert carrier["upheld_complaint_count"] == 0
        assert carrier["breach_count_current_period"] == 0


def test_a_submitted_application_opens_in_submitted_and_leaves_the_period_untouched():
    """Intake writes the application's own opening state and nothing else.

    Submission lands the application in the first state of its machine and hands
    it the first intake ordinal. Nothing has been certified yet, so the quota
    period it will eventually count against is still open at zero assignable
    units — the count moves on certification, not on submission.

    PRD: "On success the application lands in `SUBMITTED`, receives the next
    `intake_sequence`"
    Design: Corner/state_machines/every_entity_opens_in_its_declared_initial_state
    """
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()

    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])

    assert application["status"] == "SUBMITTED"
    assert application["intake_sequence"] == 1
    assert application["deposit_paid_total_cents"] == 0
    period = read_plan_period(env["plan_period"]["id"])
    assert period["status"] == "OPEN"
    assert period["total_assignable_units"] == 0


def test_a_placed_assignment_opens_in_pending_acceptance_as_an_initial_designation():
    """The selector mints the assignment; the carrier has not answered it yet.

    The run creates the row at the head of its own batch, marks it an initial
    designation with no predecessor, and leaves the rescission reason empty
    because nothing has been pulled back. The cycle that produced it was
    scheduled and has now completed.

    PRD: "Its `status` begins at `PENDING_ACCEPTANCE`, and the full `status`
    vocabulary is `PENDING_ACCEPTANCE`, `ACCEPTED`, `POLICY_ISSUED`, `RESCINDED`,
    `REASSIGNED` and `CLOSED`."
    Design: Corner/state_machines/every_entity_opens_in_its_declared_initial_state
    """
    env = _certified_risk()
    cycle = schedule_cycle(env["plan_period"]["id"])
    assert cycle["status"] == "SCHEDULED"

    run_cycle(cycle["id"])

    assignment = assignment_for_application(env["application"]["id"])
    assert assignment["status"] == "PENDING_ACCEPTANCE"
    assert assignment["batch_sequence"] == 1
    assert assignment["assignment_kind"] == "INITIAL"
    assert assignment["predecessor_assignment_id"] is None
    assert assignment["rescission_reason_code"] is None
    assert read_assignment_cycle(cycle["id"])["status"] == "COMPLETED"


def test_an_issued_policy_opens_in_force_with_its_premium_still_outstanding():
    """Both axes open at once, and the deposit is far short of the term charge.

    The 38939-cent deposit sweeps into premium at issuance but the annual charge
    is 155754, so the money axis can only open on PREMIUM_OUTSTANDING with the
    remaining 116815 restated as still due. The coverage axis opens in force, and
    the revision counter starts at its first rating.

    PRD: "The money axis is initialised from the result of that sweep —
    `premium_settlement_status` becomes `PAID_IN_FULL` when
    `premium_credited_cents` is at least `total_annual_charge_cents`, and
    `PREMIUM_OUTSTANDING` otherwise."
    Design: Corner/state_machines/every_entity_opens_in_its_declared_initial_state
    """
    env = setup_policy_in_force()

    policy = read_policy(env["policy"]["id"])
    assert policy["premium_settlement_status"] == "PREMIUM_OUTSTANDING"
    assert policy["premium_credited_cents"] == REQUIRED_DEPOSIT_CENTS
    assert policy["total_annual_charge_cents"] == TOTAL_ANNUAL_CHARGE_CENTS
    assert policy["additional_premium_due_cents"] == UNCREDITED_CENTS
    assert policy["policy_status"] == "IN_FORCE"
    assert policy["rating_revision"] == 1
    assert policy["reassignment_required"] is False


def test_a_docketed_complaint_opens_on_round_one_with_an_empty_findings_trail():
    """The complaint and the claim filed against a live policy both open OPEN.

    Docketing starts the review at its first round with every examiner field
    still empty, so no segregation comparison is possible yet. The loss reported
    against the same policy opens on the first state of its own machine.

    PRD: "A docketed complaint begins in `OPEN` with `review_round` at 1, and its
    `findings_recorded_by_user_id`, `findings_note`, `resolved_by_user_id` and
    `disposition` all begin null."
    Design: Corner/state_machines/every_entity_opens_in_its_declared_initial_state
    """
    env = _claim_on_a_live_policy()

    complaint = docket_complaint(env["policy"]["id"], env["carrier"]["id"])

    assert complaint["status"] == "OPEN"
    assert complaint["review_round"] == 1
    assert complaint["findings_recorded_by_user_id"] is None
    assert complaint["findings_note"] is None
    assert complaint["resolved_by_user_id"] is None
    assert complaint["disposition"] is None
    assert read_claim(env["claim"]["id"])["status"] == "OPEN"


# --------------------------------------------------------------------------
# The declared happy path of the claim machine
# --------------------------------------------------------------------------
def test_a_claim_walks_open_to_acknowledged_to_closed_paid_inside_the_standard():
    """Reported, acknowledged four days in, then paid at less than the reserve.

    The loss is reported on 2026-09-16, so the handling standard runs to
    2026-09-26. Acknowledging on 2026-09-20 is comfortably inside that window, so
    no breach is recorded and the carrier's standing is untouched. The paid
    closure then records 74500 of the 90000-cent reserve.

    PRD: "A `PAID` closure moves the claim `ACKNOWLEDGED → CLOSED_PAID` and
    records the supplied `paid_cents` as the indemnity paid; `paid_cents` may not
    exceed the claim's `reserve_cents`"
    Design: Corner/state_machines/claim_walks_open_to_acknowledged_to_closed_paid
    """
    env = _claim_on_a_live_policy()
    assert env["claim"]["status"] == "OPEN"
    assert env["claim"]["acknowledgement_deadline"].startswith("2026-09-26")
    set_clock("2026-09-20T00:00:00Z")
    acknowledged = acknowledge_claim(env["claim"]["id"], env["carrier"]["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_at"].startswith("2026-09-20")
    assert acknowledged["standard_breach"] is False

    closed = validate_success(api_client.close_claim(
        env["claim"]["id"], create_claim_closure_payload("PAID", paid_cents=74500),
        make_servicing_carrier_headers(env["carrier"]["id"])))

    assert closed["status"] == "CLOSED_PAID"
    assert closed["paid_cents"] == 74500
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["breach_count_current_period"] == 0
    assert carrier["performance_score"] == 100


def test_closing_a_not_at_fault_claim_leaves_the_clean_years_clock_alone():
    """Only an at-fault loss is chargeable, so the licensing date still governs.

    The closure recomputes nothing on the applicant because the claim was not at
    fault and no violation was ever verified. With no chargeable event at all the
    latest chargeable date is still the first licensed date of 2010, which at a
    2026 clock is far beyond the five-year credit cap.

    PRD: "`last_chargeable_event_date` is the latest of those event dates, or —
    when the applicant has no chargeable event at all — the applicant's
    `first_licensed_date`."
    Design: Corner/state_machines/claim_walks_open_to_acknowledged_to_closed_paid
    """
    env = _claim_on_a_live_policy()
    set_clock("2026-09-20T00:00:00Z")
    acknowledge_claim(env["claim"]["id"], env["carrier"]["id"])

    validate_success(api_client.close_claim(
        env["claim"]["id"], create_claim_closure_payload("PAID", paid_cents=74500),
        make_servicing_carrier_headers(env["carrier"]["id"])))

    applicant = read_applicant(env["applicant"]["id"])
    assert applicant["last_chargeable_event_date"].startswith("2010-06-01")
    assert applicant["clean_years_credited"] == 5


# --------------------------------------------------------------------------
# One issuance, five rows written
# --------------------------------------------------------------------------
def test_issuance_advances_the_assignment_and_the_application_and_copies_the_carrier():
    """The servicing carrier is inherited, never supplied, and two rows advance.

    Issuance is a single POST that answers 201 and writes across the placement
    chain: the policy takes its carrier from the assignment that authorised it,
    the assignment leaves ACCEPTED and the application leaves ASSIGNED. Rating is
    frozen at the effective date, where the clean record scores no points.

    PRD: "On success the policy's `carrier_id` is copied from the assignment, the
    assignment advances `ACCEPTED → POLICY_ISSUED`, and the application advances
    `ASSIGNED → POLICY_ISSUED`."
    Design: Corner/state_machines/policy_issuance_fires_its_whole_side_effect_list
    """
    env = _certified_risk()
    atlas = env["carriers"][0]
    placed = place_and_accept(env, env["application"]["id"], atlas["id"])
    set_clock("2026-09-15T00:00:00Z")

    policy = validate_success(api_client.create_policy(
        create_policy_payload(placed["assignment"]["id"], policy_number="AR-100014",
                              effective_date="2026-09-15T00:00:00Z",
                              expiration_date="2027-09-15T00:00:00Z"),
        make_servicing_carrier_headers(atlas["id"])), 201)

    assert policy["carrier_id"] == atlas["id"]
    assert read_assignment(placed["assignment"]["id"])["status"] == "POLICY_ISSUED"
    assert read_application(env["application"]["id"])["status"] == "POLICY_ISSUED"
    assert policy["surcharge_points_applied"] == 0
    assert policy["surcharge_factor_applied"] == 1.0
    assert policy["final_premium_cents"] == FINAL_PREMIUM_CENTS
    assert policy["plan_expense_charge_cents"] == EXPENSE_CHARGE_CENTS


def test_issuance_sweeps_the_deposit_and_starts_the_exposure_clock():
    """The application's balance drains into premium and the car-year clock opens.

    The whole 38939-cent balance sweeps into the policy because it is well under
    the 155754-cent cap, leaving the application's cumulative total intact and
    its balance at zero. Exposure is measured against the open period, and at a
    clock equal to the effective date no day has yet been earned.

    PRD: "The applicant's `deposit_balance_cents` sweeps into the policy's
    `premium_credited_cents`, capped at `total_annual_charge_cents`, per §2.8;
    `additional_premium_due_cents` is restated as whatever remains uncredited."
    Design: Corner/state_machines/policy_issuance_fires_its_whole_side_effect_list
    """
    env = _certified_risk()
    atlas = env["carriers"][0]
    placed = place_and_accept(env, env["application"]["id"], atlas["id"])
    set_clock("2026-09-15T00:00:00Z")

    policy = validate_success(api_client.create_policy(
        create_policy_payload(placed["assignment"]["id"], policy_number="AR-100014",
                              effective_date="2026-09-15T00:00:00Z",
                              expiration_date="2027-09-15T00:00:00Z"),
        make_servicing_carrier_headers(atlas["id"])), 201)

    assert policy["premium_credited_cents"] == REQUIRED_DEPOSIT_CENTS
    assert policy["total_annual_charge_cents"] == TOTAL_ANNUAL_CHARGE_CENTS
    assert policy["additional_premium_due_cents"] == UNCREDITED_CENTS
    application = read_application(env["application"]["id"])
    assert application["deposit_paid_total_cents"] == REQUIRED_DEPOSIT_CENTS
    assert application["deposit_balance_cents"] == 0
    assert policy["exposure_car_years_current_period"] == 0.0
    assert read_carrier(atlas["id"])["assigned_risk_count"] == 1


# --------------------------------------------------------------------------
# Triggers that no edge of the current state answers
# --------------------------------------------------------------------------
def test_curing_or_resubmitting_a_written_application_is_refused_by_its_own_machine():
    """Both edges leave SUBMITTED, and a written application is long past it.

    A cure return exists only out of SUBMITTED and a resubmission only out of
    RETURNED_FOR_CURE, so an application that has already produced a policy
    answers neither. Each refusal names the application machine specifically and
    nothing on the row moves.

    PRD: "the target row is in a state from which the requested transition
    exists"
    Design: Corner/state_machines/triggers_absent_from_a_states_transition_list_are_refused
    """
    env = setup_policy_in_force()
    application_id = env["application"]["id"]
    assert read_application(application_id)["status"] == "POLICY_ISSUED"

    validate_error(api_client.return_application_for_cure(
        application_id, create_cure_return_payload("Missing garaging proof."),
        make_compliance_examiner_headers()), ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
    validate_error(api_client.resubmit_application(
        application_id, create_resubmission_payload(
            requested_effective_date="2026-10-01T00:00:00Z"),
        make_producer_agent_headers(env["producer"]["id"])),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)

    application = read_application(application_id)
    assert application["status"] == "POLICY_ISSUED"
    assert application["cure_count"] == 0


def test_rescinding_an_assignment_that_already_carries_a_policy_is_refused():
    """Rescission reaches only untaken and unwritten designations.

    The plan may pull an assignment back while the carrier is still deciding or
    has accepted without writing, but once a policy references the assignment
    that edge is gone. The refusal names the assignment machine and the
    designation stays where issuance left it.

    PRD: "It is admissible while the assignment is `PENDING_ACCEPTANCE` or
    `ACCEPTED`, and only while no policy references that assignment."
    Design: Corner/state_machines/triggers_absent_from_a_states_transition_list_are_refused
    """
    env = setup_policy_in_force()
    assignment_id = env["assignment"]["id"]

    validate_error(api_client.rescind_assignment(
        assignment_id, create_rescission_payload("ISSUANCE_DEADLINE_MISSED"), ADMIN),
        ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE, 409)

    assignment = read_assignment(assignment_id)
    assert assignment["status"] == "POLICY_ISSUED"
    assert assignment["rescission_reason_code"] is None
    assert read_carrier(env["carrier"]["id"])["assigned_risk_count"] == 1


def test_closing_a_claim_that_was_never_acknowledged_is_refused():
    """Both closures leave ACKNOWLEDGED, so an unacknowledged loss cannot be closed.

    The claim is still OPEN because nobody acknowledged it, and the denial edge
    starts one state later. The refusal names the claim machine and the claim's
    indemnity stays at zero.

    PRD: "A `DENIED` closure moves the claim `ACKNOWLEDGED → CLOSED_DENIED`,
    requires a `denial_reason` to be present, and leaves `paid_cents` at 0."
    Design: Corner/state_machines/triggers_absent_from_a_states_transition_list_are_refused
    """
    env = _claim_on_a_live_policy()

    validate_error(api_client.close_claim(
        env["claim"]["id"],
        create_claim_closure_payload("DENIED", denial_reason="Not covered."),
        make_servicing_carrier_headers(env["carrier"]["id"])),
        ApiErrorId.ERR_INVALID_CLAIM_STATE, 409)

    claim = read_claim(env["claim"]["id"])
    assert claim["status"] == "OPEN"
    assert claim["paid_cents"] == 0


# --------------------------------------------------------------------------
# Terminal states
# --------------------------------------------------------------------------
def test_a_cancelled_policy_answers_no_further_coverage_axis_trigger():
    """Cancellation drives three rows terminal and closes every remaining edge.

    The carrier cancels for non-payment effective 2026-10-15. On the coverage
    axis CANCELLED is terminal, so a second cancellation, a voluntary exit and a
    non-renewal notice are all refused against the same machine. The application
    and the assignment are terminal too, and the headcount does not decrement a
    second time.

    PRD: "The coverage axis is `policy_status`, beginning at `IN_FORCE` and
    ranging over `IN_FORCE`, `REASSIGNMENT_PENDING`, `NON_RENEWAL_PENDING`,
    `NON_RENEWED`, `CANCELLED` and `EXITED_TO_VOLUNTARY`, of which the last three
    are terminal."
    Design: Corner/state_machines/terminal_states_accept_no_further_transition
    """
    env = setup_policy_in_force()
    policy_id = env["policy"]["id"]
    carrier_headers = make_servicing_carrier_headers(env["carrier"]["id"])
    validate_success(api_client.cancel_policy(policy_id, create_cancellation_payload(
        "NON_PAYMENT_OF_PREMIUM", "2026-10-15T00:00:00Z"), carrier_headers))
    set_clock("2026-10-15T00:00:00Z")

    validate_error(api_client.cancel_policy(policy_id, create_cancellation_payload(
        "NON_PAYMENT_OF_PREMIUM", "2026-10-20T00:00:00Z"), carrier_headers),
        ApiErrorId.ERR_INVALID_POLICY_STATE, 409)
    validate_error(api_client.exit_policy_to_voluntary(
        policy_id, create_voluntary_exit_payload("Applicant found a voluntary market."),
        ADMIN), ApiErrorId.ERR_INVALID_POLICY_STATE, 409)
    validate_error(api_client.serve_non_renewal_notice(
        policy_id, create_non_renewal_payload("Loss history."), carrier_headers),
        ApiErrorId.ERR_INVALID_POLICY_STATE, 409)

    assert read_policy(policy_id)["policy_status"] == "CANCELLED"
    assert read_application(env["application"]["id"])["status"] == "CLOSED_CANCELLED"
    assert read_assignment(env["assignment"]["id"])["status"] == "CLOSED"
    assert read_carrier(env["carrier"]["id"])["assigned_risk_count"] == 0


def test_a_completed_cycle_cannot_be_run_again():
    """A cycle reaches COMPLETED exactly once, so the run edge is spent.

    The September cycle already apportioned its queue and stamped its counters. A
    second run attempt is refused against the cycle machine, and the counters it
    recorded on its one lawful run are unchanged by the refusal.

    PRD: "It is admissible only while the cycle is still `SCHEDULED`, only once
    the clock has reached the cycle's `window_start`"
    Design: Corner/state_machines/terminal_states_accept_no_further_transition
    """
    env = setup_policy_in_force()

    validate_error(api_client.run_assignment_cycle(env["cycle"]["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_CYCLE_STATE, 409)

    cycle = read_assignment_cycle(env["cycle"]["id"])
    assert cycle["status"] == "COMPLETED"
    assert cycle["assigned_count"] == 1
    assert cycle["deferred_count"] == 0


# --------------------------------------------------------------------------
# Replaying a write
# --------------------------------------------------------------------------
def test_accepting_the_same_designation_twice_is_refused():
    """A transition is not idempotent: the second acceptance finds no edge.

    Atlas accepted the designation at a clock of 2026-09-01, which spends the
    only acceptance edge the machine offers. Replaying the identical POST is
    refused against the assignment machine, and the acceptance stamp from the
    first call is not rewritten.

    PRD: "The `ServicingCarrier` named on the assignment accepts it, and
    acceptance is admissible only while the assignment is `PENDING_ACCEPTANCE`"
    Design: Corner/state_machines/repeating_a_transition_trigger_is_refused_but_repeating_a_payment_is_not
    """
    env = _placed_risk()
    atlas = env["carriers"][0]
    accept_assignment(env["assignment"]["id"], atlas["id"])
    first = read_assignment(env["assignment"]["id"])
    assert first["status"] == "ACCEPTED"
    assert first["accepted_at"].startswith("2026-09-01")

    validate_error(api_client.accept_assignment(
        env["assignment"]["id"], make_servicing_carrier_headers(atlas["id"])),
        ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE, 409)

    again = read_assignment(env["assignment"]["id"])
    assert again["status"] == "ACCEPTED"
    assert again["accepted_at"] == first["accepted_at"]


def test_recording_a_second_deposit_is_a_lawful_additive_posting():
    """Money is not a transition, so a second payment simply accumulates.

    The risk already posted its required 38939 cents. A further 10000-cent
    payment is accepted on its own terms and raises both the cumulative total and
    the uncredited balance to 48939, because no policy exists yet for the money
    to sweep into.

    PRD: "A valid payment raises both `deposit_paid_total_cents` and
    `deposit_balance_cents` by `amount_cents`"
    Design: Corner/state_machines/repeating_a_transition_trigger_is_refused_but_repeating_a_payment_is_not
    """
    env = _placed_risk()
    assert read_application(env["application"]["id"])["deposit_paid_total_cents"] == \
        REQUIRED_DEPOSIT_CENTS

    record_deposit(env["application"]["id"], env["producer"]["id"], 10000)

    application = read_application(env["application"]["id"])
    assert application["deposit_paid_total_cents"] == REQUIRED_DEPOSIT_CENTS + 10000
    assert application["deposit_balance_cents"] == REQUIRED_DEPOSIT_CENTS + 10000
    _rows, meta = validate_paginated(api_client.list_policies(ADMIN))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# The acceptance window as a precondition of the edge
# --------------------------------------------------------------------------
def test_accepting_a_designation_one_day_past_the_deadline_is_refused():
    """The deadline day itself is open; the day after it is not.

    The cycle ran at a clock of 2026-09-01, so the designation's deadline is ten
    days later on 2026-09-11. At 2026-09-12 acceptance is refused. The assignment
    does not auto-rescind — it stays pending, the application stays assigned, and
    the carrier keeps both the headcount it took at selection and its score.

    PRD: "only while the clock is at or before the `acceptance_deadline` — a
    later attempt is refused with `ERR_ACCEPTANCE_WINDOW_EXPIRED` and HTTP 409"
    Design: Corner/state_machines/acceptance_after_the_ten_day_window_is_refused
    """
    env = _placed_risk()
    atlas = env["carriers"][0]
    assert env["assignment"]["acceptance_deadline"].startswith("2026-09-11")
    set_clock("2026-09-12T00:00:00Z")

    validate_error(api_client.accept_assignment(
        env["assignment"]["id"], make_servicing_carrier_headers(atlas["id"])),
        ApiErrorId.ERR_ACCEPTANCE_WINDOW_EXPIRED, 409)

    assignment = read_assignment(env["assignment"]["id"])
    assert assignment["status"] == "PENDING_ACCEPTANCE"
    assert assignment["accepted_at"] is None
    carrier = read_carrier(atlas["id"])
    assert carrier["assigned_risk_count"] == 1
    assert carrier["performance_score"] == 100
    assert read_application(env["application"]["id"])["status"] == "ASSIGNED"


# --------------------------------------------------------------------------
# The cyclic complaint machine
# --------------------------------------------------------------------------
def test_a_further_review_round_reopens_the_complaint_and_clears_the_findings():
    """The one cycle in the system: FINDINGS_RECORDED goes back to OPEN.

    The second examiner returns the complaint rather than disposing of it, which
    reopens it on the next round and wipes both the note and the identity of the
    examiner who wrote it, so the same examiner may work the next round without
    tripping the segregation rule.

    PRD: "`review_round` rises by 1, and both `findings_recorded_by_user_id` and
    `findings_note` are cleared so that a fresh examiner may record findings
    without tripping the segregation rule."
    Design: Corner/state_machines/complaint_review_loop_terminates_at_the_third_round
    """
    env = _complaint_at_the_third_round()

    returned = env["after_first_return"]

    assert returned["status"] == "OPEN"
    assert returned["review_round"] == 2
    assert returned["findings_recorded_by_user_id"] is None
    assert returned["findings_note"] is None
    assert env["complaint"]["review_round"] == 3
    assert env["complaint"]["status"] == "FINDINGS_RECORDED"


def test_a_fourth_review_round_is_refused_once_the_complaint_sits_at_round_three():
    """The loop has a hard stop, and the refusal changes nothing on the row.

    Two returns have carried the complaint to its third round, where findings are
    on file again. A further return is refused, the complaint keeps its round
    number and the round-three note is not cleared.

    PRD: "a further review round is only admissible while `review_round` is less
    than 3, and a request on a complaint already at its third round is refused
    with `ERR_REVIEW_ROUND_LIMIT` and HTTP 409"
    Design: Corner/state_machines/complaint_review_loop_terminates_at_the_third_round
    """
    env = _complaint_at_the_third_round()

    validate_error(api_client.resolve_complaint(
        env["complaint"]["id"],
        create_resolution_payload("RETURNED_FOR_FURTHER_REVIEW",
                                  resolution_note="Yet another pass."),
        make_compliance_examiner_headers(EXAMINER_TWO_USER_ID)),
        ApiErrorId.ERR_REVIEW_ROUND_LIMIT, 409)

    complaint = read_complaint(env["complaint"]["id"])
    assert complaint["status"] == "FINDINGS_RECORDED"
    assert complaint["review_round"] == 3
    assert complaint["findings_note"] == "Final review complete."
    assert read_carrier(env["carrier"]["id"])["performance_score"] == 100


def test_the_freeze_survives_every_review_round_and_lifts_only_on_disposition():
    """The insured stays protected while the cycle runs, and the row is not stuck.

    A return leaves the policy's open count alone, so the freeze is still on at
    round three. The complaint is not deadlocked either: an upheld disposition
    acts from FINDINGS_RECORDED, closes the review and drops the open count back
    to zero, which lifts the freeze.

    PRD: "The policy's `open_complaint_count` is deliberately left unchanged, so
    the freeze stays on across the round trip."
    Design: Corner/state_machines/complaint_review_loop_terminates_at_the_third_round
    """
    env = _complaint_at_the_third_round()
    frozen = read_policy(env["policy"]["id"])
    assert frozen["open_complaint_count"] == 1
    assert frozen["complaint_freeze_active"] is True

    resolve_complaint(env["complaint"]["id"], "UPHELD", EXAMINER_TWO_USER_ID)

    assert read_complaint(env["complaint"]["id"])["status"] == "RESOLVED_UPHELD"
    policy = read_policy(env["policy"]["id"])
    assert policy["open_complaint_count"] == 0
    assert policy["complaint_freeze_active"] is False


# --------------------------------------------------------------------------
# The period closes because of its children
# --------------------------------------------------------------------------
def test_the_period_closes_only_once_the_last_active_carrier_holds_a_final_row():
    """Two active carriers, so one filing is not enough to close the period.

    Atlas is reconciled first and the period must stay in reconciliation because
    Beacon is still outstanding. Beacon's filing is the last one the denominator
    demands, so the parent bubbles up to CLOSED without anyone calling an
    endpoint on it, with its assignable total still frozen at the single risk
    certified into the window.

    PRD: "when every carrier whose `status` is `ACTIVE` now holds a `FINAL`
    reconciliation for the period, the period bubbles up `RECONCILING → CLOSED`,
    which is terminal, and no further reconciliation row may be created for that
    period"
    Design: Corner/state_machines/period_closes_only_when_the_last_active_carrier_is_reconciled
    """
    env = _period_in_reconciliation()
    atlas, beacon = env["carriers"]
    period_id = env["plan_period"]["id"]
    assert read_plan_period(period_id)["status"] == "RECONCILING"

    validate_success(_file_reconciliation(atlas["id"], period_id, "POLICY_COUNT"), 201)
    assert read_plan_period(period_id)["status"] == "RECONCILING"
    second = validate_success(
        _file_reconciliation(beacon["id"], period_id, "POLICY_COUNT"), 201)

    assert second["status"] == "FINAL"
    period = read_plan_period(period_id)
    assert period["status"] == "CLOSED"
    assert period["total_assignable_units"] == 1


def test_a_filing_against_a_closed_period_is_refused_and_supersedes_nothing():
    """CLOSED is terminal, so the supersession machinery never runs.

    Both carriers have filed and the period has bubbled up to CLOSED. A third
    filing — Atlas on the other approved basis, pinning a freshly read carrier
    version so no concurrency rule can fire first — is refused on the period's
    state, and Atlas's existing row is still the final one.

    PRD: "The period's `status` must be `RECONCILING`; a filing against a period
    still open or already closed is refused with `ERR_PERIOD_NOT_RECONCILING` and
    HTTP 409."
    Design: Corner/state_machines/period_closes_only_when_the_last_active_carrier_is_reconciled
    """
    env = _period_in_reconciliation()
    atlas, beacon = env["carriers"]
    period_id = env["plan_period"]["id"]
    first = validate_success(
        _file_reconciliation(atlas["id"], period_id, "POLICY_COUNT"), 201)
    validate_success(_file_reconciliation(beacon["id"], period_id, "POLICY_COUNT"), 201)
    assert read_plan_period(period_id)["status"] == "CLOSED"

    validate_error(_file_reconciliation(atlas["id"], period_id, "CAR_YEAR_EXPOSURE"),
                   ApiErrorId.ERR_PERIOD_NOT_RECONCILING, 409)

    assert read_quota_reconciliation(first["id"])["status"] == "FINAL"
    assert read_plan_period(period_id)["status"] == "CLOSED"


# --------------------------------------------------------------------------
# One resolution, three entities
# --------------------------------------------------------------------------
def test_upholding_one_complaint_costs_twenty_points_and_restricts_the_carrier():
    """A single upheld complaint restricts but does not suspend.

    Atlas starts at 100 and the deduction takes it to 80, which lands inside the
    70-to-84 band of the ladder. Suspension sits below 70, so nothing is
    rescinded: the assignment that produced the policy is untouched and the
    carrier keeps its headcount.

    PRD: "its `upheld_complaint_count` rises by 1, its `performance_score` falls
    by 20 with a floor of 0, and its `posture` is recomputed"
    Design: Corner/state_machines/upholding_a_complaint_moves_the_carrier_and_the_policy
    """
    env = setup_policy_in_force()
    complaint = docket_complaint(env["policy"]["id"], env["carrier"]["id"])
    record_findings(complaint["id"], EXAMINER_ONE_USER_ID)

    resolve_complaint(complaint["id"], "UPHELD", EXAMINER_TWO_USER_ID)

    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["upheld_complaint_count"] == 1
    assert carrier["performance_score"] == 80
    assert carrier["posture"] == "RESTRICTED"
    assert carrier["status"] == "ACTIVE"
    assert carrier["assigned_risk_count"] == 1
    assert read_assignment(env["assignment"]["id"])["status"] == "POLICY_ISSUED"


def test_the_resolving_examiner_is_recorded_and_the_policy_freeze_lifts():
    """The disposition writes the complaint trail and releases the insured.

    EX-1 investigated and EX-2 disposed, so the two recorded identities differ
    and the trail names both. On the policy side the resolution drops the open
    count to zero, and the freeze derived from it lifts.

    PRD: "A second examiner then disposes of it by supplying a `disposition` and,
    optionally, a `resolution_note`; the resolving examiner's `X-User-ID` is
    written to `resolved_by_user_id`."
    Design: Corner/state_machines/upholding_a_complaint_moves_the_carrier_and_the_policy
    """
    env = setup_policy_in_force()
    complaint = docket_complaint(env["policy"]["id"], env["carrier"]["id"])
    record_findings(complaint["id"], EXAMINER_ONE_USER_ID)
    assert read_policy(env["policy"]["id"])["complaint_freeze_active"] is True

    resolved = validate_success(api_client.resolve_complaint(
        complaint["id"], create_resolution_payload("UPHELD"),
        make_compliance_examiner_headers(EXAMINER_TWO_USER_ID)))

    assert resolved["status"] == "RESOLVED_UPHELD"
    assert resolved["disposition"] == "UPHELD"
    assert resolved["resolved_by_user_id"] == EXAMINER_TWO_USER_ID
    assert resolved["findings_recorded_by_user_id"] == EXAMINER_ONE_USER_ID
    policy = read_policy(env["policy"]["id"])
    assert policy["open_complaint_count"] == 0
    assert policy["complaint_freeze_active"] is False


# --------------------------------------------------------------------------
# A claim transition writes the carrier's period ledger
# --------------------------------------------------------------------------
def test_a_late_acknowledgement_posts_a_breach_and_five_points_to_the_carrier():
    """The claim's own transition writes into its carrier's period counters.

    The loss was reported on 2026-09-16, so the standard expired on 2026-09-26.
    Acknowledging on 2026-09-27 is one day late: the breach flag goes up, the
    period breach counter reaches 1 and the score falls to 95. That is still
    above the restriction ceiling and one breach is below the three-breach rung,
    so the posture stays OPEN.

    PRD: "If `acknowledged_at` is later than `acknowledgement_deadline`, three
    things follow in the same request: `standard_breach` is set to true, the
    carrier's `breach_count_current_period` rises by 1, and the carrier's
    `performance_score` falls by 5 — floored at 0"
    Design: Corner/state_machines/a_late_acknowledgement_posts_to_the_carriers_breach_ledger
    """
    env = _claim_on_a_live_policy(coverage_line="BI", reserve_cents=120000)
    assert env["claim"]["acknowledgement_deadline"].startswith("2026-09-26")
    set_clock("2026-09-27T00:00:00Z")

    acknowledged = acknowledge_claim(env["claim"]["id"], env["carrier"]["id"])

    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["standard_breach"] is True
    assert acknowledged["acknowledged_at"].startswith("2026-09-27")
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["breach_count_current_period"] == 1
    assert carrier["performance_score"] == 95
    assert carrier["posture"] == "OPEN"


def test_closing_the_period_zeroes_the_breach_counter_and_credits_ten_points():
    """The period closure turns the page, and the recovery is clamped at 100.

    Atlas carries one breach and a score of 95 into the closure. Moving the
    period into reconciliation resets both per-period counters and adds the
    ten-point recovery, which the ceiling holds at 100 rather than 105.

    PRD: "`breach_count_current_period` is reset to 0,
    `non_renewal_count_current_period` is reset to 0, `performance_score` is
    raised by 10 but never above 100"
    Design: Corner/state_machines/a_late_acknowledgement_posts_to_the_carriers_breach_ledger
    """
    env = _claim_on_a_live_policy(coverage_line="BI", reserve_cents=120000)
    set_clock("2026-09-27T00:00:00Z")
    acknowledge_claim(env["claim"]["id"], env["carrier"]["id"])
    assert read_carrier(env["carrier"]["id"])["performance_score"] == 95
    set_clock("2026-11-30T00:00:00Z")

    validate_success(api_client.close_plan_period(env["plan_period"]["id"], ADMIN))

    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["breach_count_current_period"] == 0
    assert carrier["non_renewal_count_current_period"] == 0
    assert carrier["performance_score"] == 100
    assert read_plan_period(env["plan_period"]["id"])["status"] == "RECONCILING"


# --------------------------------------------------------------------------
# The clock-driven transition
# --------------------------------------------------------------------------
def test_serving_a_non_renewal_notice_pends_the_policy_and_dates_its_expiry():
    """The notice is the carrier's act; the effective date is the plan's.

    Served on 2026-09-15 against a term expiring 2027-09-15, the notice is well
    inside the 45-day warning requirement. The policy moves to pending
    non-renewal, its notice counter reaches its one-per-term limit, the maturity
    date is copied from the expiration date and the carrier's period quota of
    three notices is consumed by one.

    PRD: "A served notice moves the policy `IN_FORCE → NON_RENEWAL_PENDING`, sets
    `non_renewal_notice_count` to 1, records `non_renewal_effective_date` as the
    policy's `expiration_date`, and raises the carrier's
    `non_renewal_count_current_period` by 1."
    Design: Corner/state_machines/a_served_non_renewal_ripens_when_the_clock_reaches_expiration
    """
    env = setup_policy_in_force()

    policy = validate_success(api_client.serve_non_renewal_notice(
        env["policy"]["id"], create_non_renewal_payload("Adverse loss experience."),
        make_servicing_carrier_headers(env["carrier"]["id"])))

    assert policy["policy_status"] == "NON_RENEWAL_PENDING"
    assert policy["non_renewal_notice_count"] == 1
    assert policy["non_renewal_effective_date"].startswith("2027-09-15")
    assert read_carrier(env["carrier"]["id"])["non_renewal_count_current_period"] == 1


def test_serving_a_second_non_renewal_notice_on_the_same_term_is_refused():
    """Pending non-renewal offers no second notice edge.

    The first notice already moved the policy off IN_FORCE, which is the only
    state the notice edge leaves from, so the repeat is refused against the
    policy machine and the one-per-term counter does not move.

    PRD: "the target row is in a state from which the requested transition
    exists"
    Design: Corner/state_machines/a_served_non_renewal_ripens_when_the_clock_reaches_expiration
    """
    env = setup_policy_in_force()
    carrier_headers = make_servicing_carrier_headers(env["carrier"]["id"])
    validate_success(api_client.serve_non_renewal_notice(
        env["policy"]["id"], create_non_renewal_payload("Adverse loss experience."),
        carrier_headers))

    validate_error(api_client.serve_non_renewal_notice(
        env["policy"]["id"], create_non_renewal_payload("Served again."), carrier_headers),
        ApiErrorId.ERR_INVALID_POLICY_STATE, 409)

    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "NON_RENEWAL_PENDING"
    assert policy["non_renewal_notice_count"] == 1
    assert read_carrier(env["carrier"]["id"])["non_renewal_count_current_period"] == 1


def test_the_pending_non_renewal_ripens_on_the_next_read_after_the_clock_reaches_it():
    """No endpoint performs this transition — the clock does.

    Nothing is called on the policy between the notice and the maturity date. At
    a clock of 2027-09-15 the plain read reports the matured coverage state, the
    assignment behind it is closed out and the carrier's headcount falls by one.

    PRD: "once the clock reaches or passes `non_renewal_effective_date`, the
    policy is `NON_RENEWAL_PENDING → NON_RENEWED` as observed on the next read of
    that policy, its assignment moves to `CLOSED`, and the carrier's
    `assigned_risk_count` falls by 1"
    Design: Corner/state_machines/a_served_non_renewal_ripens_when_the_clock_reaches_expiration
    """
    env = setup_policy_in_force()
    validate_success(api_client.serve_non_renewal_notice(
        env["policy"]["id"], create_non_renewal_payload("Adverse loss experience."),
        make_servicing_carrier_headers(env["carrier"]["id"])))

    set_clock("2027-09-15T00:00:00Z")

    assert read_policy(env["policy"]["id"])["policy_status"] == "NON_RENEWED"
    assert read_assignment(env["assignment"]["id"])["status"] == "CLOSED"
    assert read_carrier(env["carrier"]["id"])["assigned_risk_count"] == 0
