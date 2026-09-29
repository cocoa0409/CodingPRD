"""
Writes that are gated on the state of a different row.

An enrolment cannot exist under an employer that has not completed its mandate
registration, and a closure cannot be requested for an account whose money is
still in flight inside a portability transfer. Both gates are proved by issuing
the identical request twice: once while the other row blocks it and once after
that row has moved.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    ERR_ACCOUNT_RESTRICTED,
    ERR_EMPLOYER_NOT_REGISTERED,
    assert_amounts,
    assert_fields,
    assert_total_count,
    build_active_saver_environment,
    build_employer_environment,
    create_participant,
    fund_account_by_remittance,
    make_participant_headers,
    read_account,
    read_employer,
    read_enrollment,
    read_transfer,
    register_employer,
    request_transfer,
    return_transfer,
)

ENROLLMENT_PAYLOAD = {
    "participant_id": None,
    "hire_date": "2026-01-05",
    "annual_compensation_cents": 9600000,
}

CLOSURE_PAYLOAD = {
    "closure_reason": "ROLLOVER_OUT",
    "residual_disposition": "ROLLOVER_OUT",
}


def _enrollment_payload(participant_id):
    """The enrolment payload an employer is entitled to send, unchanged."""
    payload = dict(ENROLLMENT_PAYLOAD)
    payload["participant_id"] = participant_id
    return payload


def _unregistered_employer_and_saver(api):
    """
    Configuration, a covered 60-employee employer that has not registered, and
    one saver who is ready to be enrolled the moment it does.
    """
    env = build_employer_environment(api, register=False)
    saver = create_participant(api)
    env["participant_id"] = saver["id"]
    return env


def _account_with_a_transfer_in_flight(api):
    """
    A live saver whose account holds one posted payroll deduction of 400000 cents
    and whose money is partly out on an unsettled direct rollover.
    """
    env = build_active_saver_environment(api)
    env.update(fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        8000000, 400000, "2026-03-06T00:00:00Z"))
    transfer = request_transfer(
        api, env["participant_id"], env["account_id"], 100000,
        transfer_kind="DIRECT_ROLLOVER")
    env["transfer"] = transfer
    env["transfer_id"] = transfer["id"]
    return env


def test_enrolment_is_refused_while_the_employer_has_not_registered(api):
    """
    A perfectly formed enrolment against a covered employer still sitting in
    pending registration is refused, and nothing is persisted for that employer.

    "An enrolment attempt against an employer whose `registration_status` is
    anything other than `REGISTERED` is refused with
    `ERR_EMPLOYER_NOT_REGISTERED`: an employer sitting in
    `PENDING_REGISTRATION`, `EXEMPT_CERTIFIED` or `EXEMPT_SMALL` cannot enrol
    anyone."

    Design: Difficulty/cross_entity_state_dependency/enrollment_creation_gated_on_employer_registration_state
    """
    env = _unregistered_employer_and_saver(api)
    assert read_employer(api, env["employer_id"])["registration_status"] == (
        "PENDING_REGISTRATION")

    response = api.create_enrollment(
        env["employer_id"], _enrollment_payload(env["participant_id"]), ADMIN)

    validate_error(response, ERR_EMPLOYER_NOT_REGISTERED)
    assert_total_count(
        api.list_enrollments(ADMIN, {"employer_id": env["employer_id"]}), 0,
        label="enrolments of the unregistered employer")


def test_the_identical_enrolment_succeeds_once_the_employer_registers(api):
    """
    The same payload that was refused is accepted unchanged after the employer
    completes its own registration, and the enrolment opens at the programme
    default rate with a thirty-day notice deadline.

    "The employer supplies no rate at all: the new enrolment's
    `contribution_rate_bp` is seeded from the program year's
    `default_contribution_rate_bp` with `rate_source` set to `DEFAULT`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_creation_gated_on_employer_registration_state
    """
    env = _unregistered_employer_and_saver(api)
    payload = _enrollment_payload(env["participant_id"])
    validate_error(
        api.create_enrollment(env["employer_id"], payload, ADMIN),
        ERR_EMPLOYER_NOT_REGISTERED)

    register_employer(api, env["employer_id"])
    response = api.create_enrollment(env["employer_id"], payload, ADMIN)

    enrollment = validate_success(response, expected_status=201)
    assert_fields(enrollment, {
        "employer_id": env["employer_id"],
        "participant_id": env["participant_id"],
        "enrollment_status": "NOTIFIED",
        "contribution_rate_bp": 500,
        "rate_source": "DEFAULT",
        "opt_out_deadline": "2026-01-31",
    }, label="enrolment created after registration")
    assert_total_count(
        api.list_enrollments(ADMIN, {"employer_id": env["employer_id"]}), 1,
        label="enrolments of the registered employer")


def test_registration_alone_moves_the_gate_that_blocked_the_enrolment(api):
    """
    Nothing about the enrolment payload changes between the refusal and the
    acceptance: what changes is the employer's own mandate dimension, which the
    registration act moves and stamps.

    "On success the mandate dimension moves `PENDING_REGISTRATION → REGISTERED`,
    `non_fiduciary_acknowledged` is stored as true, `payroll_contact_email` is
    stored, `registered_at` is stamped from the logical clock, and the employer's
    `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/enrollment_creation_gated_on_employer_registration_state
    """
    env = _unregistered_employer_and_saver(api)
    before = read_employer(api, env["employer_id"])
    assert before["payroll_contact_email"] is None
    assert before["registered_at"] is None

    register_employer(api, env["employer_id"])

    after = read_employer(api, env["employer_id"])
    assert_fields(after, {
        "registration_status": "REGISTERED",
        "non_fiduciary_acknowledged": True,
    }, label="employer after registration")
    assert after["registered_at"] is not None
    assert after["version"] == before["version"] + 1
    created = validate_success(
        api.create_enrollment(
            env["employer_id"], _enrollment_payload(env["participant_id"]),
            ADMIN),
        expected_status=201)
    assert read_enrollment(api, created["id"])["enrollment_status"] == "NOTIFIED"


def test_closure_is_refused_while_a_transfer_out_of_the_account_is_unsettled(api):
    """
    Money sitting in an unsettled rollover restricts the account, and a closure
    request against it is refused as restricted rather than as closed.

    "The account's derived posture must be `UNRESTRICTED` and no portability
    transfer sourced from the account may still be in status `REQUESTED`; a
    request against a `RESTRICTED` or `LOCKED` account is refused with
    `ERR_ACCOUNT_RESTRICTED`, and a request against a `CLOSED` account with
    `ERR_ACCOUNT_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/account_closure_gated_on_in_flight_portability_transfer_state
    """
    env = _account_with_a_transfer_in_flight(api)

    response = api.request_account_closure(
        env["account_id"], dict(CLOSURE_PAYLOAD),
        make_participant_headers(env["participant_id"]))

    validate_error(response, ERR_ACCOUNT_RESTRICTED)
    account = read_account(api, env["account_id"])
    assert_fields(account, {
        "account_status": "OPEN",
        "posture": "RESTRICTED",
    }, label="account with a transfer in flight")
    transfer = read_transfer(api, env["transfer_id"])
    assert transfer["status"] == "REQUESTED"
    assert_amounts(transfer, {"in_transit_cents": 100000}, label="transfer")


def test_returning_the_transfer_reopens_the_account_for_closure(api):
    """
    The unblocking write is the compensating return of the same transfer: once
    the money is back in the account the identical closure request is accepted.

    "A return is a **full compensation**: the transfer moves
    `REQUESTED → RETURNED`, `in_transit_cents` is zeroed, the source account's
    `balance_cents` increases by the whole gross `amount_cents` and its
    `contribution_basis_cents` by `basis_portion_cents`, the `fee_cents` charge is
    reversed, the fund split is recomputed, the posture is re-derived and the
    account's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/account_closure_gated_on_in_flight_portability_transfer_state
    """
    env = _account_with_a_transfer_in_flight(api)
    validate_error(
        api.request_account_closure(
            env["account_id"], dict(CLOSURE_PAYLOAD),
            make_participant_headers(env["participant_id"])),
        ERR_ACCOUNT_RESTRICTED)

    return_transfer(api, env["transfer_id"],
                    "Receiving institution rejected the account registration")

    transfer = read_transfer(api, env["transfer_id"])
    assert transfer["status"] == "RETURNED"
    assert_amounts(transfer, {"in_transit_cents": 0}, label="returned transfer")
    restored = read_account(api, env["account_id"])
    assert restored["posture"] == "UNRESTRICTED"
    assert_amounts(restored, {
        "balance_cents": 400000,
        "contribution_basis_cents": 400000,
    }, label="account after the return")

    closed_pending = validate_success(api.request_account_closure(
        env["account_id"], dict(CLOSURE_PAYLOAD),
        make_participant_headers(env["participant_id"])))
    assert_fields(closed_pending, {
        "account_status": "CLOSURE_PENDING",
        "closure_reason": "ROLLOVER_OUT",
        "residual_disposition": "ROLLOVER_OUT",
        "posture": "LOCKED",
    }, label="account after the accepted closure request")


def test_the_in_flight_leg_debits_the_account_at_the_pinned_gross_amount(api):
    """
    The restriction is real money leaving the account: the request debits the
    whole gross amount and the pro-rata basis portion, while the fee, the taxable
    portion and the withholding are pinned on the transfer itself.

    "The source account is debited immediately: `balance_cents` falls by the gross
    `amount_cents` and `contribution_basis_cents` falls by `basis_portion_cents`,
    the fund split is recomputed, the account's posture is re-derived to
    `RESTRICTED` for as long as the transfer is in flight, and the account's
    `version` increments."

    Design: Difficulty/cross_entity_state_dependency/account_closure_gated_on_in_flight_portability_transfer_state
    """
    env = _account_with_a_transfer_in_flight(api)

    transfer = read_transfer(api, env["transfer_id"])

    assert_amounts(transfer, {
        "amount_cents": 100000,
        "fee_cents": 400,
        "basis_portion_cents": 100000,
        "taxable_cents": 0,
        "withholding_cents": 0,
        "net_cents": 99600,
        "in_transit_cents": 100000,
    }, label="direct rollover out of a fully contributed account")
    account = read_account(api, env["account_id"])
    assert_amounts(account, {
        "balance_cents": 300000,
        "contribution_basis_cents": 300000,
    }, label="account while the rollover is in flight")
    assert account["posture"] == "RESTRICTED"
