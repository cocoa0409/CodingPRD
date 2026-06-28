"""State machine behavior: cyclic charity vetting loop, payroll run-cycle self-loop, invalid
transitions, terminal-state lockdown, guarded transitions, and the void cascade
(PRD 3.1-3.8).
"""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_giving_scenario,
    create_active_program,
    create_approved_charity,
    create_employee,
    create_program,
    create_active_schedule,
    create_settled_donation,
    create_pledged_donation,
    create_open_batch,
    stage_grant,
    run_cycle,
    create_charity_payload,
)

PM = TEST_USERS["program_manager_headers"]
GA = TEST_USERS["giving_admin_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine
# ===========================================================================
def test_charity_vetting_revision_loop_increments_rounds(api):
    """PRD 3.3: "A charity in `NEEDS_INFO` can re-enter review — the revision loop — moving back
    to `UNDER_REVIEW` and again incrementing `review_rounds` by one, but this re-entry is
    permitted only while `review_rounds` is below 3."

    Design: Difficulty/non_linear_state_machine/charity_vetting_revision_loop
    """
    prog = create_active_program()
    charity = get_success_data(
        api.create_charity(create_charity_payload(prog["id"], legal_name="Loop", ein="77-7777777"), GA)
    )
    api.start_review_charity(charity["id"], GA)  # round 1 -> UNDER_REVIEW
    api.request_info_charity(charity["id"], GA)  # -> NEEDS_INFO

    looped = validate_success(api.start_review_charity(charity["id"], GA))  # round 2 -> UNDER_REVIEW
    assert looped["status"] == "UNDER_REVIEW"
    assert looped["review_rounds"] == 2


def test_charity_start_review_first_round_sets_rounds_one(api):
    """PRD 3.3: "Starting a review moves a charity from `SUBMITTED` to `UNDER_REVIEW` and
    increments `review_rounds` by one."

    Design: Difficulty/non_linear_state_machine/charity_vetting_revision_loop
    """
    prog = create_active_program()
    charity = get_success_data(
        api.create_charity(create_charity_payload(prog["id"], legal_name="Loop2", ein="77-7777778"), GA)
    )
    reviewed = validate_success(api.start_review_charity(charity["id"], GA))
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["review_rounds"] == 1


def test_schedule_run_cycle_self_loop_stays_active(api):
    """PRD 3.5: "Running a cycle on a schedule is an administrative action that keeps the schedule
    in `ACTIVE` (a self-loop) while generating one occurrence ... A successful run-cycle creates
    one new `Donation` in `PLEDGED` status for that employee and campaign with `donation_type` of
    `RECURRING`, `funding_method` of `PAYROLL_DEDUCTION`, `base_amount_cents` equal to the
    schedule's `per_period_amount_cents`, and `schedule_id` set to this schedule, then increments
    the schedule's `occurrences_generated` by one."

    Design: Difficulty/non_linear_state_machine/schedule_runcycle_self_loop
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    sched = create_active_schedule(s, per_period_amount_cents=15000)
    run_cycle(sched["id"])  # first occurrence

    occ = validate_success(api.run_cycle_payroll_schedule(sched["id"], GA), expected_status=201)
    assert occ["donation_type"] == "RECURRING"
    assert occ["schedule_id"] == sched["id"]
    assert occ["base_amount_cents"] == 15000

    after = validate_success(api.get_payroll_schedule(sched["id"], GA))
    assert after["status"] == "ACTIVE"
    assert after["occurrences_generated"] == 2


def test_schedule_run_cycle_mints_recurring_donation_amount(api):
    """PRD 3.5: "A successful run-cycle creates one new `Donation` in `PLEDGED` status for that
    employee and campaign with `donation_type` of `RECURRING`, `funding_method` of
    `PAYROLL_DEDUCTION`, `base_amount_cents` equal to the schedule's `per_period_amount_cents`,
    and `schedule_id` set to this schedule."

    Design: Difficulty/non_linear_state_machine/schedule_runcycle_self_loop
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    sched = create_active_schedule(s, per_period_amount_cents=15000)
    occ = validate_success(api.run_cycle_payroll_schedule(sched["id"], GA), expected_status=201)
    assert occ["status"] == "PLEDGED"
    assert occ["funding_method"] == "PAYROLL_DEDUCTION"
    assert occ["base_amount_cents"] == 15000


# ===========================================================================
# Corner / state_machines
# ===========================================================================
def test_charity_approve_from_submitted_invalid_state(api):
    """PRD 3.3: "Each of these transitions requires the charity to be in the precise originating
    state named, failing otherwise with `ERR_INVALID_STATE`."
    PRD 3.3: "From `UNDER_REVIEW`, a charity may be approved or rejected."

    Design: Corner/state_machines/charity_approve_from_submitted_invalid_state
    """
    prog = create_program()
    charity = get_success_data(
        api.create_charity(create_charity_payload(prog["id"], legal_name="S", ein="34-3434343"), GA)
    )
    resp = api.approve_charity(charity["id"], GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_charity(charity["id"], GA))
    assert after["status"] == "SUBMITTED"


def test_charity_reject_is_terminal(api):
    """PRD 3.3: "Rejection moves the charity to the terminal `REJECTED` state and may be performed
    from either `UNDER_REVIEW` or `NEEDS_INFO`."
    PRD 3.3: "Each of these transitions requires the charity to be in the precise originating
    state named, failing otherwise with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/charity_reject_is_terminal_no_further_transition
    """
    prog = create_program()
    charity = get_success_data(
        api.create_charity(create_charity_payload(prog["id"], legal_name="R", ein="35-3535353"), GA)
    )
    api.start_review_charity(charity["id"], GA)
    api.reject_charity(charity["id"], GA)

    resp = api.start_review_charity(charity["id"], GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_charity(charity["id"], GA))
    assert after["status"] == "REJECTED"


def test_charity_review_rounds_bound_exceeded(api):
    """PRD 3.3: "once `review_rounds` has reached 3, a further attempt to restart review from
    `NEEDS_INFO` is rejected with `ERR_MAX_REVIEW_ROUNDS`."

    Design: Corner/state_machines/charity_review_rounds_bound_exceeded
    """
    prog = create_active_program()
    charity = get_success_data(
        api.create_charity(create_charity_payload(prog["id"], legal_name="Loop3", ein="36-3636363"), GA)
    )
    # Cycle review until review_rounds == 3 and we are back in NEEDS_INFO.
    for _ in range(3):
        api.start_review_charity(charity["id"], GA)
        api.request_info_charity(charity["id"], GA)

    resp = api.start_review_charity(charity["id"], GA)
    validate_error(resp, ApiErrorId.ERR_MAX_REVIEW_ROUNDS.value)

    after = validate_success(api.get_charity(charity["id"], GA))
    assert after["review_rounds"] == 3


def test_donation_settle_twice_rejected(api):
    """PRD 3.5: "Settling an authorized donation is an administrative action permitted only when
    the donation is `AUTHORIZED` (else `ERR_INVALID_STATE`) and its campaign is `LIVE` (else
    `ERR_CAMPAIGN_NOT_LIVE`)."

    Design: Corner/state_machines/donation_settle_twice_idempotency_rejected
    """
    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    resp = api.settle_donation(don["id"], GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_donation_authorize_blocked_when_employee_not_active(api):
    """PRD 3.5: "Authorizing a pledged donation is an administrative action permitted only when
    the donation is `PLEDGED` (else `ERR_INVALID_STATE`) and the donor employee is `ACTIVE` (else
    `ERR_EMPLOYEE_NOT_ACTIVE`)."

    Design: Corner/state_machines/donation_authorize_blocked_when_employee_not_active
    """
    s = setup_giving_scenario()
    don = create_pledged_donation(s, base_amount_cents=5000)
    api.suspend_employee(s["employee"]["id"], GA)

    resp = api.authorize_donation(don["id"], GA)
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE.value)


def test_program_close_blocked_with_open_batch(api):
    """PRD 3.1: "closing is permitted only while the program is `ACTIVE`, and only when no
    `DisbursementBatch` under the program is in either `OPEN` or `LOCKED` status — an outstanding
    open or locked batch blocks the close with `ERR_OPEN_BATCH_EXISTS`."

    Design: Corner/state_machines/program_close_blocked_with_open_batch
    """
    prog = create_active_program()
    charity = create_approved_charity(prog["id"], legal_name="C", ein="39-3939393")
    create_open_batch(prog["id"], charity["id"])

    resp = api.close_program(prog["id"], PM)
    validate_error(resp, ApiErrorId.ERR_OPEN_BATCH_EXISTS.value)

    after = validate_success(api.get_program(prog["id"], PM))
    assert after["status"] == "ACTIVE"


def test_refund_blocked_when_donation_disbursed(api):
    """PRD 3.5: "a donation whose grant has been staged or settled cannot be refunded and is
    rejected with `ERR_DONATION_DISBURSED`."

    Design: Corner/state_machines/refund_blocked_when_donation_disbursed
    """
    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])
    stage_grant(batch["id"], "DONATION", don["id"], batch["version"])

    resp = api.refund_donation(don["id"], GA)
    validate_error(resp, ApiErrorId.ERR_DONATION_DISBURSED.value)


# ===========================================================================
# Difficulty / boundary_precision_check (empty batch)
# ===========================================================================
def test_empty_batch_lock_rejected(api):
    """PRD 3.8: "Locking a batch freezes its staged set, moving it from `OPEN` to `LOCKED`,
    permitted only when the batch is `OPEN` (else `ERR_INVALID_STATE`) and the batch holds at
    least one grant in `STAGED` (else `ERR_EMPTY_BATCH`)."

    Design: Difficulty/boundary_precision_check/empty_batch_lock_rejected
    """
    prog = create_active_program()
    charity = create_approved_charity(prog["id"], legal_name="Emp", ein="14-1414141")
    batch = create_open_batch(prog["id"], charity["id"])  # zero staged grants

    resp = api.lock_disbursement_batch(batch["id"], GA)
    validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH.value)

    after = validate_success(api.get_disbursement_batch(batch["id"], GA))
    assert after["status"] == "OPEN"


def test_batch_with_one_staged_grant_locks_successfully(api):
    """PRD 3.8: "Locking a batch freezes its staged set, moving it from `OPEN` to `LOCKED`,
    permitted only when the batch is `OPEN` (else `ERR_INVALID_STATE`) and the batch holds at
    least one grant in `STAGED` (else `ERR_EMPTY_BATCH`)."

    Design: Difficulty/boundary_precision_check/empty_batch_lock_rejected
    """
    # The boundary's other side: exactly one staged grant makes the lock succeed.
    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])
    stage_grant(batch["id"], "DONATION", don["id"], batch["version"])

    locked = validate_success(api.lock_disbursement_batch(batch["id"], GA))
    assert locked["status"] == "LOCKED"


# ===========================================================================
# Corner / errors (void cascade)
# ===========================================================================
def test_batch_void_voids_staged_grant(api):
    """PRD 3.8: "An open batch may instead be voided, moving it from `OPEN` to the terminal
    `VOIDED` state, which transitions every `STAGED` grant in it to `VOIDED` (excluding those
    grants from any future settlement) and increments the batch's `version`."

    Design: Corner/errors/batch_void_voids_staged_grant
    """
    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])
    grant = stage_grant(batch["id"], "DONATION", don["id"], batch["version"])

    voided = validate_success(api.void_disbursement_batch(batch["id"], GA))
    assert voided["status"] == "VOIDED"

    grant_after = validate_success(api.get_grant(grant["id"], GA))
    assert grant_after["status"] == "VOIDED"


# ===========================================================================
# Corner / endpoints (grants subresource listing)
# ===========================================================================
def test_grants_subresource_list_reverse_reachability(api):
    """PRD 4: "| GET | `/disbursement-batches/{batchId}/grants` | List grants in a batch |"
    PRD 2.3: "every list endpoint returns its resources sorted by their creation timestamp
    (`created_at`) in ascending order."

    Design: Corner/endpoints/grants_subresource_list_reverse_reachability
    """
    s = setup_giving_scenario()
    don = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])
    grant = stage_grant(batch["id"], "DONATION", don["id"], batch["version"])

    resp = api.list_batch_grants(batch["id"], GA)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    assert any(g["id"] == grant["id"] for g in data)
