"""Which refusal the caller hears when two submit gates fail on the same call.

The program fixes a single evaluation order for its checks, so a rebuilder who is
simultaneously under a fraud referral and out of money hears about the fraud
referral, and a rebuilder who resubmits an already-submitted package after the
180-day window has closed hears about the status, not about the window.
"""

from test_helpers import (
    api_client,
    make_rebuilder_headers,
    read_application,
    read_rebuilder,
    read_vehicle,
    set_clock,
    setup_submission_ready_application,
    setup_submitted_application,
    submit_application_payload,
    validate_error,
)
from test_helpers.fixtures import open_fraud_referral

SEDAN_PROGRAM_CHARGE_CENTS = 20000
DEPOSIT_CENTS = 500000
PAST_THE_SUBMISSION_WINDOW = "2027-03-01T00:00:00Z"
LATE_LICENSE_EXPIRY = "2028-06-30T00:00:00Z"


def _submit(application_id: str, rebuilder_id: str):
    """Raw submit call, so the refusal envelope can be inspected."""
    return api_client.submit_application(
        application_id,
        submit_application_payload(),
        make_rebuilder_headers(rebuilder_id),
    )


# ===========================================================================
# fraud hold outranks an empty fee balance on submit
# ===========================================================================
def test_fraud_referral_outranks_the_empty_fee_balance_on_submit():
    """A broke rebuilder whose vehicle is under a fraud referral hears about the referral.

    PRD: "The practical consequence worth internalising is that a fraud hold on the vehicle surfaces before any licence, credential, capacity, window or fiscal problem, and that the fiscal checks are always the last to speak — a caller who is both broke and scheduling into an occupied bay hears about the bay."

    Design: Difficulty/priority_pair_validation_conflict/fraud_hold_outranks_insufficient_fee_balance_on_submit
    """
    env = setup_submission_ready_application(deposit_cents=0)
    open_fraud_referral(env["vehicle_id"], application_id=env["application_id"])

    # Both failing conditions genuinely stand on the same call: the vehicle is held,
    # and the balance cannot cover even the 7,500-cent base application fee.
    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["fraud_hold"] == "UNDER_REFERRAL", (
        f"expected fraud_hold UNDER_REFERRAL, got {vehicle['fraud_hold']} after the referral"
    )
    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fee_balance_cents"] == 0, (
        f"expected fee_balance_cents 0, got {rebuilder['fee_balance_cents']} for an unfunded rebuilder"
    )

    error = validate_error(_submit(env["application_id"], env["rebuilder_id"]), "ERR_VEHICLE_FRAUD_HOLD")
    assert error["error_id"] != "ERR_INSUFFICIENT_FEE_BALANCE", (
        "the fiscal check speaks last, so the empty balance must not be the reported failure"
    )


def test_fraud_held_submit_refusal_moves_no_money_and_no_status():
    """The refused submit escrows nothing and leaves the application in draft.

    PRD: "Checks are evaluated in the following fixed order, and the first failure short-circuits the request:"

    Design: Difficulty/priority_pair_validation_conflict/fraud_hold_outranks_insufficient_fee_balance_on_submit
    """
    env = setup_submission_ready_application(deposit_cents=0)
    open_fraud_referral(env["vehicle_id"], application_id=env["application_id"])

    validate_error(_submit(env["application_id"], env["rebuilder_id"]), "ERR_VEHICLE_FRAUD_HOLD")

    application = read_application(env["application_id"])
    assert application["status"] == "DRAFT", (
        f"expected status DRAFT, got {application['status']} after the refused submit"
    )
    assert application["fee_escrowed_cents"] == 0, (
        f"expected fee_escrowed_cents 0, got {application['fee_escrowed_cents']} after the refused submit"
    )
    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fee_balance_cents"] == 0, (
        f"expected fee_balance_cents 0, got {rebuilder['fee_balance_cents']} after the refused submit"
    )
    assert rebuilder["escrowed_fee_total_cents"] == 0, (
        f"expected escrowed_fee_total_cents 0, got {rebuilder['escrowed_fee_total_cents']} "
        "after the refused submit"
    )


def test_empty_fee_balance_alone_does_refuse_the_submit():
    """With no fraud referral in the way, the same empty balance refuses the submit itself.

    PRD: "And the rebuilder's `fee_balance_cents` must be at least the `total_program_charge_cents` that this very call computes, or the submission is refused with `ERR_INSUFFICIENT_FEE_BALANCE` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/fraud_hold_outranks_insufficient_fee_balance_on_submit
    """
    env = setup_submission_ready_application(deposit_cents=0)

    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["fraud_hold"] == "NONE", (
        f"expected fraud_hold NONE, got {vehicle['fraud_hold']} on an unreferred vehicle"
    )

    validate_error(
        _submit(env["application_id"], env["rebuilder_id"]), "ERR_INSUFFICIENT_FEE_BALANCE"
    )


# ===========================================================================
# an application that is no longer DRAFT outranks the closed submission window
# ===========================================================================
def test_already_submitted_status_outranks_the_closed_submission_window():
    """Resubmitting a submitted package long after the window closed reports the status.

    PRD: "Checks are evaluated in the following fixed order, and the first failure short-circuits the request:"

    Design: Difficulty/priority_pair_validation_conflict/application_not_draft_outranks_expired_submission_window_on_resubmit
    """
    env = setup_submitted_application(
        rebuilder_overrides={"license_expires_at": LATE_LICENSE_EXPIRY}
    )
    assert env["application"]["status"] == "SUBMITTED", (
        f"expected status SUBMITTED, got {env['application']['status']} after the first submit"
    )
    # The clock now stands well past the salvage title's issued_at plus 180 days,
    # so the window gate would also fail if the status gate did not speak first.
    set_clock(PAST_THE_SUBMISSION_WINDOW)

    error = validate_error(
        _submit(env["application_id"], env["rebuilder_id"]), "ERR_APPLICATION_NOT_DRAFT"
    )
    assert error["error_id"] != "ERR_SUBMISSION_WINDOW_EXPIRED", (
        "state-machine admissibility is evaluated before the temporal windows, so the "
        "closed window must not be the reported failure"
    )


def test_refused_resubmit_takes_no_second_escrow():
    """The refused resubmit leaves the first escrow standing and takes no second one.

    PRD: "It then sets `fee_escrowed_cents` equal to the freshly computed `total_program_charge_cents`, raises the rebuilder's `escrowed_fee_total_cents` by that charge, lowers the rebuilder's `fee_balance_cents` by the same charge, and moves the application `DRAFT → SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/application_not_draft_outranks_expired_submission_window_on_resubmit
    """
    env = setup_submitted_application(
        rebuilder_overrides={"license_expires_at": LATE_LICENSE_EXPIRY}
    )
    set_clock(PAST_THE_SUBMISSION_WINDOW)

    validate_error(
        _submit(env["application_id"], env["rebuilder_id"]), "ERR_APPLICATION_NOT_DRAFT"
    )

    application = read_application(env["application_id"])
    assert application["status"] == "SUBMITTED", (
        f"expected status SUBMITTED, got {application['status']} after the refused resubmit"
    )
    assert application["fee_escrowed_cents"] == SEDAN_PROGRAM_CHARGE_CENTS, (
        f"expected fee_escrowed_cents {SEDAN_PROGRAM_CHARGE_CENTS}, got "
        f"{application['fee_escrowed_cents']} after the refused resubmit"
    )
    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fee_balance_cents"] == DEPOSIT_CENTS - SEDAN_PROGRAM_CHARGE_CENTS, (
        f"expected fee_balance_cents {DEPOSIT_CENTS - SEDAN_PROGRAM_CHARGE_CENTS}, got "
        f"{rebuilder['fee_balance_cents']} after the refused resubmit"
    )
    assert rebuilder["escrowed_fee_total_cents"] == SEDAN_PROGRAM_CHARGE_CENTS, (
        f"expected escrowed_fee_total_cents {SEDAN_PROGRAM_CHARGE_CENTS}, got "
        f"{rebuilder['escrowed_fee_total_cents']} after the refused resubmit"
    )


def test_closed_submission_window_alone_does_refuse_a_draft_submit():
    """A package still in draft when the 180-day window closes hears about the window.

    PRD: "The logical clock must be no later than the salvage title's `issued_at` plus 180 days; a rebuilder who has not submitted by the end of that 180-day window loses it and is refused with `ERR_SUBMISSION_WINDOW_EXPIRED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/application_not_draft_outranks_expired_submission_window_on_resubmit
    """
    env = setup_submission_ready_application(
        rebuilder_overrides={"license_expires_at": LATE_LICENSE_EXPIRY}
    )
    assert env["application"]["status"] == "DRAFT", (
        f"expected status DRAFT, got {env['application']['status']} before any submit"
    )
    set_clock(PAST_THE_SUBMISSION_WINDOW)

    validate_error(
        _submit(env["application_id"], env["rebuilder_id"]), "ERR_SUBMISSION_WINDOW_EXPIRED"
    )

    application = read_application(env["application_id"])
    assert application["status"] == "DRAFT", (
        f"expected status DRAFT, got {application['status']} after the refused submit"
    )
    assert application["fee_escrowed_cents"] == 0, (
        f"expected fee_escrowed_cents 0, got {application['fee_escrowed_cents']} "
        "after the refused submit"
    )
