"""Cancellation compensation, and the two conserved quantities."""

from test_helpers import (
    ApiErrorId,
    assert_ledger_entry_sequence,
    assert_lot_counters,
    assert_lot_units_conserved,
    assert_points_ledger_conserved,
    convert_testers,
    new_customer,
    read_customer,
    read_ledger,
    read_lot,
    read_order,
    reserve,
    setup_catalog,
    setup_captured_order,
    setup_draft_order,
    setup_limited_launch_catalog,
    validate_error,
    validate_success,
)


def _reserved_limited_order_with_points(api):
    """A PUBLIC limited variant (lot: 5 received, 3 earmarked), a customer seeded with
    500 points, and a RESERVED order for 2 units redeeming 300 points.

    total_due = 5000 subtotal - 0 tier discount - 1500 points value = 3500."""
    catalog = setup_limited_launch_catalog(
        units_received=5, launch_reserved_units=3, clock_to="2026-05-03T00:00:00Z"
    )
    customer = new_customer(initial_points=500)
    ctx = setup_draft_order(
        customer=customer, catalog=catalog, quantity=2, points_redeemed=300
    )
    ctx["order"] = reserve(ctx["order"]["id"])
    return ctx


def test_cancelling_a_reserved_order_restores_inventory_and_the_launch_pool(
    api, associate_headers
):
    """PRD §3.7: "First, the inventory is released: for each drawn lot, the drawn units
    come out of `reserved_units` and go back into `on_hand_units`, and
    `launch_reserved_units` is restored by exactly the number of units the reservation
    originally took from the launch pool, so the earmark is made whole rather than being
    quietly converted into general stock; the lot's `version` increments."
    PRD §3.7: "Because that restoration also drops the customer's held-unit count for
    the limited variant, it re-opens headroom under `per_customer_cap` — the same
    customer can now go and try for the launch again."

    Design: Difficulty/transitive_cascade/cancel_reserved_order_cascades_inventory_launch_pool_points_and_balance
    """
    ctx = _reserved_limited_order_with_points(api)
    assert ctx["order"]["total_due_cents"] == 3500

    cancelled = validate_success(
        api.cancel_order(
            ctx["order"]["id"], associate_headers, {"reason": "CUSTOMER_CHANGED_MIND"}
        )
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"

    lot = read_lot(ctx["lot"]["id"])
    assert_lot_counters(lot, on_hand_units=5, reserved_units=0, launch_reserved_units=3)

    # Headroom under the cap is re-opened: the same customer may draw the launch again.
    again = setup_draft_order(
        customer=ctx["customer"],
        catalog={k: ctx[k] for k in ("store", "product", "variant", "lot")},
        quantity=2,
    )
    retried = validate_success(api.reserve_order(again["order"]["id"], associate_headers))
    assert retried["fulfillment_status"] == "RESERVED"


def test_cancelling_a_reserved_order_reverses_the_points_redemption(
    api, associate_headers
):
    """PRD §3.7: "Next, if the order redeemed points, a ledger entry of type `REVERSAL`
    is appended carrying the redeemed points back as a positive `delta_points`, and, as
    a direct consequence, the customer's `points_balance` rises by exactly that amount,
    restoring the pre-order balance to the cent."
    PRD §3.7: "Meanwhile the payment dimension is settled: an `AUTHORIZED` order moves
    to `VOIDED` with no cash movement, and a `CAPTURED` order moves to `REFUNDED` with
    the order's `refunded_cents` set to its full `total_due_cents`."

    Design: Difficulty/transitive_cascade/cancel_reserved_order_cascades_inventory_launch_pool_points_and_balance
    """
    ctx = _reserved_limited_order_with_points(api)

    validate_success(
        api.cancel_order(
            ctx["order"]["id"], associate_headers, {"reason": "CUSTOMER_CHANGED_MIND"}
        )
    )

    customer = read_customer(ctx["customer"]["id"])
    assert customer["points_balance"] == 500, "the pre-order balance is restored"

    entries = read_ledger(ctx["customer"]["id"])
    assert_ledger_entry_sequence(
        entries, [("SEED", 500), ("REDEEM", -300), ("REVERSAL", 300)]
    )

    order = read_order(ctx["order"]["id"])
    assert order["payment_status"] == "UNPAID", (
        "the order was never authorised, so there is nothing to void"
    )


def test_units_are_conserved_across_tester_reserve_and_cancel(api, associate_headers):
    """PRD §2.7: "For every `InventoryLot`, the total `units_received` always equals
    the sum of `on_hand_units`, `reserved_units`, `tester_units`, `sold_units` and
    `destroyed_units`. Reserving an order moves units from on-hand to reserved; handing
    an order over moves them from reserved to sold; converting a tester moves them from
    on-hand to tester; a hygiene-mandated destruction moves them from sold to destroyed;
    a restock moves them from sold back to on-hand; a cancellation moves them from
    reserved back to on-hand. No path creates or annihilates a unit."

    Design: Difficulty/compensating_invariant/inventory_units_received_conserved_across_tester_reserve_and_cancel
    """
    catalog = setup_catalog(units_received=10)
    lot_id = catalog["lot"]["id"]

    after_tester = convert_testers(lot_id, 2, catalog["lot"]["version"])
    assert_lot_units_conserved(after_tester)

    ctx = setup_draft_order(catalog=catalog, quantity=3)
    after_reserve = reserve(ctx["order"]["id"])
    assert after_reserve["fulfillment_status"] == "RESERVED"
    assert_lot_units_conserved(read_lot(lot_id))

    validate_success(
        api.cancel_order(
            ctx["order"]["id"], associate_headers, {"reason": "CUSTOMER_CHANGED_MIND"}
        )
    )

    final = read_lot(lot_id)
    assert_lot_units_conserved(final)
    assert final["units_received"] == 10, "the conserved total never moves"


def test_lot_counters_land_on_their_exact_post_cancel_values(api, associate_headers):
    """PRD §3.2: "On success, the requested count moves out of `on_hand_units` and into
    `tester_units`, and the lot's `version` increments"
    PRD §3.7: "First, the inventory is released: for each drawn lot, the drawn units
    come out of `reserved_units` and go back into `on_hand_units`, and
    `launch_reserved_units` is restored by exactly the number of units the reservation
    originally took from the launch pool, so the earmark is made whole rather than being
    quietly converted into general stock; the lot's `version` increments."

    After a 2-unit tester conversion, a 3-unit reserve and its compensating cancel, the
    lot must read 10 == 8 + 0 + 2 + 0 + 0 with zero drift in any bucket.

    Design: Difficulty/compensating_invariant/inventory_units_received_conserved_across_tester_reserve_and_cancel
    """
    catalog = setup_catalog(units_received=10)
    lot_id = catalog["lot"]["id"]

    convert_testers(lot_id, 2, catalog["lot"]["version"])
    ctx = setup_draft_order(catalog=catalog, quantity=3)
    reserve(ctx["order"]["id"])
    validate_success(
        api.cancel_order(
            ctx["order"]["id"], associate_headers, {"reason": "CUSTOMER_CHANGED_MIND"}
        )
    )

    lot = read_lot(lot_id)
    assert_lot_counters(
        lot,
        units_received=10,
        on_hand_units=8,
        reserved_units=0,
        tester_units=2,
        sold_units=0,
        destroyed_units=0,
    )


def test_points_balance_returns_to_its_pre_order_value_after_cancel(
    api, associate_headers
):
    """PRD §2.7: "A `Customer`'s `points_balance` always equals the arithmetic sum of
    `delta_points` across every `PointsLedgerEntry` belonging to that customer."
    PRD §3.7: "Next, if the order redeemed points, a ledger entry of type `REVERSAL` is
    appended carrying the redeemed points back as a positive `delta_points`, and, as a
    direct consequence, the customer's `points_balance` rises by exactly that amount,
    restoring the pre-order balance to the cent."

    Design: Difficulty/compensating_invariant/points_balance_conserved_across_redeem_and_cancel_reversal
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer(initial_points=500)
    ctx = setup_draft_order(
        customer=customer, catalog=catalog, quantity=2, points_redeemed=300
    )

    reserved = reserve(ctx["order"]["id"])
    assert reserved["points_value_cents"] == 1500
    assert reserved["total_due_cents"] == 3500
    assert read_customer(customer["id"])["points_balance"] == 200

    validate_success(
        api.cancel_order(
            ctx["order"]["id"], associate_headers, {"reason": "CUSTOMER_CHANGED_MIND"}
        )
    )

    final = read_customer(customer["id"])
    assert final["points_balance"] == 500
    assert_points_ledger_conserved(final, read_ledger(customer["id"]))


def test_the_redeem_entry_is_compensated_not_deleted(api, associate_headers):
    """PRD §2.7: "There is no way to move a balance except by appending an entry, and
    every entry records `balance_after` — the customer's `points_balance` immediately
    after that entry was appended — so the ledger is self-auditing."
    PRD §3.4: "Ledger entries can be listed and filtered by `customer_id` and by
    `order_id`, and are returned oldest first."

    Design: Difficulty/compensating_invariant/points_balance_conserved_across_redeem_and_cancel_reversal
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer(initial_points=500)
    ctx = setup_draft_order(
        customer=customer, catalog=catalog, quantity=2, points_redeemed=300
    )
    reserve(ctx["order"]["id"])
    validate_success(api.cancel_order(ctx["order"]["id"], associate_headers))

    entries = read_ledger(customer["id"])
    assert_ledger_entry_sequence(
        entries, [("SEED", 500), ("REDEEM", -300), ("REVERSAL", 300)]
    )
    assert [e["balance_after"] for e in entries] == [500, 200, 500], (
        "each entry records the balance immediately after it was appended"
    )
    assert sum(e["delta_points"] for e in entries) == 500


def test_cancelling_a_captured_order_refunds_the_full_total_due(api, associate_headers):
    """PRD §3.7: "Meanwhile the payment dimension is settled: an `AUTHORIZED` order
    moves to `VOIDED` with no cash movement, and a `CAPTURED` order moves to `REFUNDED`
    with the order's `refunded_cents` set to its full `total_due_cents`."
    PRD §3.7: "Cancelling a `RESERVED` order — or one already staged at
    `READY_FOR_PICKUP`, which unwinds identically — must undo every effect the
    reservation caused, and it does so in a chain."

    Design: Corner/state_machines/order_cancel_after_capture_refunds_full_total_due
    """
    ctx = setup_captured_order(quantity=2)

    cancelled = validate_success(api.cancel_order(ctx["order"]["id"], associate_headers))

    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["refunded_cents"] == 5000, "the full total_due of 2 units at 2500"

    lot = read_lot(ctx["lot"]["id"])
    assert_lot_counters(lot, on_hand_units=10, reserved_units=0, sold_units=0)
    assert read_customer(ctx["customer"]["id"])["qualifying_spend_cents"] == 0, (
        "an order that was never fulfilled never counted toward spend"
    )


def test_cancelling_a_cancelled_order_is_rejected_and_does_not_re_compensate(
    api, associate_headers
):
    """PRD §3.7: "`fulfillment_status` runs `DRAFT`, `RESERVED`, `READY_FOR_PICKUP`,
    `PICKED_UP`, `SHIPPED` and `CANCELLED`, with `PICKED_UP`, `SHIPPED` and `CANCELLED`
    terminal."
    PRD §2.9: "7. State — the target resource is in a state from which the requested
    transition is declared. Order actions (line addition, reserve, payment, fulfilment,
    cancel) report `ERR_INVALID_ORDER_STATE`; booking actions report
    `ERR_INVALID_BOOKING_STATE`; return creation and return decisions report
    `ERR_INVALID_RETURN_STATE`. All are HTTP 409."

    Design: Corner/state_machines/cancel_a_cancelled_order_returns_invalid_order_state
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer(initial_points=500)
    ctx = setup_draft_order(
        customer=customer, catalog=catalog, quantity=2, points_redeemed=300
    )
    reserve(ctx["order"]["id"])
    validate_success(api.cancel_order(ctx["order"]["id"], associate_headers))
    assert read_customer(customer["id"])["points_balance"] == 500

    resp = api.cancel_order(ctx["order"]["id"], associate_headers)

    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value)

    assert read_customer(customer["id"])["points_balance"] == 500, (
        "the reversal must not run a second time (500, not 800)"
    )
    assert len(read_ledger(customer["id"])) == 3, "no fourth ledger entry was appended"
