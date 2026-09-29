"""Withdrawing a committed order and putting the reserved blank back."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions, fixtures
from test_helpers.test_users import OPTICIAN_A_HEADERS

PROVISIONAL_GROSS = 81126


def _committed_order_with_one_scheduled_window(api):
    """One blank reserved and one surfacing window booked but never started."""
    scenario = fixtures.surfaced_queued_job(api)

    lot = fixtures.read_lot(api, scenario["lot_id"])
    assert lot["received_qty"] == 2
    assertions.assert_lot_quantities(
        lot, on_hand=1, allocated=1, consumed=0, scrapped=0, status="AVAILABLE"
    )

    operation = fixtures.book_surfacing(api, scenario)
    assert operation["status"] == "SCHEDULED"
    scenario["operation_id"] = operation["id"]

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["gross_charge_cents"] == PROVISIONAL_GROSS
    assert order["billing_status"] == "PROVISIONAL_QUOTED"
    return scenario


def test_withdrawal_moves_both_dimensions_and_zeroes_the_money_block(api):
    """Nothing was ever charged, so the whole money block goes to zero.

    PRD 3.9: "The order's own move depends on where it stood: `DRAFT → CANCELLED`,
    `LAYOUT_READY → CANCELLED`, `IN_LAB → CANCELLED` or `REMAKE_PENDING → CANCELLED`
    on the fulfillment dimension, and `PROVISIONAL_QUOTED → CANCELLED_NO_CHARGE` on
    the billing dimension, with `gross_charge_cents`, `patient_portion_cents`,
    `expedite_fee_cents` and `estimated_benefit_cents` all set to 0."

    Design: Difficulty/compensating_invariant/order_cancel_returns_the_allocated_blank_and_conserves_the_lot_quantity_ledger
    """
    scenario = _committed_order_with_one_scheduled_window(api)

    order = validate_success(
        api.cancel_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS)
    )

    assert order["fulfillment_status"] == "CANCELLED"
    assert order["billing_status"] == "CANCELLED_NO_CHARGE"
    assert order["gross_charge_cents"] == 0
    assert order["patient_portion_cents"] == 0
    assert order["expedite_fee_cents"] == 0
    assert order["estimated_benefit_cents"] == 0


def test_the_job_and_its_booked_window_are_unwound_in_the_same_write(api):
    """Both carry the literal ORDER_CANCELLED reason and the job keeps its lot link.

    PRD 3.9: "Every `SCHEDULED` occupation of the order's newest job moves `SCHEDULED
    → CANCELLED` with `cancel_reason` set to the literal string `ORDER_CANCELLED`,
    freeing the machine and bay windows they held."

    Design: Difficulty/compensating_invariant/order_cancel_returns_the_allocated_blank_and_conserves_the_lot_quantity_ledger
    """
    scenario = _committed_order_with_one_scheduled_window(api)

    validate_success(api.cancel_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS))

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "SCRAPPED"
    assert job["scrap_reason"] == "ORDER_CANCELLED"
    assert job["blank_lot_id"] == scenario["lot_id"]

    operation = fixtures.read_operation(api, scenario["operation_id"])
    assert operation["status"] == "CANCELLED"
    assert operation["cancel_reason"] == "ORDER_CANCELLED"


def test_the_reserved_unit_is_returned_rather_than_written_off(api):
    """Two received units are still two on the shelf, with nothing scrapped.

    PRD 3.9: "If the job still held a blank reservation, the reservation is
    compensated rather than destroyed: the lot's `allocated_qty` falls by 1 and its
    `on_hand_qty` rises by 1, restoring `on_hand_qty` to its exact pre-allocation
    value, and a lot that had gone `DEPLETED` flips back to `AVAILABLE` once its
    `on_hand_qty` becomes 1."

    Design: Difficulty/compensating_invariant/order_cancel_returns_the_allocated_blank_and_conserves_the_lot_quantity_ledger
    """
    scenario = _committed_order_with_one_scheduled_window(api)

    validate_success(api.cancel_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS))

    lot = fixtures.read_lot(api, scenario["lot_id"])
    assertions.assert_lot_quantities(
        lot, on_hand=2, allocated=0, consumed=0, scrapped=0, status="AVAILABLE"
    )
    assertions.assert_blank_ledger_conserved(lot)


def test_no_settlement_entry_is_ever_appended(api):
    """Withdrawal touches no ledger because nothing was charged.

    PRD 3.9: "No settlement entry is appended, because nothing was ever charged."

    Design: Difficulty/compensating_invariant/order_cancel_returns_the_allocated_blank_and_conserves_the_lot_quantity_ledger
    """
    scenario = _committed_order_with_one_scheduled_window(api)

    validate_success(api.cancel_rx_order(scenario["order_id"], OPTICIAN_A_HEADERS))

    entries, meta = validate_paginated(
        api.list_order_settlement_entries(scenario["order_id"], OPTICIAN_A_HEADERS)
    )
    assert entries == []
    assert meta["total_count"] == 0
