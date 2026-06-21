"""Validation tests: priority-pair precedence, boundary precision, cross-entity state
dependencies, and single-failure business-rule validations.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency.
Queue B (Corner): validations.* instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_employer,
    create_standard_policy,
    create_fee_schedule,
    create_pay_period,
    create_worker,
    post_time_entry,
    post_shift_6h_gross_12000,
    post_shift_10h_gross_20000,
    post_shifts_for_gross_80000,
    setup_base_scenario,
    setup_defaulted_advance_319,
    setup_worker_on_hold_via_writeoff,
    request_advance,
    request_and_approve_advance,
    request_approve_disburse_advance,
    lock_period,
    open_batch,
    post_batch,
    lock_and_post_batch,
    run_payday,
    get_worker_version,
)

OFFICER = TEST_USERS["payroll_officer_headers"]
POSTER = TEST_USERS["payroll_poster_headers"]
SIGNER = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict / invalid_state_beats_employer_frozen_on_approve
# ===========================================================================
def test_invalid_state_beats_employer_frozen_on_approve(api):
    """PRD §2.11: "State legality — whether the requested transition is defined from the target's
    current state — is checked sixth, yielding `ERR_INVALID_STATE`."
    PRD §2.11: "Only after all of these do the domain-specific business rules described in Section
    3 apply, in the order their workflows present them."

    Approving an already-DECLINED advance (no valid from-state) under a FROZEN employer fails both
    the state check and the frozen business rule; the state check (sixth) precedes any Section-3
    business rule, so ERR_INVALID_STATE wins.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_employer_frozen_on_approve
    """
    # pp1: drive employer to FROZEN via a DISCREPANCY at payday.
    employer, _p, _f, pp1, worker = setup_base_scenario()
    post_shift_6h_gross_12000(pp1["id"], worker["id"])
    request_approve_disburse_advance(worker["id"], pp1["id"], 6000, disbursement_speed="INSTANT")
    lock_and_post_batch(pp1["id"])
    run_payday(pp1["id"])
    assert validate_success(api.get_employer(employer["id"], OFFICER))["posture"] == "FROZEN"

    # pp2: a second advance that we DECLINE (terminal), then attempt to approve.
    pp2 = create_pay_period(employer["id"], start_at="2026-06-08T00:00:00Z", end_at="2026-06-15T00:00:00Z")
    post_time_entry(pp2["id"], worker["id"], "2026-06-09T08:00:00Z", "2026-06-09T14:00:00Z", 6.0)
    adv2 = request_advance(worker["id"], pp2["id"], 2000, disbursement_speed="STANDARD")
    get_success_data(api.decline_advance(adv2["id"], OFFICER))

    resp = api.approve_advance(adv2["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_declined_advance_under_frozen_employer_not_frozen_error(api):
    """PRD §2.11: "State legality ... is checked sixth, yielding `ERR_INVALID_STATE`. ... Only
    after all of these do the domain-specific business rules described in Section 3 apply".
    PRD §2.9: "While the posture is `FROZEN`, disbursement-class operations — locking a period,
    running payday, approving an advance, and disbursing an advance — are blocked with
    `ERR_EMPLOYER_FROZEN` (HTTP 409)."

    The returned error must be ERR_INVALID_STATE, not ERR_EMPLOYER_FROZEN, because the state
    check is ordered ahead of the frozen business rule.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_employer_frozen_on_approve
    """
    employer, _p, _f, pp1, worker = setup_base_scenario()
    post_shift_6h_gross_12000(pp1["id"], worker["id"])
    request_approve_disburse_advance(worker["id"], pp1["id"], 6000, disbursement_speed="INSTANT")
    lock_and_post_batch(pp1["id"])
    run_payday(pp1["id"])

    pp2 = create_pay_period(employer["id"], start_at="2026-06-08T00:00:00Z", end_at="2026-06-15T00:00:00Z")
    post_time_entry(pp2["id"], worker["id"], "2026-06-09T08:00:00Z", "2026-06-09T14:00:00Z", 6.0)
    adv2 = request_advance(worker["id"], pp2["id"], 2000, disbursement_speed="STANDARD")
    get_success_data(api.decline_advance(adv2["id"], OFFICER))

    resp = api.approve_advance(adv2["id"], OFFICER)
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, (
        f"state check must pre-empt frozen; got {body['data']['error_id']}"
    )


# ===========================================================================
# Queue A — priority_pair_validation_conflict / worker_on_hold_beats_cooling_off_on_approve
# ===========================================================================
def test_worker_on_hold_beats_cooling_off_on_approve(api):
    """PRD §3.5: "The worker's `advance_eligibility` must be `ELIGIBLE`, else `ERR_WORKER_ON_HOLD`.
    The employer's posture must be `HEALTHY` or `RESTRICTED` and not `FROZEN`, else
    `ERR_EMPLOYER_FROZEN`. The cooling-off interval must be satisfied — that is, the time elapsed
    from the worker's most recent disbursed advance's `disbursed_at` to the server clock must be
    at least the employer's `cooling_off_hours`, or there must be no prior disbursed advance at
    all — else `ERR_COOLING_OFF_ACTIVE`."
    PRD §2.11: "Only after all of these do the domain-specific business rules described in Section
    3 apply, in the order their workflows present them."

    A worker who is ON_HOLD (written-off advance) and also inside the cooling-off window fails
    both; the ON_HOLD check precedes the cooling-off check in §3.5 workflow order, so the error is
    ERR_WORKER_ON_HOLD. The fixture clears the employer FROZEN posture first (write-off + signed
    clean statement) so the frozen rule passes.

    Design: Difficulty/priority_pair_validation_conflict/worker_on_hold_beats_cooling_off_on_approve
    """
    employer, pp1, pp2, worker, adv1, adv2 = setup_worker_on_hold_via_writeoff()
    # Move clock to 1h after disbursement so cooling-off (24h) is also violated.
    set_clock("2026-06-01T01:00:00Z")
    # Precondition sanity: employer is not FROZEN, worker is ON_HOLD.
    assert validate_success(api.get_employer(employer["id"], OFFICER))["posture"] != "FROZEN"
    assert validate_success(api.get_worker(worker["id"], OFFICER))["advance_eligibility"] == "ON_HOLD"

    resp = api.approve_advance(adv2["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_WORKER_ON_HOLD.value)


def test_on_hold_worker_approve_returns_on_hold_not_cooling_off(api):
    """PRD §3.5: "The worker's `advance_eligibility` must be `ELIGIBLE`, else `ERR_WORKER_ON_HOLD`.
    ... The cooling-off interval must be satisfied ... else `ERR_COOLING_OFF_ACTIVE`."

    With both the ON_HOLD and the cooling-off conditions violated, the returned error must be
    ERR_WORKER_ON_HOLD (it is listed earlier in the §3.5 approve workflow), not
    ERR_COOLING_OFF_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/worker_on_hold_beats_cooling_off_on_approve
    """
    employer, pp1, pp2, worker, adv1, adv2 = setup_worker_on_hold_via_writeoff()
    set_clock("2026-06-01T01:00:00Z")

    resp = api.approve_advance(adv2["id"], OFFICER)
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_WORKER_ON_HOLD.value, (
        f"ON_HOLD must pre-empt cooling-off; got {body['data']['error_id']}"
    )


# ===========================================================================
# Queue A — boundary_precision_check / cooling_off_exactly_24h_allowed_on_approve
# ===========================================================================
def test_cooling_off_exactly_24h_allowed(api):
    """PRD §3.5: "The cooling-off interval must be satisfied — that is, the time elapsed from the
    worker's most recent disbursed advance's `disbursed_at` to the server clock must be at least
    the employer's `cooling_off_hours`, or there must be no prior disbursed advance at all — else
    `ERR_COOLING_OFF_ACTIVE`."

    adv1 disbursed at 2026-06-01T00:00Z; clock advanced to 2026-06-02T00:00Z (exactly 24h).
    Elapsed == cooling_off_hours satisfies ">= cooling_off_hours" so approving adv2 succeeds.

    Design: Difficulty/boundary_precision_check/cooling_off_exactly_24h_allowed_on_approve
    """
    employer = create_employer()
    create_standard_policy(employer["id"])
    create_fee_schedule(employer["id"])
    period = create_pay_period(employer["id"], start_at="2026-06-01T00:00:00Z", end_at="2026-06-15T00:00:00Z")
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-03T00:00:00Z", 16.0)
    post_time_entry(period["id"], worker["id"], "2026-06-04T08:00:00Z", "2026-06-05T00:00:00Z", 16.0)
    request_approve_disburse_advance(worker["id"], period["id"], 5000, disbursement_speed="STANDARD")

    set_clock("2026-06-02T00:00:00Z")  # exactly 24h after adv1 disbursed_at
    adv2 = request_advance(worker["id"], period["id"], 3000, disbursement_speed="STANDARD")
    approved = validate_success(api.approve_advance(adv2["id"], OFFICER))
    assert approved["status"] == "APPROVED", (
        f"elapsed exactly 24h satisfies >= cooling_off_hours; got {approved['status']}"
    )


def test_cooling_off_below_24h_rejected(api):
    """PRD §3.5: "The cooling-off interval must be satisfied — that is, the time elapsed from the
    worker's most recent disbursed advance's `disbursed_at` to the server clock must be at least
    the employer's `cooling_off_hours`, or there must be no prior disbursed advance at all — else
    `ERR_COOLING_OFF_ACTIVE`."

    Boundary X-1: adv1 disbursed at 00:00; clock advanced to 23:59 (< 24h) before approving adv2.
    Elapsed under cooling_off_hours => ERR_COOLING_OFF_ACTIVE.

    Design: Difficulty/boundary_precision_check/cooling_off_exactly_24h_allowed_on_approve
    """
    employer = create_employer()
    create_standard_policy(employer["id"])
    create_fee_schedule(employer["id"])
    period = create_pay_period(employer["id"], start_at="2026-06-01T00:00:00Z", end_at="2026-06-15T00:00:00Z")
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-03T00:00:00Z", 16.0)
    post_time_entry(period["id"], worker["id"], "2026-06-04T08:00:00Z", "2026-06-05T00:00:00Z", 16.0)
    request_approve_disburse_advance(worker["id"], period["id"], 5000, disbursement_speed="STANDARD")

    set_clock("2026-06-01T23:59:00Z")  # 23h59m < 24h
    adv2 = request_advance(worker["id"], period["id"], 3000, disbursement_speed="STANDARD")
    resp = api.approve_advance(adv2["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_COOLING_OFF_ACTIVE.value)


# ===========================================================================
# Queue A — boundary_precision_check / funding_exactly_equals_recoup_target_allows_disburse
# ===========================================================================
def test_funding_exactly_equals_recoup_target_allows_disburse(api):
    """PRD §3.8: "Disbursement requires the employer's `funding_balance_cents` to be at least the
    advance's `recoup_target_cents`, else `ERR_INSUFFICIENT_FUNDING`".
    PRD §3.8: "debits `funding_balance_cents` by `recoup_target_cents` to reserve principal and
    fee".

    Funding seeded to exactly 5000; STANDARD advance principal 5000 (rt 5000). funding ==
    recoup_target satisfies ">=" so disburse SUCCEEDS, leaving funding 0.

    Design: Difficulty/boundary_precision_check/funding_exactly_equals_recoup_target_allows_disburse
    """
    employer = create_employer(funding_balance_cents=5000)
    create_standard_policy(employer["id"])
    create_fee_schedule(employer["id"])
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T18:00:00Z", 10.0)
    adv = request_and_approve_advance(worker["id"], period["id"], 5000, disbursement_speed="STANDARD")

    disbursed = validate_success(api.disburse_advance(adv["id"], OFFICER))
    assert disbursed["status"] == "DISBURSED"
    emp = validate_success(api.get_employer(employer["id"], OFFICER))
    assert emp["funding_balance_cents"] == 0, f"funding must be 0 after debit; got {emp['funding_balance_cents']}"


def test_funding_one_cent_below_recoup_target_rejected(api):
    """PRD §3.8: "Disbursement requires the employer's `funding_balance_cents` to be at least the
    advance's `recoup_target_cents`, else `ERR_INSUFFICIENT_FUNDING`".

    Boundary X-1: funding 4999 < recoup_target 5000 => ERR_INSUFFICIENT_FUNDING (402).

    Design: Difficulty/boundary_precision_check/funding_exactly_equals_recoup_target_allows_disburse
    """
    employer = create_employer(funding_balance_cents=4999)
    create_standard_policy(employer["id"])
    create_fee_schedule(employer["id"])
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T18:00:00Z", 10.0)
    adv = request_and_approve_advance(worker["id"], period["id"], 5000, disbursement_speed="STANDARD")

    resp = api.disburse_advance(adv["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDING.value)


# ===========================================================================
# Queue A — cross_entity_state_dependency / advance_approve_requires_worker_eligible_advance_worker_pair
# ===========================================================================
def test_approve_blocked_by_worker_on_hold(api):
    """PRD §3.5: "The worker's `advance_eligibility` must be `ELIGIBLE`, else `ERR_WORKER_ON_HOLD`."
    PRD §3.2: "A worker is `ON_HOLD` exactly when they have at least one advance in the
    `DEFAULTED` or `WRITTEN_OFF` set".

    The Advance REQUESTED->APPROVED transition is gated by the cross-entity Worker.advance_eligibility:
    an ON_HOLD worker blocks approval even though the advance itself is in a valid from-state. The
    fixture advances the clock past cooling-off so only the ON_HOLD dependency can fire.

    Design: Difficulty/cross_entity_state_dependency/advance_approve_requires_worker_eligible_advance_worker_pair
    """
    employer, pp1, pp2, worker, adv1, adv2 = setup_worker_on_hold_via_writeoff()
    # Fixture leaves the clock at 2026-06-03 (cooling-off from 06-01 disbursement elapsed).
    assert validate_success(api.get_worker(worker["id"], OFFICER))["advance_eligibility"] == "ON_HOLD"

    resp = api.approve_advance(adv2["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_WORKER_ON_HOLD.value)


def test_eligible_worker_advance_in_valid_from_state_approves(api):
    """PRD §3.5: "A `PayrollOfficer` approves a requested advance, moving it `REQUESTED →
    APPROVED`."
    PRD §3.2: "The second dimension is `advance_eligibility`, defaulting to `ELIGIBLE`".

    Control half of the cross-entity pair: when the worker is ELIGIBLE and the advance is in the
    valid REQUESTED from-state, approval succeeds — confirming it was the ON_HOLD dependency, not
    the advance state, that blocked the negative case.

    Design: Difficulty/cross_entity_state_dependency/advance_approve_requires_worker_eligible_advance_worker_pair
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 5000)
    approved = validate_success(api.approve_advance(adv["id"], OFFICER))
    assert approved["status"] == "APPROVED"


# ===========================================================================
# Queue A — cross_entity_state_dependency / batch_post_requires_period_locked_batch_period_pair
# ===========================================================================
def test_batch_post_blocked_when_period_open(api):
    """PRD §3.8: "Posting carries several preconditions in addition to the global checks: the
    period must be `LOCKED`, else `ERR_PERIOD_NOT_LOCKED`".

    The RepaymentBatch DRAFT->POSTED transition is gated by the cross-entity PayPeriod.status: an
    OPEN (never-locked) period blocks the post.

    Design: Difficulty/cross_entity_state_dependency/batch_post_requires_period_locked_batch_period_pair
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])  # OPEN, never locked
    batch = open_batch(period["id"])
    b_v = validate_success(api.get_repayment_batch(batch["id"], OFFICER))["version"]

    resp = api.post_repayment_batch(batch["id"], {"expected_repaymentbatch_version": b_v}, POSTER)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_LOCKED.value)


def test_batch_post_succeeds_when_period_locked(api):
    """PRD §3.8: "Posting a batch, a `PayrollOfficer` action that moves it `DRAFT → POSTED`, runs
    the payday recoup waterfall described in Section 3.10 against the period's recoupable
    advances."
    PRD §3.8: "the period must be `LOCKED`, else `ERR_PERIOD_NOT_LOCKED`".

    Control half of the cross-entity pair: once the period is LOCKED, the same batch posts
    successfully — confirming the period-status dependency, not the batch state, drove the block.

    Design: Difficulty/cross_entity_state_dependency/batch_post_requires_period_locked_batch_period_pair
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    lock_period(period["id"])
    batch = open_batch(period["id"])
    b_v = validate_success(api.get_repayment_batch(batch["id"], OFFICER))["version"]

    posted = validate_success(api.post_repayment_batch(batch["id"], {"expected_repaymentbatch_version": b_v}, POSTER))
    assert posted["status"] == "POSTED"


# ===========================================================================
# Queue B — validations / below_floor_principal_returns_below_floor
# ===========================================================================
def test_below_floor_principal_returns_below_floor(api):
    """PRD §3.5: "after the principal clamp below is applied, the resulting `principal_cents` must
    be at least the matched tier's `per_advance_floor_cents`, else `ERR_BELOW_FLOOR`."

    Worker gross 1500 (0.75h @ 2000) => accessible floor(1500*0.5)=750; requested 5000 clamps to
    750 < floor 1000 => ERR_BELOW_FLOOR (422).

    Design: Corner/validations/below_floor_principal_returns_below_floor
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T08:45:00Z", 0.75)
    adv = request_advance(worker["id"], period["id"], 5000, disbursement_speed="STANDARD")

    resp = api.approve_advance(adv["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_BELOW_FLOOR.value)


# ===========================================================================
# Queue B — validations / period_cap_reached_on_fourth_advance
# ===========================================================================
def test_period_cap_reached(api):
    """PRD §3.5: "The worker's `period_advance_count` must be strictly less than the employer's
    `per_period_advance_cap_count`, else `ERR_PERIOD_CAP_REACHED`."

    Employer cap 2; two advances DISBURSED this period; clock advanced past cooling-off between
    each. Approving the 3rd advance (count 2 not < cap 2) => ERR_PERIOD_CAP_REACHED.

    Design: Corner/validations/period_cap_reached_on_fourth_advance
    """
    employer = create_employer(per_period_advance_cap_count=2)
    create_standard_policy(employer["id"])
    create_fee_schedule(employer["id"])
    period = create_pay_period(employer["id"], start_at="2026-06-01T00:00:00Z", end_at="2026-06-30T00:00:00Z")
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-03T00:00:00Z", 16.0)
    post_time_entry(period["id"], worker["id"], "2026-06-03T08:00:00Z", "2026-06-04T00:00:00Z", 16.0)

    request_approve_disburse_advance(worker["id"], period["id"], 3000, disbursement_speed="STANDARD")
    set_clock("2026-06-02T00:00:00Z")
    request_approve_disburse_advance(worker["id"], period["id"], 3000, disbursement_speed="STANDARD")
    set_clock("2026-06-03T00:00:00Z")
    adv3 = request_advance(worker["id"], period["id"], 3000, disbursement_speed="STANDARD")

    resp = api.approve_advance(adv3["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_PERIOD_CAP_REACHED.value)


# ===========================================================================
# Queue B — validations / time_entry_out_of_window_rejected
# ===========================================================================
def test_time_entry_out_of_window_rejected(api):
    """PRD §3.3: "The shift's `shift_start_at` is inclusive and must fall within the period's
    interval; `shift_end_at` is inclusive, must be strictly after `shift_start_at`, and must fall
    within the period; the period must be `OPEN`; and `hours_worked` must be greater than 0 and at
    most 24, and must equal the span between `shift_start_at` and `shift_end_at` measured in hours
    to within one hundredth of an hour. Any of these failing yields `ERR_TIME_ENTRY_OUT_OF_WINDOW`."

    Period 06-01..06-08; shift on 06-10 falls outside the interval.

    Design: Corner/validations/time_entry_out_of_window_rejected
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])

    resp = api.create_time_entry(
        {"pay_period_id": period["id"], "worker_id": worker["id"],
         "shift_start_at": "2026-06-10T08:00:00Z", "shift_end_at": "2026-06-10T12:00:00Z",
         "hours_worked": 4.0}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_TIME_ENTRY_OUT_OF_WINDOW.value)


# ===========================================================================
# Queue B — validations / over_recoup_amount_rejected
# ===========================================================================
def test_over_recoup_amount_rejected(api):
    """PRD §3.9: "That amount must be greater than 0 and at most the advance's
    `principal_outstanding_cents`, else `ERR_OVER_RECOUP`."

    DEFAULTED advance with 319 outstanding; manual-recoup 320 > 319 => ERR_OVER_RECOUP (422).

    Design: Corner/validations/over_recoup_amount_rejected
    """
    employer, period, worker, adv = setup_defaulted_advance_319()
    resp = api.manual_recoup_advance(adv["id"], {"amount_cents": 320}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_OVER_RECOUP.value)


# ===========================================================================
# Queue B — validations / insufficient_funding_blocks_disburse
# ===========================================================================
def test_insufficient_funding_blocks_disburse(api):
    """PRD §3.8: "Disbursement requires the employer's `funding_balance_cents` to be at least the
    advance's `recoup_target_cents`, else `ERR_INSUFFICIENT_FUNDING`".

    Funding 4999 < recoup_target 5000 => ERR_INSUFFICIENT_FUNDING (402).

    Design: Corner/validations/insufficient_funding_blocks_disburse
    """
    employer = create_employer(funding_balance_cents=4999)
    create_standard_policy(employer["id"])
    create_fee_schedule(employer["id"])
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T18:00:00Z", 10.0)
    adv = request_and_approve_advance(worker["id"], period["id"], 5000, disbursement_speed="STANDARD")

    resp = api.disburse_advance(adv["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDING.value)


# ===========================================================================
# Queue B — validations / sign_statement_not_clean_rejected
# ===========================================================================
def test_sign_statement_not_clean_rejected(api):
    """PRD §3.11: "Signing a statement is a `ComplianceOfficer` action that moves it `DRAFT →
    SIGNED`. Signing requires the period to be `DISBURSED`, else `ERR_PERIOD_NOT_DISBURSED`;
    requires segregation of duties ...; and requires the statement's `outcome` to be `CLEAN`,
    equivalently `drift_cents` equal to 0, else `ERR_STATEMENT_NOT_CLEAN`."

    Period DISBURSED with a DEFAULTED advance leaving drift 319 (DISCREPANCY); signing the DRAFT
    statement => ERR_STATEMENT_NOT_CLEAN.

    Design: Corner/validations/sign_statement_not_clean_rejected
    """
    employer, period, worker, adv = setup_defaulted_advance_319()
    stmt = validate_success(api.create_reconciliation_statement({"pay_period_id": period["id"]}, SIGNER))
    assert stmt["outcome"] == "DISCREPANCY", f"precondition: statement must be DISCREPANCY; got {stmt['outcome']}"

    resp = api.sign_reconciliation_statement(stmt["id"], SIGNER)
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_CLEAN.value)
