"""State-machine tests: advance lifecycle (incl. DEFAULTED write-back loop), pay-period
cyclic OPEN<->LOCKED, terminal lockdowns, guarded transitions, precondition violations.

Queue A (Difficulty): non_linear_state_machine.
Queue B (Corner): state_machines.* instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_employer,
    create_standard_policy,
    create_fee_schedule,
    create_pay_period,
    create_worker,
    post_shift_6h_gross_12000,
    post_shift_10h_gross_20000,
    setup_base_scenario,
    setup_defaulted_advance_319,
    request_advance,
    request_and_approve_advance,
    request_approve_disburse_advance,
    lock_period,
    open_batch,
    post_batch,
    lock_and_post_batch,
    run_payday,
)

OFFICER = TEST_USERS["payroll_officer_headers"]
POSTER = TEST_USERS["payroll_poster_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine / advance_defaulted_to_recouping_writeback_loop
# ===========================================================================
def test_advance_defaulted_manual_recoup_to_settled(api):
    """PRD §3.9: "A `PayrollOfficer` performs a manual recovery on a `DEFAULTED` advance, moving
    it `DEFAULTED → RECOUPING`, by supplying an `amount_cents`."
    PRD §3.9: "If outstanding reaches 0, the advance proceeds on through the settlement path
    described above."
    PRD §3.9: "This is a system transition, `RECOUPING → SETTLED`, gated on outstanding reaching
    exactly 0."

    A DEFAULTED advance with 319 outstanding, recovered via manual-recoup of 319, re-enters
    RECOUPING and then reaches SETTLED (the non-linear write-back loop).

    Design: Difficulty/non_linear_state_machine/advance_defaulted_to_recouping_writeback_loop
    """
    employer, period, worker, adv = setup_defaulted_advance_319()
    pre = validate_success(api.get_advance(adv["id"], OFFICER))
    assert pre["status"] == "DEFAULTED", f"precondition: advance must be DEFAULTED; got {pre['status']}"

    recovered = validate_success(api.manual_recoup_advance(adv["id"], {"amount_cents": 319}, OFFICER))
    assert recovered["status"] == "SETTLED", (
        f"DEFAULTED -> RECOUPING -> SETTLED after recovering final 319; got {recovered['status']}"
    )


def test_advance_defaulted_manual_recoup_drives_outstanding_to_zero(api):
    """PRD §3.9: "A successful recovery creates a `Repayment` row tied to the period's
    posted-or-prior batch, adds the amount to `amount_recouped_cents`, subtracts it from
    `principal_outstanding_cents`, and recomputes the period's statement `drift_cents` to reflect
    the write-back."

    Recovering the full 319 drives principal_outstanding_cents to 0 on the re-entered advance.

    Design: Difficulty/non_linear_state_machine/advance_defaulted_to_recouping_writeback_loop
    """
    employer, period, worker, adv = setup_defaulted_advance_319()
    recovered = validate_success(api.manual_recoup_advance(adv["id"], {"amount_cents": 319}, OFFICER))
    assert recovered["principal_outstanding_cents"] == 0, (
        f"outstanding must reach 0 after recovering 319; got {recovered['principal_outstanding_cents']}"
    )


# ===========================================================================
# Queue A — non_linear_state_machine / pay_period_cyclic_open_locked_reopen
# ===========================================================================
def test_pay_period_reopen_returns_to_open(api):
    """PRD §3.3: "A period's `status` flows `OPEN → LOCKED → DISBURSED`, with a cyclic reopen
    loop allowing `LOCKED → OPEN`".
    PRD §3.3: "Reopening, also by a `PayrollOfficer`, moves `LOCKED → OPEN` to allow late
    time-entry corrections".

    OPEN -> LOCKED -> OPEN: the cyclic loop returns the period to a prior state.

    Design: Difficulty/non_linear_state_machine/pay_period_cyclic_open_locked_reopen
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    locked = validate_success(api.lock_pay_period(period["id"], OFFICER))
    assert locked["status"] == "LOCKED"

    reopened = validate_success(api.reopen_pay_period(period["id"], OFFICER))
    assert reopened["status"] == "OPEN", f"reopen must return to OPEN; got {reopened['status']}"


def test_pay_period_reopen_clears_locked_at(api):
    """PRD §3.3: "Locking, performed by a `PayrollOfficer`, freezes the time feed: it requires
    the employer's posture not to be `FROZEN` (otherwise `ERR_EMPLOYER_FROZEN`), stamps
    `locked_at` with the server clock, and recomputes the period's `gross_accrued_cents` over its
    posted time entries."
    PRD §3.3: "on success it clears `locked_at` back to null."

    locked_at is set on lock then cleared to null on reopen.

    Design: Difficulty/non_linear_state_machine/pay_period_cyclic_open_locked_reopen
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    locked = validate_success(api.lock_pay_period(period["id"], OFFICER))
    assert locked["locked_at"] is not None, "locked_at must be set on lock"

    reopened = validate_success(api.reopen_pay_period(period["id"], OFFICER))
    assert reopened["locked_at"] is None, f"locked_at must be null after reopen; got {reopened['locked_at']}"


# ===========================================================================
# Queue B — state_machines / advance_initial_state_is_requested
# ===========================================================================
def test_advance_initial_state_is_requested(api):
    """PRD §3.5: "On creation the advance takes its `employer_id` from the worker, stamps
    `requested_at` with the server clock, sets `status` to `REQUESTED`, and increments the target
    worker's `version` by one."

    Design: Corner/state_machines/advance_initial_state_is_requested
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 5000)
    assert adv["status"] == "REQUESTED", f"new advance must start REQUESTED; got {adv['status']}"


# ===========================================================================
# Queue B — state_machines / disburse_from_requested_returns_invalid_state
# ===========================================================================
def test_disburse_from_requested_returns_invalid_state(api):
    """PRD §3.8: "Once an advance is `APPROVED`, a `PayrollOfficer` disburses it, moving it
    `APPROVED → DISBURSED`."
    PRD §2.11: "State legality — whether the requested transition is defined from the target's
    current state — is checked sixth, yielding `ERR_INVALID_STATE`."

    Disburse on a REQUESTED (not APPROVED) advance has no defined from-state => ERR_INVALID_STATE.

    Design: Corner/state_machines/disburse_from_requested_returns_invalid_state
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 5000)

    resp = api.disburse_advance(adv["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — state_machines / declined_advance_terminal_lockdown
# ===========================================================================
def test_declined_advance_second_decline_returns_invalid_state(api):
    """PRD §3.5: "An advance's `status` flows `REQUESTED → APPROVED → DISBURSED → RECOUPING →
    SETTLED` along the happy path, with `SETTLED`, `DECLINED`, and `WRITTEN_OFF` as terminal
    states".
    PRD §2.11: "State legality — whether the requested transition is defined from the target's
    current state — is checked sixth, yielding `ERR_INVALID_STATE`."

    A second decline on a DECLINED (terminal) advance has no defined from-state.

    Design: Corner/state_machines/declined_advance_terminal_lockdown
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 5000)
    get_success_data(api.decline_advance(adv["id"], OFFICER))

    resp = api.decline_advance(adv["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — state_machines / reopen_blocked_when_batch_posted
# ===========================================================================
def test_reopen_blocked_when_batch_posted(api):
    """PRD §3.3: "Reopening, also by a `PayrollOfficer`, moves `LOCKED → OPEN` to allow late
    time-entry corrections; it is blocked when any repayment batch for the period is already
    posted or reconciled, in which case it is rejected with `ERR_PERIOD_HAS_POSTED_BATCH`".

    Design: Corner/state_machines/reopen_blocked_when_batch_posted
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    lock_and_post_batch(period["id"])

    resp = api.reopen_pay_period(period["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_PERIOD_HAS_POSTED_BATCH.value)


# ===========================================================================
# Queue B — state_machines / run_payday_without_posted_batch_returns_no_posted_batch
# ===========================================================================
def test_run_payday_without_posted_batch_returns_no_posted_batch(api):
    """PRD §3.8: "Running payday is the period's closing act, a `PayrollOfficer` transition that
    moves the period `LOCKED → DISBURSED`. It requires exactly one batch for the period to be in
    `POSTED` status, else `ERR_NO_POSTED_BATCH`".

    Design: Corner/state_machines/run_payday_without_posted_batch_returns_no_posted_batch
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    lock_period(period["id"])

    resp = api.run_payday(period["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_NO_POSTED_BATCH.value)


# ===========================================================================
# Queue B — state_machines / second_batch_post_returns_batch_already_posted
# ===========================================================================
def test_second_batch_post_returns_batch_already_posted(api):
    """PRD §3.8: "no other batch for the period may already be `POSTED` or `RECONCILED`, else
    `ERR_BATCH_ALREADY_POSTED`".

    Design: Corner/state_machines/second_batch_post_returns_batch_already_posted
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    lock_period(period["id"])
    batch1 = open_batch(period["id"])
    post_batch(batch1["id"])
    batch2 = open_batch(period["id"])
    b2_v = validate_success(api.get_repayment_batch(batch2["id"], OFFICER))["version"]

    resp = api.post_repayment_batch(batch2["id"], {"expected_repaymentbatch_version": b2_v}, POSTER)
    validate_error(resp, ApiErrorId.ERR_BATCH_ALREADY_POSTED.value)


# ===========================================================================
# Queue B — state_machines / worker_terminate_blocked_with_open_advance
# ===========================================================================
def test_worker_terminate_blocked_with_open_advance(api):
    """PRD §3.2: "Termination is blocked while the worker still has any advance in the
    `DISBURSED`, `RECOUPING`, or `DEFAULTED` state, in which case the request is rejected with
    `ERR_WORKER_HAS_OPEN_ADVANCE`."

    Design: Corner/state_machines/worker_terminate_blocked_with_open_advance
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    request_approve_disburse_advance(worker["id"], period["id"], 5000)

    resp = api.terminate_worker(worker["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_WORKER_HAS_OPEN_ADVANCE.value)


# ===========================================================================
# Queue B — state_machines / approve_suspended_worker_returns_worker_not_active
# ===========================================================================
def test_approve_suspended_worker_returns_worker_not_active(api):
    """PRD §3.5: "The worker's `employment_status` must be `ACTIVE`, else `ERR_WORKER_NOT_ACTIVE`."
    PRD §3.2: "Suspension blocks new advance approvals but does not touch the second dimension."

    Design: Corner/state_machines/approve_suspended_worker_returns_worker_not_active
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 5000)
    get_success_data(api.suspend_worker(worker["id"], OFFICER))

    resp = api.approve_advance(adv["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_WORKER_NOT_ACTIVE.value)
