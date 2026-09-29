"""Recording a deed: the four-hop cascade to suspense."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_decimal_interest, assert_money
from test_helpers.test_users import ADMIN_HEADERS


def _fully_papered_and_funded_world(api):
    """A CURATIVE_CLOSED / FUNDED agreement whose interest also carries an
    EXECUTED division order on a unit holding the same tract."""
    world = fx.psa_ready(api)
    world["unit"] = fx.create_unit(api)
    world["allocation"] = fx.create_allocation(
        api, world["unit"]["id"], world["tract"]["id"]
    )
    world["order"] = fx.create_division_order(
        api, world["interest"]["id"], world["unit"]["id"]
    )
    world["order"] = fx.send_operator_response(
        api, world["order"]["id"], operator_decimal=0.00195313, effective_production_month="2026-06"
    )
    fx.close_curative(api, world["psa"]["id"])
    fx.fund_psa(api, world["psa"]["id"], wire_amount=48000.00, wire_reference="WIRE-7")
    return world


def test_recording_closes_the_agreement_and_transfers_the_interest(api):
    """Hops one and two: the agreement closes and the interest is acquired.

    PRD: "The first hop writes `recording_county`, `recorded_book_page` and
    `recording_date` onto the agreement and sets `psa_status` to `CLOSED`."

    Design: Difficulty/transitive_cascade/record_deed_cascades_psa_to_interest_to_division_order_to_suspense
    """
    world = _fully_papered_and_funded_world(api)

    psa = fx.record_deed(
        api,
        world["psa"]["id"],
        recording_county="Reeves",
        recorded_book_page="915/210",
        recording_date="2026-08-10",
    )
    assert psa["psa_status"] == "CLOSED"
    assert psa["recorded_book_page"] == "915/210"

    interest = fx.read_interest(api, world["interest"]["id"])
    assert interest["interest_status"] == "ACQUIRED"
    assert interest["acquiring_deed_book_page"] == "915/210"


def test_recording_disputes_the_live_division_order_without_touching_its_pin(api):
    """Hop three: the order is disputed for ownership change, pin intact.

    PRD: "The third hop, caused by the second rather than by the recording
    itself, reaches every division order of that interest whose `do_status` is
    `SENT` or `EXECUTED`: each such order is driven to `DISPUTED` with a
    `dispute_reason` of `OWNERSHIP_CHANGE`, and each one's `expected_decimal` is
    recomputed against present-day state."

    Design: Difficulty/transitive_cascade/record_deed_cascades_psa_to_interest_to_division_order_to_suspense
    """
    world = _fully_papered_and_funded_world(api)

    fx.record_deed(
        api,
        world["psa"]["id"],
        recorded_book_page="915/210",
        recording_date="2026-08-10",
    )

    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "DISPUTED"
    assert order["dispute_reason"] == "OWNERSHIP_CHANGE"
    assert_decimal_interest(order["pinned_decimal"], "0.00195313", "pinned_decimal")


def test_recording_opens_one_ownership_transfer_suspense_account(api):
    """Hop four: exactly one ACCRUING account, opened for the transfer.

    PRD: "The fourth hop, caused by the third, opens or reuses a suspense account
    for each of those orders, keyed on the pairing of the order and its payee of
    record: the account's `suspense_status` is `ACCRUING`, its `suspense_reason`
    is `OWNERSHIP_TRANSFER`, and, when the account is being created rather than
    reused, its `first_suspended_month` is the logical clock's own year and month
    in `YYYY-MM` form."

    Design: Difficulty/transitive_cascade/record_deed_cascades_psa_to_interest_to_division_order_to_suspense
    """
    world = _fully_papered_and_funded_world(api)

    fx.record_deed(
        api,
        world["psa"]["id"],
        recorded_book_page="915/210",
        recording_date="2026-08-10",
    )

    accounts, _meta = validate_paginated(
        api.list_suspense_accounts(ADMIN_HEADERS, {"division_order_id": world["order"]["id"]})
    )
    assert len(accounts) == 1
    account = accounts[0]
    assert account["suspense_reason"] == "OWNERSHIP_TRANSFER"
    assert account["suspense_status"] == "ACCRUING"
    assert_money(account["accrued_amount"], "0.00", "accrued_amount")
    assert account["held_detail_count"] == 0
    assert account["first_suspended_month"] == "2026-08"
