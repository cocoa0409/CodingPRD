"""The four conserved quantities of the fulfillment network.

Each test drives one leg of a round trip — the leg that consumes or reserves the
quantity, or the compensating leg that restores or releases it — and asserts the
conserved identity at that point.
"""

import pytest

from test_helpers import (
    CARRIER,
    PLANNER,
    accept,
    adjust_inventory,
    api_client,
    assert_available_to_promise_consistent,
    assert_order_line_units_conserved,
    assert_pickup_parcels_conserved,
    assert_reserved_units_conserved,
    cancel_assignment,
    cancel_pickup,
    commit_routing,
    find_assignment,
    find_assignments,
    find_notifications,
    find_routing_runs,
    inventory_adjustment_payload,
    inventory_version,
    make_store_associate_headers,
    pack,
    pick_full,
    pick_units,
    pickup_version,
    read_assignment,
    read_inventory,
    read_order,
    read_order_line,
    read_pickup,
    read_store,
    reject,
    schedule_pickup,
    set_clock,
    setup_network,
    setup_order_with_lines,
    ship,
    ship_payload,
    validate_error,
)

# The five assignment statuses that hold a reservation (PRD §2.9).
_HOLDING_STATUSES = ("ASSIGNED", "ACCEPTED", "PICKED", "SHORT_PICKED", "PACKED")


def _holding_labor_minutes(store_id: str) -> float:
    """Sum labor_minutes_reserved over the node's assignments at a holding status."""
    return sum(
        row["labor_minutes_reserved"]
        for row in find_assignments(store_id=store_id)
        if row["status"] in _HOLDING_STATUSES
    )


# ======================================================================
# Conserved quantity 1 — promise-able units at a node
# ======================================================================


def _committed_two_node_network() -> dict:
    """Clock 09:00; S1 stocks SKU-A 12 on hand / 2 safety (so 12 == 10 + 0 + 2)
    and S3 stocks it 5 / 2 (so 5 == 3 + 0 + 2). One two-unit GROUND order to
    destination zone 4 is then committed across the network."""
    net = setup_network(
        node_presets=("S1", "S3"),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2), ("S3", "SKU-A", 5, 2)],
    )
    built = setup_order_with_lines(
        [(net["skus"]["SKU-A"]["id"], 2, 4500)],
        order_code="O-7001",
        customer_ref="C-51",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    run = commit_routing(built["order"]["id"])
    return {
        "s1": net["stores"]["S1"],
        "s3": net["stores"]["S3"],
        "sku": net["skus"]["SKU-A"],
        "inv_s1": net["inventories"][("S1", "SKU-A")],
        "inv_s3": net["inventories"][("S3", "SKU-A")],
        "order": built["order"],
        "line": built["lines"][0],
        "run": run,
    }


class TestPromiseableUnitsAtANode:
    def test_commit_moves_units_from_promise_able_into_reserved(self):
        """PRD §2.9: "For every pairing of a node and a SKU, whenever `on_hand_units` minus `reserved_units` minus `safety_stock_units` is not negative, `on_hand_units` equals the sum of `available_to_promise_units`, `reserved_units` and `safety_stock_units`."
        PRD §3.4: "On a `COMMIT` run each winner also produces a `FulfillmentAssignment` and its `AssignmentLine` rows, as described in §3.5, which raises that node's inventory `reserved_units`, `units_committed_epoch` and `reserved_labor_minutes` and recomputes its `eligibility_score`."
        PRD §3.1: "A row's `reserved_units` is always the sum, over the assignment lines whose owning assignment belongs to this node and whose served demand line references this SKU, of that line's `units_assigned` minus its `units_cancelled`, counting only assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
        PRD §3.1: "`available_to_promise_units` is recomputed from the formula above whenever `reserved_units` moves, whenever the row is adjusted, and at row creation."

        Design: Difficulty/compensating_invariant/inventory_reservation_round_trip_restores_available_to_promise
        """
        ctx = _committed_two_node_network()

        winner = find_assignment(
            order_id=ctx["order"]["id"], store_id=ctx["s3"]["id"]
        )
        assert winner["status"] == "ASSIGNED", (
            "the committed assignment starts at ASSIGNED"
        )
        assert winner["assigned_units"] == 2, (
            "the winner covers the whole two-unit line"
        )

        reserved_row = read_inventory(ctx["inv_s3"]["id"])
        assert reserved_row["on_hand_units"] == 5, "a commit never moves on_hand_units"
        assert reserved_row["reserved_units"] == 2, (
            "the two committed units are now reserved at the winning node"
        )
        assert reserved_row["safety_stock_units"] == 2, "the buffer is untouched"
        assert reserved_row["available_to_promise_units"] == 1, (
            "5 == 1 + 2 + 2: the commit consumed two promise-able units"
        )
        assert_available_to_promise_consistent(reserved_row)
        assert_reserved_units_conserved(reserved_row, [winner])

        untouched_row = read_inventory(ctx["inv_s1"]["id"])
        assert untouched_row["reserved_units"] == 0, (
            "the node that lost the waterfall reserves nothing"
        )
        assert untouched_row["available_to_promise_units"] == 10, (
            "12 == 10 + 0 + 2 still holds at the unselected node"
        )
        assert_available_to_promise_consistent(untouched_row)

    def test_adjustment_below_reserved_units_cannot_strand_a_promised_unit(self):
        """PRD §3.1: "Only then is the promise check applied, because an adjustment may not strand units already promised to customers: a `counted_on_hand_units` below the row's current `reserved_units` is rejected with `ERR_INVENTORY_BELOW_RESERVED`."
        PRD §2.9: "For every pairing of a node and a SKU, whenever `on_hand_units` minus `reserved_units` minus `safety_stock_units` is not negative, `on_hand_units` equals the sum of `available_to_promise_units`, `reserved_units` and `safety_stock_units`."
        PRD §3.1: "On success `on_hand_units` is overwritten with `counted_on_hand_units`, `last_adjustment_reason` records the supplied `reason`, `available_to_promise_units` is recomputed, the node's `eligibility_score` is recomputed, and the row's `version` increments."

        Design: Difficulty/compensating_invariant/inventory_reservation_round_trip_restores_available_to_promise
        """
        ctx = _committed_two_node_network()
        version_before = inventory_version(ctx["inv_s3"]["id"])

        response = api_client.adjust_store_inventory(
            ctx["inv_s3"]["id"],
            inventory_adjustment_payload(
                version_before, 1, "SHRINK", safety_stock_units=0
            ),
            PLANNER,
        )
        validate_error(response, "ERR_INVENTORY_BELOW_RESERVED")

        row = read_inventory(ctx["inv_s3"]["id"])
        assert row["on_hand_units"] == 5, "the refused adjustment wrote no on-hand count"
        assert row["reserved_units"] == 2, "the promised units are still reserved"
        assert row["safety_stock_units"] == 2, "the buffer was not replaced"
        assert row["available_to_promise_units"] == 1, (
            "the refused adjustment leaves 5 == 1 + 2 + 2 intact"
        )
        assert row["last_adjustment_reason"] is None, (
            "last_adjustment_reason is only written on success"
        )
        assert row["version"] == version_before, (
            "a refused adjustment mutates nothing, so version does not move"
        )
        assert_available_to_promise_consistent(row)

    def test_reject_returns_available_to_promise_to_its_pre_action_value(self):
        """PRD §2.9: "A forward action such as a routing commit and its compensating action — a reject, a cancel, or a supersede — must return `available_to_promise_units` to exactly its pre-action value."
        PRD §3.7: "Rejection sets `status` to `REJECTED`, stores the `reject_reason_code`, and sets every assignment line's `units_cancelled` equal to its `units_assigned`."
        PRD §3.7: "Second, because the node's reservations dropped, its inventory `reserved_units` decreases and `available_to_promise_units` is recomputed, while its `units_committed_epoch` and `reserved_labor_minutes` decrease, which in turn recomputes that node's `eligibility_score`."
        PRD §3.7: "Fourth, that run's waterfall may create a replacement assignment at the winning node whose `reroute_generation` is one greater than the rejected assignment's, which reserves the winning node's inventory `reserved_units` and raises its `units_committed_epoch` and `reserved_labor_minutes`."

        Design: Difficulty/compensating_invariant/inventory_reservation_round_trip_restores_available_to_promise
        """
        ctx = _committed_two_node_network()
        rejected = find_assignment(
            order_id=ctx["order"]["id"], store_id=ctx["s3"]["id"]
        )
        reserved_before_release = (
            read_inventory(ctx["inv_s3"]["id"])["reserved_units"]
            + read_inventory(ctx["inv_s1"]["id"])["reserved_units"]
        )

        reject(rejected["id"], ctx["s3"]["id"], "NO_STOCK_ON_FLOOR")

        released = read_assignment(rejected["id"])
        assert released["status"] == "REJECTED", "the assignment is now REJECTED"
        assert released["reject_reason_code"] == "NO_STOCK_ON_FLOOR", (
            "the supplied reject_reason_code is stored"
        )

        released_row = read_inventory(ctx["inv_s3"]["id"])
        assert released_row["on_hand_units"] == 5, (
            "a reject leaves on_hand_units untouched"
        )
        assert released_row["reserved_units"] == 0, "the reservation is dropped"
        assert released_row["available_to_promise_units"] == 3, (
            "back to the exact pre-commit decomposition 5 == 3 + 0 + 2"
        )
        assert_available_to_promise_consistent(released_row)

        rejecting_node = read_store(ctx["s3"]["id"])
        assert rejecting_node["units_committed_epoch"] == 0, (
            "the rejecting node committed no units any more"
        )
        assert rejecting_node["reserved_labor_minutes"] == pytest.approx(
            0.00, abs=0.01
        ), "the rejecting node's labour reservation is released too"
        assert rejecting_node["eligibility_score"] == pytest.approx(88.00, abs=0.01), (
            "the rejecting node rescored on its released reservation levels"
        )

        replacement = find_assignment(
            order_id=ctx["order"]["id"], store_id=ctx["s1"]["id"]
        )
        assert replacement["status"] == "ASSIGNED", (
            "the reroute created a live replacement assignment"
        )
        assert replacement["assigned_units"] == 2, (
            "the replacement carries the whole released allocation"
        )
        assert replacement["reroute_generation"] == 1, (
            "reroute_generation is one greater than the rejected assignment's 0"
        )

        winning_row = read_inventory(ctx["inv_s1"]["id"])
        assert winning_row["reserved_units"] == 2, (
            "the reservation moved to the rerouted node"
        )
        assert winning_row["available_to_promise_units"] == 8, (
            "12 == 8 + 2 + 2 at the rerouted node"
        )
        assert_available_to_promise_consistent(winning_row)
        assert_reserved_units_conserved(winning_row, [replacement])

        winning_node = read_store(ctx["s1"]["id"])
        assert winning_node["reserved_labor_minutes"] == pytest.approx(18.00, abs=0.01), (
            "the rerouted node now holds the 12 + 3 x 2 labour standard"
        )
        assert winning_node["eligibility_score"] == pytest.approx(70.48, abs=0.01), (
            "the rerouted node rescored on its raised reservation levels"
        )

        reserved_after_release = (
            released_row["reserved_units"] + winning_row["reserved_units"]
        )
        assert reserved_before_release == 2, (
            "two units were reserved across the network before the reject"
        )
        assert reserved_after_release == reserved_before_release, (
            "no unit was created or destroyed by the release — only the owning node "
            f"changed ({reserved_before_release} != {reserved_after_release})"
        )

    def test_safety_buffer_raise_clamps_promise_able_units_at_zero(self):
        """PRD §3.1: "Creation sets `reserved_units` to 0, leaves `last_adjustment_reason` null, and derives `available_to_promise_units` as the larger of 0 and the result of taking `on_hand_units`, subtracting `reserved_units`, then subtracting `safety_stock_units`."
        PRD §2.9: "For every pairing of a node and a SKU, whenever `on_hand_units` minus `reserved_units` minus `safety_stock_units` is not negative, `on_hand_units` equals the sum of `available_to_promise_units`, `reserved_units` and `safety_stock_units`."
        PRD §3.1: "On success `on_hand_units` is overwritten with `counted_on_hand_units`, `last_adjustment_reason` records the supplied `reason`, `available_to_promise_units` is recomputed, the node's `eligibility_score` is recomputed, and the row's `version` increments."

        Design: Difficulty/compensating_invariant/inventory_reservation_round_trip_restores_available_to_promise
        """
        ctx = _committed_two_node_network()
        rejected = find_assignment(
            order_id=ctx["order"]["id"], store_id=ctx["s3"]["id"]
        )
        reject(rejected["id"], ctx["s3"]["id"], "NO_STOCK_ON_FLOOR")

        # An unreserved row keeps the identity at whatever buffer it is given.
        adjust_inventory(
            ctx["inv_s3"]["id"], 5, "MARKDOWN_PULL", safety_stock_units=4
        )
        rebuffered = read_inventory(ctx["inv_s3"]["id"])
        assert rebuffered["on_hand_units"] == 5, "the counted figure is written outright"
        assert rebuffered["reserved_units"] == 0, "the released row reserves nothing"
        assert rebuffered["safety_stock_units"] == 4, "the replacement buffer is stored"
        assert rebuffered["available_to_promise_units"] == 1, (
            "5 == 1 + 0 + 4 at the new buffer"
        )
        assert rebuffered["last_adjustment_reason"] == "MARKDOWN_PULL", (
            "last_adjustment_reason records the supplied reason"
        )
        assert_available_to_promise_consistent(rebuffered)

        # Raising the buffer past on_hand minus reserved suspends the identity
        # through the max(0, ...) clamp without destroying a reserved unit.
        adjust_inventory(
            ctx["inv_s1"]["id"], 12, "MARKDOWN_PULL", safety_stock_units=11
        )
        clamped = read_inventory(ctx["inv_s1"]["id"])
        assert clamped["on_hand_units"] == 12, "the counted figure is written outright"
        assert clamped["reserved_units"] == 2, (
            "the rerouted allocation is still promised to the customer"
        )
        assert clamped["safety_stock_units"] == 11, "the replacement buffer is stored"
        assert clamped["available_to_promise_units"] == 0, (
            "on_hand 12 minus reserved 2 minus safety 11 is negative, so the "
            "promise-able figure clamps at 0"
        )
        assert_available_to_promise_consistent(clamped)


# ======================================================================
# Conserved quantity 2 — node labour minutes
# ======================================================================


def _two_assignments_holding_labor() -> dict:
    """Clock 09:00; S1 is the only node (standard 12 minutes per order plus 3
    per unit, 480 staffed) stocking SKU-A 20 / 2, with MEDIUM_BOX packaging and
    a 09:15Z-12:00Z pickup window. A three-unit order and a one-unit order both
    commit to S1, and the three-unit assignment is accepted at 09:05."""
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 20, 2)],
        packaging=[("S1", "MEDIUM_BOX", 5, 1)],
    )
    store = net["stores"]["S1"]
    sku = net["skus"]["SKU-A"]
    pickup = schedule_pickup(
        store["id"],
        window_start_utc="2026-08-03T09:15:00Z",
        window_end_utc="2026-08-03T12:00:00Z",
        parcel_capacity=4,
    )

    first = setup_order_with_lines(
        [(sku["id"], 3, 4500)],
        order_code="O-7101",
        customer_ref="C-61",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    commit_routing(first["order"]["id"])
    big = find_assignment(order_id=first["order"]["id"], store_id=store["id"])

    second = setup_order_with_lines(
        [(sku["id"], 1, 4500)],
        order_code="O-7102",
        customer_ref="C-62",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    commit_routing(second["order"]["id"])
    small = find_assignment(order_id=second["order"]["id"], store_id=store["id"])

    set_clock("2026-08-03T09:05:00Z")
    accept(big["id"], store["id"])

    return {
        "store": store,
        "sku": sku,
        "inventory": net["inventories"][("S1", "SKU-A")],
        "supply": net["supplies"][("S1", "MEDIUM_BOX")],
        "pickup": pickup,
        "big_order": first["order"],
        "big_line": first["lines"][0],
        "big": read_assignment(big["id"]),
        "small_order": second["order"],
        "small_line": second["lines"][0],
        "small": read_assignment(small["id"]),
    }


def _short_pick_and_pack(ctx: dict) -> None:
    """Pick two of the three units at 09:10, then pack at 09:20."""
    set_clock("2026-08-03T09:10:00Z")
    pick_units(ctx["big"]["id"], ctx["store"]["id"], {0: 2})
    set_clock("2026-08-03T09:20:00Z")
    pack(ctx["big"]["id"], ctx["store"]["id"], "MEDIUM_BOX")


class TestNodeLabourMinutes:
    def test_short_pick_and_pack_keep_holding_the_full_labour_standard(self):
        """PRD §2.9: "A node's `reserved_labor_minutes` equals the sum of `labor_minutes_reserved` over that node's assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
        PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."
        PRD §3.5: "Crucially, `labor_minutes_reserved` is *not* rewritten on a short pick — the labour standard was already committed — and only the final cost variant reflects the units actually picked."
        PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."

        Design: Difficulty/compensating_invariant/labor_minute_reservations_release_the_full_standard_on_ship_and_cancel
        """
        ctx = _two_assignments_holding_labor()
        store_id = ctx["store"]["id"]

        assert ctx["big"]["labor_minutes_reserved"] == pytest.approx(21.00, abs=0.01), (
            "the three-unit assignment reserved 12 + 3 x 3 minutes"
        )
        assert ctx["small"]["labor_minutes_reserved"] == pytest.approx(
            15.00, abs=0.01
        ), "the one-unit assignment reserved 12 + 3 x 1 minutes"
        assert read_store(store_id)["reserved_labor_minutes"] == pytest.approx(
            36.00, abs=0.01
        ), "the node holds both standards while both assignments are non-terminal"

        set_clock("2026-08-03T09:10:00Z")
        pick_units(ctx["big"]["id"], store_id, {0: 2})

        short_picked = read_assignment(ctx["big"]["id"])
        assert short_picked["status"] == "SHORT_PICKED", (
            "picking 2 of 3 units lands on SHORT_PICKED"
        )
        assert short_picked["picked_units"] == 2, "picked_units is stored"
        assert short_picked["shortfall_units"] == 1, (
            "shortfall_units is assigned_units minus picked_units"
        )
        assert short_picked["labor_minutes_reserved"] == pytest.approx(
            21.00, abs=0.01
        ), "the shortfall never re-prices the committed labour standard"

        assert read_store(store_id)["reserved_labor_minutes"] == pytest.approx(
            36.00, abs=0.01
        ), "the short pick released units but no labour minutes"
        assert _holding_labor_minutes(store_id) == pytest.approx(36.00, abs=0.01), (
            "the node figure still equals the sum over the holding statuses"
        )

        set_clock("2026-08-03T09:20:00Z")
        pack(ctx["big"]["id"], store_id, "MEDIUM_BOX")

        packed = read_assignment(ctx["big"]["id"])
        assert packed["status"] == "PACKED", "the short-picked branch rejoins at pack"
        assert packed["labor_minutes_actual"] == pytest.approx(15.00, abs=0.01), (
            "09:20 pack minus the 09:05 accept is 15 whole minutes"
        )
        assert packed["labor_minutes_reserved"] == pytest.approx(21.00, abs=0.01), (
            "the reserved standard is still the committed 21 minutes"
        )
        assert read_store(store_id)["reserved_labor_minutes"] == pytest.approx(
            36.00, abs=0.01
        ), "PACKED is one of the five holding statuses, so nothing is released"
        assert _holding_labor_minutes(store_id) == pytest.approx(36.00, abs=0.01), (
            "the node figure still equals the sum over the holding statuses"
        )

    def test_ship_releases_the_full_standard_not_the_clocked_actual(self):
        """PRD §2.9: "Reaching `SHIPPED`, `REJECTED` or `CANCELLED` releases the full labour standard, so a create-then-release round trip leaves `reserved_labor_minutes` exactly where it started — even when the assignment was short-picked, because a shortfall never re-prices the labour standard."
        PRD §3.6: "The node's `reserved_labor_minutes` is reduced by the assignment's `labor_minutes_reserved` and its `eligibility_score` is recomputed."
        PRD §3.6: "For each line's SKU, the node's inventory row has `on_hand_units` reduced by the line's `units_picked` and `reserved_units` reduced by its `units_assigned`, and `available_to_promise_units` is recomputed."
        PRD §3.6: "Each served demand line has its `shipped_units` raised by the line's `units_picked` and its `assigned_units` reduced by its `units_assigned`."

        Design: Difficulty/compensating_invariant/labor_minute_reservations_release_the_full_standard_on_ship_and_cancel
        """
        ctx = _two_assignments_holding_labor()
        store_id = ctx["store"]["id"]
        _short_pick_and_pack(ctx)

        set_clock("2026-08-03T09:30:00Z")
        ship(ctx["big"]["id"], store_id, ctx["pickup"]["id"])

        shipped = read_assignment(ctx["big"]["id"])
        assert shipped["status"] == "SHIPPED", "the tender moves PACKED to SHIPPED"
        assert shipped["labor_minutes_reserved"] == pytest.approx(21.00, abs=0.01), (
            "the row still carries the standard it committed"
        )

        node = read_store(store_id)
        assert node["reserved_labor_minutes"] == pytest.approx(15.00, abs=0.01), (
            "SHIPPED released the full 21.00 standard, not the 15.00 clocked actual, "
            "leaving only the other assignment's 15.00"
        )
        assert _holding_labor_minutes(store_id) == pytest.approx(15.00, abs=0.01), (
            "the node figure equals the sum over the remaining holding statuses"
        )

        row = read_inventory(ctx["inventory"]["id"])
        assert row["on_hand_units"] == 18, (
            "the ship decremented on_hand_units by the two picked units"
        )
        assert row["reserved_units"] == 1, (
            "only the other assignment's single unit is still reserved"
        )
        assert row["safety_stock_units"] == 2, "the buffer is untouched"
        assert row["available_to_promise_units"] == 15, "18 == 15 + 1 + 2"
        assert_available_to_promise_consistent(row)

        line = read_order_line(ctx["big_line"]["id"])
        assert line["assigned_units"] == 0, "the shipped allocation left assigned_units"
        assert line["shipped_units"] == 2, "the picked units landed in shipped_units"
        assert line["cancelled_units"] == 0, "nothing was cancelled to the customer"
        assert line["dc_fallback_units"] == 0, "nothing went to the distribution centre"
        assert line["open_units"] == 1, "the short-picked unit is open again"
        assert_order_line_units_conserved(line)

        order = read_order(ctx["big_order"]["id"])
        assert order["shipped_units"] == 2, "the order counts the two shipped units"
        assert order["fulfillment_status"] == "PARTIALLY_SHIPPED", (
            "two of the three demanded units shipped, with nothing cancelled and "
            "nothing handed to the distribution centre"
        )

    def test_cancel_closes_the_labour_round_trip_back_to_zero(self):
        """PRD §2.9: "Reaching `SHIPPED`, `REJECTED` or `CANCELLED` releases the full labour standard, so a create-then-release round trip leaves `reserved_labor_minutes` exactly where it started — even when the assignment was short-picked, because a shortfall never re-prices the labour standard."
        PRD §3.7: "All four permitted source states carry the same cascade: `status` becomes `CANCELLED` and the `cancel_reason_code` is stored; each assignment line's `units_cancelled` becomes its `units_assigned` minus its `units_picked`, releasing that much of the served demand line's `assigned_units`; the node's inventory `reserved_units`, `units_committed_epoch` and `reserved_labor_minutes` all decrease and its `eligibility_score` is recomputed — including, for a `PICKED` or `SHORT_PICKED` source, the units already physically picked, which are returned to the node's reservations and then released; when `reroute` is true a system reroute run excluding this node is created, at `initiated_by` `SYSTEM_REROUTE` or, for a deactivation cascade, `SYSTEM_DEACTIVATION`, while when `reroute` is false the released units become the demand lines' `cancelled_units`; a customer notification is emitted; the order's `routing_status` and `fulfillment_status` are re-derived; and the assignment's `version` increments."
        PRD §3.7: "The `notification_type` is chosen by a single pinned rule, first match winning: `CANCELLATION_FULL` when the event is a customer order cancel and the cancelled units equal the order's `total_units`; otherwise `CANCELLATION_PARTIAL` when the event is a customer order cancel or an assignment cancel with `reroute` false; otherwise `DC_FALLBACK` when the event raised the demand lines' `dc_fallback_units`; otherwise `REJECTION_REROUTED` when the event is a rejection whose reroute run created at least one replacement assignment; otherwise `SHORT_PICK_REROUTED` when the event is a short pick whose reroute run created at least one replacement assignment; otherwise `NODE_DEACTIVATED_REROUTED` when the event is a deactivation-driven retry run that created at least one replacement assignment; otherwise `UNROUTABLE`, meaning the released units are still open."
        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."

        Design: Difficulty/compensating_invariant/labor_minute_reservations_release_the_full_standard_on_ship_and_cancel
        """
        ctx = _two_assignments_holding_labor()
        store_id = ctx["store"]["id"]
        _short_pick_and_pack(ctx)

        set_clock("2026-08-03T09:30:00Z")
        ship(ctx["big"]["id"], store_id, ctx["pickup"]["id"])

        set_clock("2026-08-03T09:35:00Z")
        cancel_assignment(ctx["small"]["id"], "CUSTOMER_REQUEST", reroute=False)

        node = read_store(store_id)
        assert node["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
            "with no assignment left at a holding status the node is back to 0.00, "
            "exactly where the round trip started"
        )
        assert _holding_labor_minutes(store_id) == pytest.approx(0.00, abs=0.01), (
            "the sum over the holding statuses is empty"
        )

        cancelled = read_assignment(ctx["small"]["id"])
        assert cancelled["status"] == "CANCELLED", "the assignment is CANCELLED"
        assert cancelled["cancel_reason_code"] == "CUSTOMER_REQUEST", (
            "the supplied cancel_reason_code is stored"
        )
        assert cancelled["labor_minutes_reserved"] == pytest.approx(15.00, abs=0.01), (
            "the committed standard is never rewritten on the row itself"
        )

        row = read_inventory(ctx["inventory"]["id"])
        assert row["on_hand_units"] == 18, "a cancel leaves on_hand_units untouched"
        assert row["reserved_units"] == 0, "no reservation is left at the node"
        assert row["available_to_promise_units"] == 16, "18 == 16 + 0 + 2"
        assert_available_to_promise_consistent(row)

        line = read_order_line(ctx["small_line"]["id"])
        assert line["assigned_units"] == 0, "the allocation was released"
        assert line["shipped_units"] == 0, "nothing shipped on that order"
        assert line["cancelled_units"] == 1, (
            "a cancel with reroute false turns the released unit into cancelled_units"
        )
        assert line["dc_fallback_units"] == 0, "nothing went to the distribution centre"
        assert line["open_units"] == 0, "no unit is left open"
        assert_order_line_units_conserved(line)

        notifications = find_notifications(order_id=ctx["small_order"]["id"])
        assert len(notifications) == 1, (
            "an assignment cancel emits exactly one customer notification"
        )
        assert notifications[0]["notification_type"] == "CANCELLATION_PARTIAL", (
            "an assignment cancel with reroute false reports CANCELLATION_PARTIAL"
        )
        assert notifications[0]["units_affected"] == 1, (
            "units_affected counts the single unit the cancel removed"
        )

        assert read_order(ctx["small_order"]["id"])["routing_status"] == "UNROUTABLE", (
            "covered units is 0, and that clause is matched before the ROUTED clause"
        )


# ======================================================================
# Conserved quantity 3 — customer demand units
# ======================================================================


def _four_node_split_order() -> dict:
    """Clock 09:00; four nodes created in the order S3, S1, S5, S2, each stocking
    SKU-A 3 on hand / 2 safety so every node can promise exactly one unit. S3
    also carries MEDIUM_BOX packaging and a 09:15Z-12:00Z pickup window. One
    four-unit GROUND line to destination zone 4 is committed."""
    net = setup_network(
        node_presets=("S3", "S1", "S5", "S2"),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[
            ("S3", "SKU-A", 3, 2),
            ("S1", "SKU-A", 3, 2),
            ("S5", "SKU-A", 3, 2),
            ("S2", "SKU-A", 3, 2),
        ],
        packaging=[("S3", "MEDIUM_BOX", 10, 2)],
    )
    pickup = schedule_pickup(
        net["stores"]["S3"]["id"],
        window_start_utc="2026-08-03T09:15:00Z",
        window_end_utc="2026-08-03T12:00:00Z",
        parcel_capacity=4,
    )
    built = setup_order_with_lines(
        [(net["skus"]["SKU-A"]["id"], 4, 4500)],
        order_code="O-7201",
        customer_ref="C-71",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    run = commit_routing(built["order"]["id"])
    order_id = built["order"]["id"]
    assignments = {}
    for preset, store in net["stores"].items():
        rows = find_assignments(order_id=order_id, store_id=store["id"])
        if rows:
            assignments[preset] = rows[0]
    return {
        "stores": net["stores"],
        "inventories": net["inventories"],
        "pickup": pickup,
        "order": built["order"],
        "line": built["lines"][0],
        "run": run,
        "assignments": assignments,
    }


class TestCustomerDemandUnits:
    def test_commit_splits_the_line_into_assigned_and_dc_fallback_units(self):
        """PRD §2.9: "For every demand line, `quantity` equals the sum of `assigned_units`, `shipped_units`, `cancelled_units`, `dc_fallback_units` and `open_units`."
        PRD §2.9: "At the order level, `total_units` equals the sum of every demand line's `quantity`, and `unassigned_units` equals the sum of every demand line's `open_units`."
        PRD §3.4: "If it ended because three nodes had been selected while units still remained, those units become each line's `dc_fallback_units` — a handoff to the distribution centre — and a customer notification of type `DC_FALLBACK` is emitted."
        PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
        PRD §3.4: "`candidate_count` records how many candidate rows this run persisted across all iterations."
        PRD §3.4: "A planner's `COMMIT` run on an order at `UNROUTED` lands it on `ROUTED` when every open unit is covered, on `PARTIALLY_ROUTED` when some but not all are covered — with the shortfall recorded in `unfulfillable_units` and left in `open_units` unless the three-split ceiling converted it to `dc_fallback_units`, which is the only case in which that run emits a `DC_FALLBACK` notification — and on `UNROUTABLE` when the pool is empty at the first iteration."

        Design: Difficulty/compensating_invariant/order_demand_units_stay_conserved_across_all_five_buckets
        """
        ctx = _four_node_split_order()

        run = ctx["run"]
        assert run["status"] == "COMMITTED", "the run committed its three winners"
        assert run["selected_store_count"] == 3, "three nodes were selected"
        assert run["planned_split_count"] == 3, (
            "planned_split_count equals the number of nodes selected"
        )
        assert run["unfulfillable_units"] == 1, (
            "one unit of remaining demand was left when the loop stopped"
        )
        assert run["candidate_count"] == 12, (
            "all four nodes were evaluated in each of the three iterations"
        )

        assert set(ctx["assignments"]) == {"S3", "S1", "S5"}, (
            "the waterfall selected S3, then S1, then S5"
        )
        for preset, assignment in ctx["assignments"].items():
            assert assignment["assigned_units"] == 1, (
                f"{preset} could only promise one unit, so it was allocated one"
            )

        line = read_order_line(ctx["line"]["id"])
        assert line["quantity"] == 4, "the line still demands four units"
        assert line["assigned_units"] == 3, "three units are held by live assignments"
        assert line["shipped_units"] == 0, "nothing has shipped yet"
        assert line["cancelled_units"] == 0, "nothing has been cancelled"
        assert line["dc_fallback_units"] == 1, (
            "the unit stranded at the three-split ceiling went to the "
            "distribution centre"
        )
        assert line["open_units"] == 0, (
            "a unit converted to dc_fallback_units is no longer open"
        )
        assert_order_line_units_conserved(line)

        order = read_order(ctx["order"]["id"])
        assert order["total_units"] == 4, "total_units is the sum of the line quantities"
        assert order["unassigned_units"] == 0, (
            "unassigned_units is the sum of the lines' open_units"
        )
        assert order["split_count"] == 3, "three live assignments serve the order"
        assert order["routing_status"] == "PARTIALLY_ROUTED", (
            "some but not all units are covered by the network"
        )

        notifications = find_notifications(
            order_id=ctx["order"]["id"], notification_type="DC_FALLBACK"
        )
        assert len(notifications) == 1, (
            "the three-split ceiling emits exactly one DC_FALLBACK notification"
        )
        assert notifications[0]["units_affected"] == 1, (
            "units_affected counts the single unit handed to the distribution centre"
        )

    def test_ship_moves_a_unit_from_assigned_into_shipped(self):
        """PRD §2.9: "For every demand line, `quantity` equals the sum of `assigned_units`, `shipped_units`, `cancelled_units`, `dc_fallback_units` and `open_units`."
        PRD §3.6: "Each served demand line has its `shipped_units` raised by the line's `units_picked` and its `assigned_units` reduced by its `units_assigned`."
        PRD §3.6: "For each line's SKU, the node's inventory row has `on_hand_units` reduced by the line's `units_picked` and `reserved_units` reduced by its `units_assigned`, and `available_to_promise_units` is recomputed."
        PRD §3.6: "From `PENDING`, a ship that leaves the order with `shipped_units` above 0 while `shipped_units` plus the sum of the lines' `cancelled_units` plus `dc_fallback_units` is still strictly below `total_units` moves it to `PARTIALLY_SHIPPED`, recomputing `shipped_units` and refreshing the provisional cost fields."

        Design: Difficulty/compensating_invariant/order_demand_units_stay_conserved_across_all_five_buckets
        """
        ctx = _four_node_split_order()
        shipping_store = ctx["stores"]["S3"]
        shipping_assignment = ctx["assignments"]["S3"]

        set_clock("2026-08-03T09:05:00Z")
        accept(shipping_assignment["id"], shipping_store["id"])
        set_clock("2026-08-03T09:10:00Z")
        pick_full(shipping_assignment["id"], shipping_store["id"])
        set_clock("2026-08-03T09:20:00Z")
        pack(shipping_assignment["id"], shipping_store["id"], "MEDIUM_BOX")
        set_clock("2026-08-03T09:30:00Z")
        ship(shipping_assignment["id"], shipping_store["id"], ctx["pickup"]["id"])

        assert read_assignment(shipping_assignment["id"])["status"] == "SHIPPED", (
            "the tendered parcel reached SHIPPED"
        )

        line = read_order_line(ctx["line"]["id"])
        assert line["assigned_units"] == 2, (
            "the two remaining live assignments still hold two units"
        )
        assert line["shipped_units"] == 1, "the picked unit moved into shipped_units"
        assert line["cancelled_units"] == 0, "nothing has been cancelled"
        assert line["dc_fallback_units"] == 1, "the fallback unit is unchanged"
        assert line["open_units"] == 0, "no unit is open yet"
        assert_order_line_units_conserved(line)

        row = read_inventory(ctx["inventories"][("S3", "SKU-A")]["id"])
        assert row["on_hand_units"] == 2, (
            "on_hand_units dropped by the single picked unit"
        )
        assert row["reserved_units"] == 0, "the ship dropped the reservation"
        assert row["safety_stock_units"] == 2, "the buffer is untouched"
        assert row["available_to_promise_units"] == 0, (
            "2 == 0 + 0 + 2: the whole remainder is floor-presentation buffer"
        )
        assert_available_to_promise_consistent(row)

        order = read_order(ctx["order"]["id"])
        assert order["fulfillment_status"] == "PARTIALLY_SHIPPED", (
            "one unit shipped while shipped plus cancelled plus fallback is below "
            "total_units"
        )
        assert order["total_units"] == 4, "total_units never moves"

    def test_reject_and_cancel_leave_one_unit_in_every_bucket(self):
        """PRD §2.9: "For every demand line, `quantity` equals the sum of `assigned_units`, `shipped_units`, `cancelled_units`, `dc_fallback_units` and `open_units`."
        PRD §2.9: "At the order level, `total_units` equals the sum of every demand line's `quantity`, and `unassigned_units` equals the sum of every demand line's `open_units`."
        PRD §3.7: "First, every served demand line has its `assigned_units` reduced by the corresponding `units_assigned`, so its `open_units` rises."
        PRD §3.4: "If it ended because a candidate pool came up empty, the units simply stay in `open_units` and the order's `routing_status` is re-derived."
        PRD §3.4: "If the pool was already empty on the very first iteration, the run's `status` becomes `NO_ELIGIBLE_NODE` with `selected_store_count` 0 and `unfulfillable_units` equal to the order's `unassigned_units`, a notification of type `UNROUTABLE` is emitted, and no assignment and no reservation change occurs at all."
        PRD §3.4: "A successful run re-derives the order's `routing_status`, recomputes `split_count` — the number of the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — recomputes `provisional_cost_cents`, `dc_baseline_cost_cents` and `cost_index_bps`, and increments the order's `version`."
        PRD §3.4: "`reroute_attempt_count` counts the order's runs whose `initiated_by` is `SYSTEM_REROUTE` or `SYSTEM_DEACTIVATION`."

        Design: Difficulty/compensating_invariant/order_demand_units_stay_conserved_across_all_five_buckets
        """
        ctx = _four_node_split_order()
        stores = ctx["stores"]
        order_id = ctx["order"]["id"]

        set_clock("2026-08-03T09:05:00Z")
        accept(ctx["assignments"]["S3"]["id"], stores["S3"]["id"])
        accept(ctx["assignments"]["S1"]["id"], stores["S1"]["id"])
        set_clock("2026-08-03T09:10:00Z")
        pick_full(ctx["assignments"]["S3"]["id"], stores["S3"]["id"])
        set_clock("2026-08-03T09:20:00Z")
        pack(ctx["assignments"]["S3"]["id"], stores["S3"]["id"], "MEDIUM_BOX")
        set_clock("2026-08-03T09:30:00Z")
        ship(ctx["assignments"]["S3"]["id"], stores["S3"]["id"], ctx["pickup"]["id"])

        # Take the last unreserved node's promise-able units to 0 so the reroute
        # that follows the reject finds an empty candidate pool.
        set_clock("2026-08-03T09:32:00Z")
        adjust_inventory(
            ctx["inventories"][("S2", "SKU-A")]["id"],
            2,
            "SHRINK",
            safety_stock_units=2,
        )
        assert (
            read_inventory(ctx["inventories"][("S2", "SKU-A")]["id"])[
                "available_to_promise_units"
            ]
            == 0
        ), "no node can promise a unit any more"

        set_clock("2026-08-03T09:35:00Z")
        reject(ctx["assignments"]["S5"]["id"], stores["S5"]["id"], "LABOR_UNAVAILABLE")

        reroutes = find_routing_runs(order_id=order_id, initiated_by="SYSTEM_REROUTE")
        assert len(reroutes) == 1, "the reject created exactly one system reroute run"
        assert reroutes[0]["status"] == "NO_ELIGIBLE_NODE", (
            "the reroute's first iteration found an empty candidate pool"
        )
        assert reroutes[0]["selected_store_count"] == 0, (
            "an empty pool selects no node"
        )

        after_reject = read_order(order_id)
        assert after_reject["routing_status"] == "ROUTING", (
            "open units remain, the reroute limit is not reached and a REJECTED "
            "assignment exists"
        )
        assert after_reject["reroute_attempt_count"] == 1, (
            "reroute_attempt_count counts the SYSTEM_REROUTE run"
        )

        released = read_order_line(ctx["line"]["id"])
        assert released["open_units"] == 1, (
            "the reroute exited on an empty pool, so the released unit stays open"
        )
        assert released["dc_fallback_units"] == 1, (
            "an empty pool never converts units to dc_fallback_units"
        )
        assert_order_line_units_conserved(released)

        unroutable = find_notifications(
            order_id=order_id, notification_type="UNROUTABLE"
        )
        assert len(unroutable) == 1, "the stranded release emits one UNROUTABLE notice"
        assert unroutable[0]["units_affected"] == 1, (
            "units_affected counts the single released unit"
        )

        set_clock("2026-08-03T09:40:00Z")
        cancel_assignment(
            ctx["assignments"]["S1"]["id"], "CUSTOMER_REQUEST", reroute=False
        )

        line = read_order_line(ctx["line"]["id"])
        assert line["quantity"] == 4, "the demand line still demands four units"
        assert line["assigned_units"] == 0, "no live assignment holds a unit"
        assert line["shipped_units"] == 1, "one unit shipped from the store network"
        assert line["cancelled_units"] == 1, (
            "the cancel with reroute false turned its unit into cancelled_units"
        )
        assert line["dc_fallback_units"] == 1, "one unit went to the distribution centre"
        assert line["open_units"] == 1, "the rejected unit is still open"
        assert_order_line_units_conserved(line)

        partial = find_notifications(
            order_id=order_id, notification_type="CANCELLATION_PARTIAL"
        )
        assert len(partial) == 1, "the assignment cancel emits one notification"
        assert partial[0]["units_affected"] == 1, (
            "units_affected counts the single cancelled unit"
        )

        order = read_order(order_id)
        assert order["total_units"] == 4, "total_units is the sum of line quantities"
        assert order["unassigned_units"] == 1, (
            "unassigned_units is the sum of the lines' open_units"
        )
        assert order["split_count"] == 1, (
            "only the SHIPPED assignment is neither REJECTED nor CANCELLED"
        )
        assert order["reroute_attempt_count"] == 1, (
            "the cancel with reroute false started no further run"
        )

        for preset in ("S3", "S1", "S5", "S2"):
            node = read_store(stores[preset]["id"])
            assert node["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
                f"{preset} holds no assignment at a holding status any more"
            )

        for preset in ("S1", "S5"):
            row = read_inventory(ctx["inventories"][(preset, "SKU-A")]["id"])
            assert row["reserved_units"] == 0, f"{preset} released its reservation"
            assert row["available_to_promise_units"] == 1, (
                f"3 == 1 + 0 + 2 at {preset}: the released unit is back on the floor"
            )
            assert_available_to_promise_consistent(row)


# ======================================================================
# Conserved quantity 4 — carrier parcel slots
# ======================================================================


def _three_packed_parcels_and_three_windows() -> dict:
    """Clock 09:00; S1 is the only node, stocking SKU-A 20 / 2 with MEDIUM_BOX
    packaging and three non-conflicting two-parcel windows (09:15Z-12:00Z,
    12:30Z-14:00Z and 14:30Z-15:30Z). Three orders — two units, one unit and one
    unit — commit to S1, are accepted at 09:05, picked in full at 09:10 and
    packed in MEDIUM_BOX at 09:20."""
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 20, 2)],
        packaging=[("S1", "MEDIUM_BOX", 5, 1)],
    )
    store = net["stores"]["S1"]
    sku = net["skus"]["SKU-A"]

    first_window = schedule_pickup(
        store["id"],
        window_start_utc="2026-08-03T09:15:00Z",
        window_end_utc="2026-08-03T12:00:00Z",
        parcel_capacity=2,
    )
    second_window = schedule_pickup(
        store["id"],
        window_start_utc="2026-08-03T12:30:00Z",
        window_end_utc="2026-08-03T14:00:00Z",
        parcel_capacity=2,
    )
    untouched_window = schedule_pickup(
        store["id"],
        carrier_code="EXP",
        window_start_utc="2026-08-03T14:30:00Z",
        window_end_utc="2026-08-03T15:30:00Z",
        parcel_capacity=2,
    )

    parcels = []
    for order_code, customer_ref, quantity in (
        ("O-7301", "C-81", 2),
        ("O-7302", "C-82", 1),
        ("O-7303", "C-83", 1),
    ):
        built = setup_order_with_lines(
            [(sku["id"], quantity, 4500)],
            order_code=order_code,
            customer_ref=customer_ref,
            destination_zone=4,
            service_level="GROUND",
            promised_ship_by_utc="2026-08-03T16:00:00Z",
        )
        commit_routing(built["order"]["id"])
        parcels.append(
            {
                "order": built["order"],
                "line": built["lines"][0],
                "assignment": find_assignment(
                    order_id=built["order"]["id"], store_id=store["id"]
                ),
            }
        )

    set_clock("2026-08-03T09:05:00Z")
    for parcel in parcels:
        accept(parcel["assignment"]["id"], store["id"])
    set_clock("2026-08-03T09:10:00Z")
    for parcel in parcels:
        pick_full(parcel["assignment"]["id"], store["id"])
    set_clock("2026-08-03T09:20:00Z")
    for parcel in parcels:
        pack(parcel["assignment"]["id"], store["id"], "MEDIUM_BOX")

    return {
        "store": store,
        "inventory": net["inventories"][("S1", "SKU-A")],
        "first_window": first_window,
        "second_window": second_window,
        "untouched_window": untouched_window,
        "parcels": parcels,
    }


class TestCarrierParcelSlots:
    def test_each_tender_consumes_one_slot_and_capacity_is_never_exceeded(self):
        """PRD §2.9: "A pickup's `reserved_parcels` equals the count of assignments whose `carrier_pickup_id` names that pickup and whose `status` is `SHIPPED`, and `reserved_parcels` never exceeds `parcel_capacity`."
        PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."
        PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."
        PRD §3.6: "A coordinator may also cancel a `SCHEDULED` window, moving it `SCHEDULED → CANCELLED`, which releases its slot so a new overlapping window may be scheduled at the node and increments `version`; cancellation is permitted only while `reserved_parcels` is exactly 0, and a window holding parcels is refused with `ERR_PICKUP_HAS_PARCELS`."

        Design: Difficulty/compensating_invariant/carrier_parcel_slots_equal_the_count_of_shipped_assignments
        """
        ctx = _three_packed_parcels_and_three_windows()
        store_id = ctx["store"]["id"]
        window = ctx["first_window"]
        first, second, third = ctx["parcels"]

        set_clock("2026-08-03T09:30:00Z")
        ship(first["assignment"]["id"], store_id, window["id"])

        after_one = read_pickup(window["id"])
        assert after_one["reserved_parcels"] == 1, (
            "the first tender consumed exactly one parcel slot"
        )
        assert_pickup_parcels_conserved(
            after_one,
            find_assignments(carrier_pickup_id=window["id"], status="SHIPPED"),
        )

        refused_cancel = api_client.cancel_carrier_pickup(window["id"], CARRIER)
        validate_error(refused_cancel, "ERR_PICKUP_HAS_PARCELS")

        still_scheduled = read_pickup(window["id"])
        assert still_scheduled["status"] == "SCHEDULED", (
            "a window holding a parcel cannot be cancelled away"
        )
        assert still_scheduled["reserved_parcels"] == 1, (
            "the refused cancel moved no slot"
        )

        set_clock("2026-08-03T09:32:00Z")
        ship(second["assignment"]["id"], store_id, window["id"])

        at_capacity = read_pickup(window["id"])
        assert at_capacity["reserved_parcels"] == 2, (
            "the second tender consumed the second slot"
        )
        assert at_capacity["reserved_parcels"] == at_capacity["parcel_capacity"], (
            "reserved_parcels has reached parcel_capacity"
        )
        assert_pickup_parcels_conserved(
            at_capacity,
            find_assignments(carrier_pickup_id=window["id"], status="SHIPPED"),
        )

        set_clock("2026-08-03T09:33:00Z")
        refused_ship = api_client.ship_assignment(
            third["assignment"]["id"],
            ship_payload(window["id"], pickup_version(window["id"])),
            make_store_associate_headers(store_id),
        )
        validate_error(refused_ship, "ERR_PICKUP_CAPACITY_EXCEEDED")

        unmoved = read_pickup(window["id"])
        assert unmoved["reserved_parcels"] == 2, (
            "the refused tender did not move the slot counter"
        )
        assert_pickup_parcels_conserved(
            unmoved,
            find_assignments(carrier_pickup_id=window["id"], status="SHIPPED"),
        )

        stayed_packed = read_assignment(third["assignment"]["id"])
        assert stayed_packed["status"] == "PACKED", (
            "the refused tender left the assignment at PACKED"
        )
        assert stayed_packed["carrier_pickup_id"] is None, (
            "no pickup was stored on the refused tender"
        )
        assert stayed_packed["shipped_at"] is None, "shipped_at was not written"

    def test_shipped_parcels_partition_across_windows_and_an_empty_window_cancels(self):
        """PRD §2.9: "A pickup's `reserved_parcels` equals the count of assignments whose `carrier_pickup_id` names that pickup and whose `status` is `SHIPPED`, and `reserved_parcels` never exceeds `parcel_capacity`."
        PRD §3.6: "A coordinator may also cancel a `SCHEDULED` window, moving it `SCHEDULED → CANCELLED`, which releases its slot so a new overlapping window may be scheduled at the node and increments `version`; cancellation is permitted only while `reserved_parcels` is exactly 0, and a window holding parcels is refused with `ERR_PICKUP_HAS_PARCELS`."
        PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."
        PRD §3.6: "The node's `reserved_labor_minutes` is reduced by the assignment's `labor_minutes_reserved` and its `eligibility_score` is recomputed."

        Design: Difficulty/compensating_invariant/carrier_parcel_slots_equal_the_count_of_shipped_assignments
        """
        ctx = _three_packed_parcels_and_three_windows()
        store_id = ctx["store"]["id"]
        first_window = ctx["first_window"]
        second_window = ctx["second_window"]
        untouched_window = ctx["untouched_window"]
        first, second, third = ctx["parcels"]

        set_clock("2026-08-03T09:30:00Z")
        ship(first["assignment"]["id"], store_id, first_window["id"])
        set_clock("2026-08-03T09:32:00Z")
        ship(second["assignment"]["id"], store_id, first_window["id"])

        cancel_pickup(untouched_window["id"])
        cancelled_window = read_pickup(untouched_window["id"])
        assert cancelled_window["status"] == "CANCELLED", (
            "a window that never took a parcel cancels cleanly"
        )
        assert cancelled_window["reserved_parcels"] == 0, (
            "the cancelled window held no slot"
        )

        set_clock("2026-08-03T12:35:00Z")
        ship(third["assignment"]["id"], store_id, second_window["id"])

        retendered = read_assignment(third["assignment"]["id"])
        assert retendered["status"] == "SHIPPED", (
            "the third parcel shipped into the later window"
        )
        assert retendered["carrier_pickup_id"] == second_window["id"], (
            "the tendered window is stored on the assignment"
        )

        full_window = read_pickup(first_window["id"])
        later_window = read_pickup(second_window["id"])
        assert full_window["reserved_parcels"] == 2, (
            "the first window still holds exactly its two parcels"
        )
        assert later_window["reserved_parcels"] == 1, (
            "the later window holds the third parcel"
        )
        assert_pickup_parcels_conserved(
            full_window,
            find_assignments(carrier_pickup_id=first_window["id"], status="SHIPPED"),
        )
        assert_pickup_parcels_conserved(
            later_window,
            find_assignments(carrier_pickup_id=second_window["id"], status="SHIPPED"),
        )

        shipped_rows = find_assignments(store_id=store_id, status="SHIPPED")
        assert len(shipped_rows) == 3, "all three parcels reached SHIPPED"
        assert (
            full_window["reserved_parcels"] + later_window["reserved_parcels"]
            == len(shipped_rows)
        ), "the three SHIPPED assignments partition 2 + 1 with no slot double counted"

        row = read_inventory(ctx["inventory"]["id"])
        assert row["on_hand_units"] == 16, (
            "the four picked units left the building across the three ships"
        )
        assert row["reserved_units"] == 0, "no reservation survives the ships"
        assert row["safety_stock_units"] == 2, "the buffer is untouched"
        assert row["available_to_promise_units"] == 14, "16 == 14 + 0 + 2"
        assert_available_to_promise_consistent(row)

        node = read_store(store_id)
        assert node["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
            "every assignment reached SHIPPED, so all three standards were released"
        )
        assert node["units_committed_epoch"] == 4, (
            "the four units of the epoch's shipped assignments stay committed"
        )
        assert node["eligibility_score"] == pytest.approx(71.20, abs=0.01), (
            "the node rescored on its released labour and its committed units"
        )
