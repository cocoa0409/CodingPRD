"""Lease and truck lifecycle: initial state, default/cure, termination, return."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_operator, create_truck, create_active_lease,
    set_clock, get_escrow_for_lease,
    setup_lease_with_missed_payments, setup_defaulted_lease,
    create_lease_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


# ─── Queue B: corner/state_machines ──────────────────

def test_lease_initial_state_and_escrow_auto_creation(api):
    """PRD section 3.3: "A new lease is born in `APPLICATION` status with three
    counters at zero — `missed_payment_count`, `arrears_cents`,
    `total_payments_applied_cents` — and the `escrow_satisfied` flag `false`. In
    the same transaction the system creates the lease's companion `EscrowAccount`
    (one per lease, pointing back via its `lease_id`), starting in `ACCUMULATING`
    with `balance_cents`, `total_credited_cents`, `total_refunded_cents`, and
    `total_applied_cents` all zero."

    Design: Corner/state_machines/lease_initial_state_and_escrow_auto_creation
    """
    operator = create_operator()
    truck = create_truck()
    lease = validate_success(
        api.create_lease_agreement(
            create_lease_payload(operator["id"], truck["id"]), ADMIN), 201)
    assert lease["status"] == "APPLICATION"
    assert lease["missed_payment_count"] == 0
    assert lease["arrears_cents"] == 0
    assert lease["total_payments_applied_cents"] == 0
    assert lease["escrow_satisfied"] is False

    escrow = get_escrow_for_lease(lease["id"])
    assert escrow["lease_id"] == lease["id"]
    assert escrow["status"] == "ACCUMULATING"
    assert escrow["balance_cents"] == 0
    assert escrow["total_credited_cents"] == 0
    assert escrow["total_refunded_cents"] == 0
    assert escrow["total_applied_cents"] == 0


def test_lease_cure_from_active_rejected(api):
    """PRD section 3.7: "A `LeaseAdmin` cures a `DEFAULTED` lease (wrong state:
    `ERR_LEASE_NOT_DEFAULTED`) by submitting an `arrears_payment_cents` amount".

    Design: Corner/state_machines/lease_cure_from_active_rejected
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]

    res = api.cure_default(lease_id, {"arrears_payment_cents": 100}, ADMIN)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_DEFAULTED.value)

    after = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert after["status"] == "ACTIVE", "rejected cure changes nothing"


def test_lease_complete_before_term_rejected(api):
    """PRD section 3.7: "A `LeaseAdmin` completes an `ACTIVE` lease (wrong state:
    `ERR_LEASE_NOT_ACTIVE`) once the logical clock has reached the term end — the
    start date plus the term in weeks times seven days — failing with
    `ERR_LEASE_TERM_NOT_REACHED` before that."

    Design: Corner/state_machines/lease_complete_before_term_rejected
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-12T00:00:00Z")

    res = api.complete_lease(lease_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_LEASE_TERM_NOT_REACHED.value)

    after = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert after["status"] == "ACTIVE", "rejected completion changes nothing"


def test_lease_terminate_terminal_rejected(api):
    """PRD section 3.7: "Termination is the hard exit, available from
    `APPLICATION`, `ACTIVE`, or `DEFAULTED` (terminating a lease already
    `COMPLETED` or `TERMINATED` fails with `ERR_LEASE_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/lease_terminate_terminal_rejected
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    validate_success(api.terminate_lease(lease_id, ADMIN), 200)

    res = api.terminate_lease(lease_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_LEASE_ALREADY_TERMINAL.value)

    after = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert after["status"] == "TERMINATED"


def test_escrow_disburse_not_pending_rejected(api):
    """PRD section 3.7: "A `SettlementClerk` then disburses a `REFUND_PENDING`
    escrow: the full `balance_cents` is added to `total_refunded_cents`, the
    balance zeroes, and the account moves to `REFUNDED` (disbursing an account
    not in `REFUND_PENDING` fails with `ERR_ESCROW_NOT_REFUNDABLE`)."

    Design: Corner/state_machines/escrow_disburse_not_pending_rejected
    """
    scenario = create_active_lease()
    escrow = scenario["escrow"]
    assert escrow["status"] == "ACCUMULATING"

    res = api.disburse_escrow(escrow["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_ESCROW_NOT_REFUNDABLE.value)

    after = validate_success(api.get_escrow_account(escrow["id"], CLERK), 200)
    assert after["status"] == "ACCUMULATING", "rejected disbursement changes nothing"


def test_truck_relist_cycle_available_leased_returned_available(api):
    """PRD section 3.1: "activation moves `AVAILABLE` → `LEASED`; termination or
    completion moves `LEASED` → `IN_RETURN`; a `LeaseAdmin` confirming physical
    return moves `IN_RETURN` → `RETURNED` (a confirm-return attempt on a truck
    not in `IN_RETURN` is rejected with `ERR_TRUCK_NOT_IN_RETURN`); and relisting
    moves `RETURNED` → `AVAILABLE` for the next lessee (relisting a truck not in
    `RETURNED` fails with `ERR_TRUCK_NOT_RETURNED`)."

    Design: Corner/state_machines/truck_relist_cycle_available_leased_returned_available
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    truck_id = scenario["truck"]["id"]
    assert scenario["truck"]["status"] == "AVAILABLE"
    assert validate_success(api.get_truck(truck_id, ADMIN), 200)["status"] == "LEASED"

    validate_success(api.terminate_lease(lease_id, ADMIN), 200)
    truck = validate_success(api.get_truck(truck_id, ADMIN), 200)
    assert truck["status"] == "IN_RETURN"

    validate_success(api.confirm_truck_return(truck_id, ADMIN), 200)
    truck = validate_success(api.get_truck(truck_id, ADMIN), 200)
    assert truck["status"] == "RETURNED"

    validate_success(api.relist_truck(truck_id, ADMIN), 200)
    truck = validate_success(api.get_truck(truck_id, ADMIN), 200)
    assert truck["status"] == "AVAILABLE", "truck cycle closes back at AVAILABLE"

    lease = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert lease["status"] == "TERMINATED"


def test_truck_return_relist_wrong_state_rejected(api):
    """PRD section 3.1: "a `LeaseAdmin` confirming physical return moves
    `IN_RETURN` → `RETURNED` (a confirm-return attempt on a truck not in
    `IN_RETURN` is rejected with `ERR_TRUCK_NOT_IN_RETURN`); and relisting moves
    `RETURNED` → `AVAILABLE` for the next lessee (relisting a truck not in
    `RETURNED` fails with `ERR_TRUCK_NOT_RETURNED`)."

    Design: Corner/state_machines/truck_return_relist_wrong_state_rejected
    """
    truck = create_truck()
    assert truck["status"] == "AVAILABLE"

    res1 = api.confirm_truck_return(truck["id"], ADMIN)
    validate_error(res1, ApiErrorId.ERR_TRUCK_NOT_IN_RETURN.value)
    res2 = api.relist_truck(truck["id"], ADMIN)
    validate_error(res2, ApiErrorId.ERR_TRUCK_NOT_RETURNED.value)

    after = validate_success(api.get_truck(truck["id"], ADMIN), 200)
    assert after["status"] == "AVAILABLE", "both rejections leave the truck untouched"


# ─── Queue A: difficulty/non_linear_state_machine ────

def test_lease_default_then_cure_closes_cycle(api):
    """PRD section 3.7: "a `LeaseAdmin` declares default on an `ACTIVE` lease
    (wrong state: `ERR_LEASE_NOT_ACTIVE`) whose `missed_payment_count` has
    reached at least three (otherwise `ERR_LEASE_NOT_DEFAULT_ELIGIBLE`), moving
    `ACTIVE` → `DEFAULTED`." PRD section 3.7: "On success the lease returns
    `DEFAULTED` → `ACTIVE`, `arrears_cents` and `missed_payment_count` reset to
    zero, and any overpayment — the amount paid beyond the arrears — flows into
    escrow: the escrow balance rises by the overpayment, truncated at the lease's
    `escrow_cap_cents`, with `total_credited_cents` growing by the credited
    portion."

    Design: Difficulty/non_linear_state_machine/lease_default_cure_cycle
    """
    scenario = setup_lease_with_missed_payments(3)
    lease_id = scenario["lease"]["id"]
    assert scenario["lease"]["missed_payment_count"] == 3
    assert scenario["lease"]["arrears_cents"] == 195000

    defaulted = validate_success(api.declare_default(lease_id, ADMIN), 200)
    assert defaulted["status"] == "DEFAULTED"

    cured = validate_success(
        api.cure_default(lease_id, {"arrears_payment_cents": 195000}, ADMIN), 200)
    assert cured["status"] == "ACTIVE", "cure closes the ACTIVE->DEFAULTED->ACTIVE cycle"
    assert cured["arrears_cents"] == 0
    assert cured["missed_payment_count"] == 0


def test_declare_default_after_cure_rejected_until_fresh_threshold(api):
    """PRD section 3.7: "a `LeaseAdmin` declares default on an `ACTIVE` lease
    (wrong state: `ERR_LEASE_NOT_ACTIVE`) whose `missed_payment_count` has
    reached at least three (otherwise `ERR_LEASE_NOT_DEFAULT_ELIGIBLE`), moving
    `ACTIVE` → `DEFAULTED`." PRD section 3.7: "On success the lease returns
    `DEFAULTED` → `ACTIVE`, `arrears_cents` and `missed_payment_count` reset to
    zero".

    Design: Difficulty/non_linear_state_machine/lease_default_cure_cycle
    """
    scenario = setup_defaulted_lease()
    lease_id = scenario["lease"]["id"]
    validate_success(
        api.cure_default(lease_id, {"arrears_payment_cents": 195000}, ADMIN), 200)

    res = api.declare_default(lease_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_DEFAULT_ELIGIBLE.value)

    after = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert after["status"] == "ACTIVE"
    assert after["missed_payment_count"] == 0, "cure reset the counter"
