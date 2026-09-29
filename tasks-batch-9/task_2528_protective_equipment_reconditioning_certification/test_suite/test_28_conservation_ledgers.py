"""Ledgers that must balance after every single request.

Part stock buckets always re-sum to the quantity booked into the cage, and a
shipment's disposition counters always re-sum to the counted tally — including
after a compensating void.
"""
from test_helpers import (
    PLANT_MANAGER,
    add_part_line,
    api_client,
    assert_disposition_ledger_conserved,
    assert_part_stock_conserved,
    cancel_repair_payload,
    create_part,
    get_success_data,
    install_repair_order,
    issue_label,
    open_repair_order,
    read_label,
    read_part,
    read_repair_order,
    read_shipment,
    read_unit,
    release_unit,
    setup_certified_units,
    setup_determined_units,
    setup_repair_pending_unit,
    stage_unit,
    submit_repair_order,
    void_label,
)


def test_the_three_stock_buckets_resum_to_received_after_every_move():
    """Reserving four of ten and then installing them walks stock across all three
    buckets, and the cage total never changes.

    PRD §2.8: "For every `ApprovedPart`, the quantity originally booked into the
    parts cage always equals the sum of the three moving buckets: `received_qty`
    equals `on_hand_qty` plus `reserved_qty` plus `consumed_qty`."

    Design: Difficulty/compensating_invariant/part_stock_buckets_sum_to_received_across_reserve_install_cancel
    """
    ctx = setup_repair_pending_unit()
    part = create_part(ctx["model"]["id"], received_qty=10)
    assert (part["on_hand_qty"], part["reserved_qty"], part["consumed_qty"]) == (10, 0, 0)
    assert_part_stock_conserved(part)

    order = open_repair_order(ctx["unit"]["id"])
    add_part_line(order["id"], part["id"], 4)
    submit_repair_order(order["id"])

    part = read_part(part["id"])
    assert (part["on_hand_qty"], part["reserved_qty"], part["consumed_qty"]) == (6, 4, 0)
    assert_part_stock_conserved(part)

    install_repair_order(order["id"])

    part = read_part(part["id"])
    assert (part["on_hand_qty"], part["reserved_qty"], part["consumed_qty"]) == (6, 0, 4)
    assert_part_stock_conserved(part)


def test_cancelling_a_reservation_credits_the_shelf_without_touching_consumed_stock():
    """A second order reserves the remaining six and is then cancelled: the six go
    back on the shelf while the four already installed stay consumed.

    PRD §2.8: "Reserving stock moves quantity out of `on_hand_qty` into
    `reserved_qty`; installing moves it out of `reserved_qty` into
    `consumed_qty`; cancelling an order that still holds reservations moves it
    back out of `reserved_qty` into `on_hand_qty`."

    Design: Difficulty/compensating_invariant/part_stock_buckets_sum_to_received_across_reserve_install_cancel
    """
    ctx = setup_repair_pending_unit()
    part = create_part(ctx["model"]["id"], received_qty=10)

    order_a = open_repair_order(ctx["unit"]["id"])
    add_part_line(order_a["id"], part["id"], 4)
    submit_repair_order(order_a["id"])
    install_repair_order(order_a["id"])

    order_b = open_repair_order(ctx["unit"]["id"])
    add_part_line(order_b["id"], part["id"], 6, lot_code="LOT-B", oem_cert_ref="OEM-B-1")
    submit_repair_order(order_b["id"])
    part = read_part(part["id"])
    assert (part["on_hand_qty"], part["reserved_qty"], part["consumed_qty"]) == (0, 6, 4)

    cancelled = get_success_data(
        api_client.cancel_repair_order(
            order_b["id"],
            cancel_repair_payload(cancel_reason="customer declined the second rework quote"),
            PLANT_MANAGER,
        )
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["reserved_parts_cents"] == 0
    assert cancelled["installed_parts_cents"] == 0

    part = read_part(part["id"])
    assert part["received_qty"] == 10
    assert (part["on_hand_qty"], part["reserved_qty"], part["consumed_qty"]) == (6, 0, 4)
    assert_part_stock_conserved(part)

    order_a = read_repair_order(order_a["id"])
    assert order_a["status"] == "INSTALLED"
    assert order_a["installed_parts_cents"] == 18000
    assert read_unit(ctx["unit"]["id"])["recon_status"] == "REPAIR_PENDING"


def test_the_disposition_ledger_holds_from_acceptance_through_the_first_certification():
    """Acceptance loads every counted unit into the in-process bucket, and
    certifying one moves it across without changing the total.

    PRD §2.8: "At acceptance `units_in_process` is set to `counted_unit_count` and
    the other three are set to zero."

    Design: Difficulty/compensating_invariant/shipment_disposition_ledger_sums_to_counted_after_void_and_release
    """
    ctx = setup_determined_units(unit_count=2, determination="PASS")

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["counted_unit_count"] == 2
    assert shipment["units_in_process"] == 2
    assert shipment["units_certified"] == 0
    assert shipment["units_condemned"] == 0
    assert shipment["units_released"] == 0
    assert_disposition_ledger_conserved(shipment)

    issue_label(ctx["units"][0]["id"])

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_in_process"] == 1
    assert shipment["units_certified"] == 1
    assert_disposition_ledger_conserved(shipment)


def test_the_disposition_ledger_still_balances_after_a_void_and_a_release():
    """Voiding one label and releasing the other unit leaves one unit back in
    process and one released, still summing to the counted tally of two.

    PRD §2.8: "Because every mutation is a paired decrement and increment, the
    four counters can never drift away from `counted_unit_count`."

    Design: Difficulty/compensating_invariant/shipment_disposition_ledger_sums_to_counted_after_void_and_release
    """
    ctx = setup_certified_units(unit_count=2)
    stage_unit(ctx["units"][0]["id"])

    void_label(ctx["labels"][1]["id"])
    release_unit(ctx["units"][0]["id"])

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["counted_unit_count"] == 2
    assert shipment["units_in_process"] == 1
    assert shipment["units_certified"] == 0
    assert shipment["units_condemned"] == 0
    assert shipment["units_released"] == 1
    assert_disposition_ledger_conserved(shipment)
    assert shipment["status"] == "IN_PROCESS"
    assert shipment["settlement_locked"] is False

    released = read_unit(ctx["units"][0]["id"])
    assert released["custody_status"] == "RETURNED"
    assert released["released_to"] == "Northside High athletics"
    assert read_unit(ctx["units"][1]["id"])["recon_status"] == "REPAIR_PENDING"
    assert read_label(ctx["labels"][0]["id"])["status"] == "ACTIVE"
    assert read_label(ctx["labels"][1]["id"])["status"] == "VOIDED"
