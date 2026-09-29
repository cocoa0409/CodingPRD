"""Undoing an earlier act must put every aggregate back where it was.

Two aggregates in this program are maintained incrementally and therefore have
to be walked back by hand when the act that raised them is reversed: an
application's documented parts cost, which is defined as the sum over exactly
its verified receipts, and a rebuilder's four money counters, which must close
into one identity through every disposition of an escrow.
"""

import pytest

from test_helpers import (
    api_client,
    assert_fee_ledger_closes,
    file_parts_document,
    make_inspector_headers,
    make_rebuilder_headers,
    read_application,
    read_parts_document,
    read_rebuilder,
    read_vehicle,
    reject_parts_document,
    reject_parts_document_payload,
    setup_submission_ready_application,
    setup_submitted_application,
    validate_error,
    validate_success,
    verify_parts_document,
    withdraw_application_payload,
)

api = api_client

# The default SEDAN package documents STRUCTURAL 200000, RESTRAINT 50000 and
# LIGHTING 30000, all verified.
RESTRAINT_AMOUNT_CENTS = 50_000
DOCUMENTED_COST_BEFORE_CENTS = 280_000
DOCUMENTED_COST_AFTER_CENTS = 230_000

# A bare SEDAN package escrows the base application fee plus the one-off
# structural surcharge, drawn against the default deposit.
ESCROWED_CHARGE_CENTS = 20_000
DEPOSIT_CENTS = 500_000
BALANCE_WITH_ESCROW_CENTS = 480_000


def _package_with_three_verified_receipts() -> dict:
    """A DRAFT application carrying one verified receipt per required part class."""
    env = setup_submission_ready_application()
    application = read_application(env["application_id"])
    assert application["documented_parts_cost_cents"] == DOCUMENTED_COST_BEFORE_CENTS, (
        f"expected {DOCUMENTED_COST_BEFORE_CENTS} documented before the reversal, "
        f"got {application['documented_parts_cost_cents']}"
    )
    assert application["documentation_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        f"expected a complete package before the reversal, "
        f"got {application['documentation_completeness_pct']}"
    )
    return env


def _sum_over_verified_documents(env: dict) -> int:
    """The invariant's right-hand side, read back one document at a time."""
    total = 0
    for document in env["document_list"]:
        stored = read_parts_document(document["id"])
        if stored["status"] == "VERIFIED":
            total += stored["amount_cents"]
    return total


def test_rejecting_a_verified_receipt_subtracts_its_amount_from_the_documented_cost():
    """Impeaching a receipt takes the money it documented back out of the total.

    PRD: "Rejecting a `VERIFIED` document is a compensating action and must also subtract that document's `amount_cents` from the application's `documented_parts_cost_cents`, restoring the invariant that `documented_parts_cost_cents` always equals the sum of `amount_cents` over exactly the application's `VERIFIED` documents."

    Design: Difficulty/compensating_invariant/rejecting_a_previously_verified_document_restores_the_parts_cost_aggregate
    """
    env = _package_with_three_verified_receipts()
    restraint = env["documents"]["RESTRAINT"]
    assert restraint["amount_cents"] == RESTRAINT_AMOUNT_CENTS, (
        f"expected the restraint receipt to document {RESTRAINT_AMOUNT_CENTS}, "
        f"got {restraint['amount_cents']}"
    )

    response = api.reject_parts_document(
        restraint["id"],
        reject_parts_document_payload("ILLEGIBLE"),
        make_inspector_headers(env["inspector_id"]),
    )
    rejected = validate_success(response, expected_status=200)

    assert rejected["status"] == "REJECTED", (
        f"expected the receipt to move to REJECTED, got {rejected['status']}"
    )
    assert rejected["rejection_reason"] == "ILLEGIBLE", (
        f"expected rejection_reason ILLEGIBLE to be stored, got {rejected['rejection_reason']}"
    )

    application = read_application(env["application_id"])
    assert application["documented_parts_cost_cents"] == DOCUMENTED_COST_AFTER_CENTS, (
        f"expected the documented cost to fall from {DOCUMENTED_COST_BEFORE_CENTS} by "
        f"{RESTRAINT_AMOUNT_CENTS} to {DOCUMENTED_COST_AFTER_CENTS}, "
        f"got {application['documented_parts_cost_cents']}"
    )
    assert application["documented_parts_cost_cents"] == _sum_over_verified_documents(env), (
        f"the aggregate must equal the sum over exactly the VERIFIED receipts "
        f"({_sum_over_verified_documents(env)}), "
        f"got {application['documented_parts_cost_cents']}"
    )


def test_a_replacement_receipt_carries_the_documented_cost_back_up():
    """Filing and verifying a fresh receipt restores the withdrawn amount.

    PRD: "A successful verification records `verified_by_inspector_id` as the acting inspector's `X-User-ID`, adds the document's `amount_cents` to the application's `documented_parts_cost_cents`, and recomputes the application's `documentation_completeness_pct` and — once the application has been submitted — its `assessed_fee_cents`."

    Design: Difficulty/compensating_invariant/rejecting_a_previously_verified_document_restores_the_parts_cost_aggregate
    """
    env = _package_with_three_verified_receipts()
    reject_parts_document(
        env["documents"]["RESTRAINT"]["id"], env["inspector_id"], rejection_reason="ILLEGIBLE"
    )
    assert read_application(env["application_id"])[
        "documented_parts_cost_cents"
    ] == DOCUMENTED_COST_AFTER_CENTS, "the rejection must have withdrawn the restraint amount first"

    replacement = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        part_class="RESTRAINT",
        amount_cents=RESTRAINT_AMOUNT_CENTS,
        vendor_name="Second Chance Restraints",
    )
    verified = verify_parts_document(replacement["id"], env["inspector_id"])
    assert verified["status"] == "VERIFIED", (
        f"expected the replacement receipt to be VERIFIED, got {verified['status']}"
    )

    application = read_application(env["application_id"])
    assert application["documented_parts_cost_cents"] == DOCUMENTED_COST_BEFORE_CENTS, (
        f"expected the documented cost back at {DOCUMENTED_COST_BEFORE_CENTS}, "
        f"got {application['documented_parts_cost_cents']}"
    )
    assert application["documentation_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        f"the replacement re-covers the restraint class, so completeness must read 100.00, "
        f"got {application['documentation_completeness_pct']}"
    )


def test_the_withdrawn_receipt_stops_covering_its_required_part_class():
    """A rejected receipt no longer satisfies the class it was filed for.

    PRD: "When the required list is non-empty, the program counts how many of the required classes are covered — a class counts as covered when at least one document of this application has that `part_class` and `status` of `VERIFIED` — then divides the covered count by the size of the required list, multiplies by 100 and rounds half up to two decimal places."

    Design: Difficulty/compensating_invariant/rejecting_a_previously_verified_document_restores_the_parts_cost_aggregate
    """
    env = _package_with_three_verified_receipts()

    reject_parts_document(
        env["documents"]["RESTRAINT"]["id"], env["inspector_id"], rejection_reason="ILLEGIBLE"
    )

    application = read_application(env["application_id"])
    assert application["documentation_completeness_pct"] == pytest.approx(66.67, abs=0.01), (
        f"two of the three required classes remain covered, so completeness must read 66.67, "
        f"got {application['documentation_completeness_pct']}"
    )
    assert application["status"] == "DRAFT", (
        f"the compensation happens without moving the application, got {application['status']}"
    )


def test_rejecting_an_already_rejected_receipt_cannot_subtract_the_amount_twice():
    """The compensation runs once; a repeat rejection is refused outright.

    PRD: "Rejection is admissible from either `SUBMITTED` or `VERIFIED`; a document that is already `REJECTED` draws `ERR_PARTS_DOCUMENT_STATE_INVALID`, and the acting inspector must again hold a `CURRENT` credential."

    Design: Difficulty/compensating_invariant/rejecting_a_previously_verified_document_restores_the_parts_cost_aggregate
    """
    env = _package_with_three_verified_receipts()
    restraint = env["documents"]["RESTRAINT"]
    reject_parts_document(restraint["id"], env["inspector_id"], rejection_reason="ILLEGIBLE")

    response = api.reject_parts_document(
        restraint["id"],
        reject_parts_document_payload("DUPLICATE"),
        make_inspector_headers(env["inspector_id"]),
    )
    validate_error(response, "ERR_PARTS_DOCUMENT_STATE_INVALID")

    application = read_application(env["application_id"])
    assert application["documented_parts_cost_cents"] == DOCUMENTED_COST_AFTER_CENTS, (
        f"the amount must be withdrawn exactly once, leaving {DOCUMENTED_COST_AFTER_CENTS}, "
        f"got {application['documented_parts_cost_cents']}"
    )
    assert application["documented_parts_cost_cents"] == _sum_over_verified_documents(env), (
        f"the aggregate must still equal the sum over the VERIFIED receipts "
        f"({_sum_over_verified_documents(env)}), "
        f"got {application['documented_parts_cost_cents']}"
    )


def _submitted_with_escrow_posted() -> dict:
    """A submitted SEDAN application whose program charge is sitting in escrow."""
    env = setup_submitted_application()
    application = read_application(env["application_id"])
    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert application["fee_escrowed_cents"] == ESCROWED_CHARGE_CENTS, (
        f"expected {ESCROWED_CHARGE_CENTS} escrowed on submission, "
        f"got {application['fee_escrowed_cents']}"
    )
    assert rebuilder["escrowed_fee_total_cents"] == ESCROWED_CHARGE_CENTS, (
        f"expected escrowed_fee_total_cents {ESCROWED_CHARGE_CENTS}, "
        f"got {rebuilder['escrowed_fee_total_cents']}"
    )
    assert rebuilder["fee_balance_cents"] == BALANCE_WITH_ESCROW_CENTS, (
        f"expected fee_balance_cents {BALANCE_WITH_ESCROW_CENTS} while the charge is escrowed, "
        f"got {rebuilder['fee_balance_cents']}"
    )
    return env


def test_withdrawing_a_submitted_application_refunds_the_escrow_in_full():
    """The rebuilder's exit hands back every cent the submission escrowed.

    PRD: "A successful withdrawal refunds the escrow in full — the rebuilder's `fee_balance_cents` rises by `fee_escrowed_cents`, which is then set to 0, so `escrowed_fee_total_cents` falls by the refunded amount and the money becomes spendable again."

    Design: Difficulty/compensating_invariant/withdrawing_a_submitted_application_conserves_the_rebuilder_fee_ledger
    """
    env = _submitted_with_escrow_posted()

    response = api.withdraw_application(
        env["application_id"],
        withdraw_application_payload(withdrawn_reason="donor structural member fell through"),
        make_rebuilder_headers(env["rebuilder_id"]),
    )
    withdrawn = validate_success(response, expected_status=200)

    assert withdrawn["fee_escrowed_cents"] == 0, (
        f"expected fee_escrowed_cents zeroed by the refund, got {withdrawn['fee_escrowed_cents']}"
    )

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fee_balance_cents"] == DEPOSIT_CENTS, (
        f"expected fee_balance_cents to rise by {ESCROWED_CHARGE_CENTS} back to {DEPOSIT_CENTS}, "
        f"got {rebuilder['fee_balance_cents']}"
    )
    assert rebuilder["escrowed_fee_total_cents"] == 0, (
        f"expected escrowed_fee_total_cents to fall by the refunded amount to 0, "
        f"got {rebuilder['escrowed_fee_total_cents']}"
    )


def test_the_refund_is_not_a_capture_so_consumed_fees_never_move():
    """A withdrawal moves money sideways, not into the program's pocket.

    PRD: "A refund (withdrawal, or a fraud void) adds the escrowed amount back to `fee_balance_cents` and then zeroes `fee_escrowed_cents`, so `escrowed_fee_total_cents` falls and the money becomes spendable again."

    Design: Difficulty/compensating_invariant/withdrawing_a_submitted_application_conserves_the_rebuilder_fee_ledger
    """
    env = _submitted_with_escrow_posted()
    before = read_rebuilder(env["rebuilder_id"])
    assert before["fees_consumed_cents"] == 0, (
        f"nothing has been captured before the withdrawal, got {before['fees_consumed_cents']}"
    )

    api.withdraw_application(
        env["application_id"],
        withdraw_application_payload(withdrawn_reason="donor structural member fell through"),
        make_rebuilder_headers(env["rebuilder_id"]),
    )

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fees_consumed_cents"] == 0, (
        f"a refund is not a capture, so fees_consumed_cents must stay 0, "
        f"got {rebuilder['fees_consumed_cents']}"
    )
    assert rebuilder["fees_deposited_cents"] == DEPOSIT_CENTS, (
        f"the cumulative deposit total never decreases, expected {DEPOSIT_CENTS}, "
        f"got {rebuilder['fees_deposited_cents']}"
    )


def test_the_ledger_identity_still_closes_after_the_refund():
    """Whatever the disposition, the four money counters add back up.

    PRD: "And `fee_balance_cents` — the unescrowed, unconsumed money the rebuilder can still spend — equals `fees_deposited_cents` reduced by `escrowed_fee_total_cents` and reduced again by `fees_consumed_cents`."

    Design: Difficulty/compensating_invariant/withdrawing_a_submitted_application_conserves_the_rebuilder_fee_ledger
    """
    env = _submitted_with_escrow_posted()
    assert_fee_ledger_closes(read_rebuilder(env["rebuilder_id"]))

    api.withdraw_application(
        env["application_id"],
        withdraw_application_payload(withdrawn_reason="donor structural member fell through"),
        make_rebuilder_headers(env["rebuilder_id"]),
    )

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert_fee_ledger_closes(rebuilder)
    expected_balance = (
        rebuilder["fees_deposited_cents"]
        - rebuilder["escrowed_fee_total_cents"]
        - rebuilder["fees_consumed_cents"]
    )
    assert rebuilder["fee_balance_cents"] == expected_balance, (
        f"expected fee_balance_cents {expected_balance} from the deposited total less escrow "
        f"less consumption, got {rebuilder['fee_balance_cents']}"
    )


def test_the_withdrawn_application_leaves_the_vehicles_live_set():
    """The exit is terminal and frees the vehicle for a fresh attempt at retitling.

    PRD: "The application then moves to `WITHDRAWN` with `terminal_at` stamped, and the vehicle's `open_application_count` is recomputed downward, freeing the vehicle for a fresh application."

    Design: Difficulty/compensating_invariant/withdrawing_a_submitted_application_conserves_the_rebuilder_fee_ledger
    """
    env = _submitted_with_escrow_posted()
    assert read_vehicle(env["vehicle_id"])["open_application_count"] == 1, (
        "the live application must be counted against the vehicle before the withdrawal"
    )

    api.withdraw_application(
        env["application_id"],
        withdraw_application_payload(withdrawn_reason="donor structural member fell through"),
        make_rebuilder_headers(env["rebuilder_id"]),
    )

    application = read_application(env["application_id"])
    assert application["status"] == "WITHDRAWN", (
        f"expected the application to move to WITHDRAWN, got {application['status']}"
    )
    assert application["terminal_at"] is not None, (
        "terminal_at must be stamped when the application is withdrawn"
    )
    assert application["withdrawn_reason"] == "donor structural member fell through", (
        f"expected the supplied reason to be stored, got {application['withdrawn_reason']}"
    )
    assert read_vehicle(env["vehicle_id"])["open_application_count"] == 0, (
        f"expected open_application_count recomputed downward to 0, got "
        f"{read_vehicle(env['vehicle_id'])['open_application_count']}"
    )
