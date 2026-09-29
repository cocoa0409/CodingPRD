"""Role-based access control: who may call which route, and how identity is refused.

Every test builds its own state against an empty database and cites the PRD
sentence that names the authorised role, the scope rule or the refusal code.
"""

from test_helpers import (
    CARE,
    CARRIER,
    PLANNER,
    assert_cost_comparison,
    build_user_headers,
    commit_routing,
    create_carrier_pickup_payload,
    create_order_line_payload,
    create_order_payload,
    create_packaging_supply_payload,
    create_routing_run_payload,
    create_sku_payload,
    create_store_inventory_payload,
    create_store_payload,
    find_assignment,
    find_assignment_lines,
    find_routing_candidates,
    find_routing_runs,
    find_windows,
    inventory_adjustment_payload,
    inventory_version,
    line_pick,
    make_store_associate_headers,
    pick_payload,
    pickup_version,
    read_assignment,
    read_inventory,
    read_order,
    read_packaging,
    read_pickup,
    read_store,
    register_node,
    set_clock,
    setup_committed_assignment,
    setup_network,
    setup_order_with_lines,
    ship_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"


# ======================================================================
# Module-private preambles
# ======================================================================


def _committed_assignment_with_a_pickup() -> dict:
    """Node S1 with SKU-A stock, a carrier pickup window scheduled by the
    coordinator, and one committed A x 2 assignment from order O-K001."""
    return setup_committed_assignment(
        clock=CLOCK,
        with_packaging=False,
        with_pickup=True,
        pickup_start="2026-08-03T08:30:00Z",
        pickup_end="2026-08-03T10:00:00Z",
        parcel_capacity=5,
        order_code="O-K001",
        customer_ref="C-970",
    )


def _committed_assignment_only() -> dict:
    """Node S1 with SKU-A stock and one committed A x 2 assignment, no
    packaging row and no pickup window."""
    return setup_committed_assignment(
        clock=CLOCK,
        with_packaging=False,
        with_pickup=False,
        order_code="O-L001",
        customer_ref="C-980",
    )


def _order_committed_to_the_second_node() -> dict:
    """Two peer nodes S1 and S2 where only S2 stocks SKU-A, so the committed
    A x 2 order lands at S2 and S1 owns none of the fixture's rows."""
    net = setup_network(
        node_presets=("S1", "S2"),
        sku_presets=("SKU-A",),
        clock=CLOCK,
        stock=[("S2", "SKU-A", 12, 2)],
        packaging=[("S2", "MEDIUM_BOX", 4, 1)],
    )
    built = setup_order_with_lines(
        [(net["skus"]["SKU-A"]["id"], 2, 4500)],
        order_code="O-M001",
        customer_ref="C-990",
    )
    run = commit_routing(built["order"]["id"])
    return {
        "s1": net["stores"]["S1"],
        "s2": net["stores"]["S2"],
        "sku": net["skus"]["SKU-A"],
        "inventory": net["inventories"][("S2", "SKU-A")],
        "supply": net["supplies"][("S2", "MEDIUM_BOX")],
        "order": read_order(built["order"]["id"]),
        "run": run,
        "assignment": find_assignment(order_id=built["order"]["id"]),
    }


# ======================================================================
# NetworkPlanner
# ======================================================================


class TestNetworkPlannerRoutes:
    def test_network_planner_registers_every_configuration_row(self, api):
        """PRD §2.1: "A `NetworkPlanner` owns network configuration (nodes, SKUs, inventory, packaging), the routing engine, node reactivation and the operations run that closes performance windows."
        PRD §3.1: "A `NetworkPlanner` registers a fulfillment node by supplying its `store_code` — a human-readable node code between 1 and 16 characters that must be unique across all nodes, with a duplicate rejected as `ERR_DUPLICATE_STORE_CODE` — its `region_code` for reporting, and its `origin_zone`, an integer from 1 to 8 giving the carrier origin zone used for transit and rate arithmetic."
        PRD §3.1: "A planner may later adjust a node's posture, supplying any subset of `daily_unit_capacity`, `staffed_labor_minutes`, `labor_standard_minutes_per_order`, `pick_labor_minutes_per_unit`, `labor_rate_cents_per_minute`, `cutoff_utc_minutes` and `hazmat_certified`."

        Design: Corner/rbac/network_planner_runs_every_configuration_and_engine_operation
        """
        set_clock(CLOCK)

        s1 = validate_success(api.create_store(create_store_payload("S1"), PLANNER), 201)
        assert s1["node_status"] == "ELIGIBLE", (
            "registration seeds node_status ELIGIBLE for the planner's new node"
        )
        s2 = validate_success(api.create_store(create_store_payload("S2"), PLANNER), 201)
        assert s2["node_status"] == "ELIGIBLE", "S2 also starts ELIGIBLE"
        assert s2["eligibility_score"] == 48.75, (
            "S2 cold-start eligibility_score should be 48.75, got "
            f"{s2['eligibility_score']}"
        )

        sku_a = validate_success(api.create_sku(create_sku_payload("SKU-A"), PLANNER), 201)
        sku_b = validate_success(api.create_sku(create_sku_payload("SKU-B"), PLANNER), 201)
        assert sku_b["package_class"] == "SMALL", (
            f"SKU-B package_class should be SMALL, got {sku_b['package_class']}"
        )

        inventory = validate_success(
            api.create_store_inventory(
                create_store_inventory_payload(s1["id"], sku_a["id"], 12, 2), PLANNER
            ),
            201,
        )
        assert inventory["store_id"] == s1["id"], "the planner stocked the SKU at S1"
        assert inventory["available_to_promise_units"] == 10, (
            "available_to_promise_units is 12 on hand less 0 reserved less 2 safety, got "
            f"{inventory['available_to_promise_units']}"
        )

        supply = validate_success(
            api.create_packaging_supply(
                create_packaging_supply_payload(s1["id"], "MEDIUM_BOX", 4, 1), PLANNER
            ),
            201,
        )
        assert supply["package_type"] == "MEDIUM_BOX", "the planner stocked a MEDIUM_BOX row"
        assert supply["reorder_flag"] is False, "4 on hand is above the reorder point of 1"

        patched = validate_success(
            api.patch_store(
                s1["id"], {"daily_unit_capacity": 200, "cutoff_utc_minutes": 1080}, PLANNER
            ),
            200,
        )
        assert patched["daily_unit_capacity"] == 200, "the posture adjustment applied"
        assert patched["cutoff_utc_minutes"] == 1080, "the cutoff moved with the adjustment"
        assert patched["eligibility_score"] == 88.00, (
            "the adjustment rescores the node to 88.00, got "
            f"{patched['eligibility_score']}"
        )
        assert patched["version"] == 2, (
            f"the adjustment increments version to 2, got {patched['version']}"
        )

    def test_network_planner_drives_the_routing_engine_the_ops_run_and_the_clock(self, api):
        """PRD §3.4: "A `NetworkPlanner` routes an order by starting a routing run, supplying a `mode` of either `PROVISIONAL` or `COMMIT`, the `expected_order_version` guard from §2.8, and optionally `override_cost_guardrail`."
        PRD §3.9: "Node performance is settled by a network-wide operations run that a `NetworkPlanner` triggers."
        PRD §2.6: "A `NetworkPlanner` may advance it through an administrative test-driving capability that takes a `to_iso8601` instant and answers with the resulting `current_utc` alongside the `previous_utc` it replaced."

        Design: Corner/rbac/network_planner_runs_every_configuration_and_engine_operation
        """
        net = setup_network(
            node_presets=("S1", "S2"),
            sku_presets=("SKU-A", "SKU-B"),
            clock=CLOCK,
            stock=[("S1", "SKU-A", 12, 2), ("S2", "SKU-B", 5, 1)],
        )
        s1, s2 = net["stores"]["S1"], net["stores"]["S2"]
        validate_success(
            api.patch_store(
                s1["id"], {"daily_unit_capacity": 200, "cutoff_utc_minutes": 1080}, PLANNER
            ),
            200,
        )

        built = setup_order_with_lines(
            [(net["skus"]["SKU-A"]["id"], 2, 4500)],
            order_code="O-H001",
            customer_ref="C-940",
            destination_zone=4,
        )
        order = built["order"]

        run = validate_success(
            api.create_routing_run(
                order["id"],
                create_routing_run_payload(order["version"], "COMMIT"),
                PLANNER,
            ),
            201,
        )
        assert run["status"] == "COMMITTED", (
            f"the planner's COMMIT run should be COMMITTED, got {run['status']}"
        )
        assert run["selected_store_count"] == 1, (
            f"only S1 can cover the demand, got selected_store_count {run['selected_store_count']}"
        )

        s2_candidates = find_routing_candidates(routing_run_id=run["id"], store_id=s2["id"])
        assert len(s2_candidates) == 1, "S2 is still evaluated and persisted as a candidate"
        assert s2_candidates[0]["eligible"] is False, "S2 stocks only SKU-B, so it is ineligible"
        assert s2_candidates[0]["ineligible_reason"] == "NO_ATP", (
            "S2 has no promise-able units for SKU-A, so ineligible_reason is NO_ATP, got "
            f"{s2_candidates[0]['ineligible_reason']}"
        )

        assert read_store(s1["id"])["eligibility_score"] == 86.48, (
            "after the commit S1 rescores to 86.48, got "
            f"{read_store(s1['id'])['eligibility_score']}"
        )

        closed = validate_success(api.close_performance_windows(PLANNER), 200)
        assert [row["store_id"] for row in closed] == [s1["id"], s2["id"]], (
            "the ops run answers with the closed windows in ascending node created_at order"
        )
        assert all(row["status"] == "CLOSED" for row in closed), (
            "every window the ops run touched is CLOSED"
        )
        assert closed[0]["assignments_created"] == 1, (
            f"S1's window measured one assignment, got {closed[0]['assignments_created']}"
        )
        assert closed[0]["breach_flags"] == [], (
            f"S1's window is unbreached, got breach_flags {closed[0]['breach_flags']}"
        )
        assert closed[0]["node_action"] == "NONE", (
            f"a non-breached ELIGIBLE node takes no action, got {closed[0]['node_action']}"
        )

        clock = validate_success(
            api.set_clock({"to_iso8601": "2026-08-03T09:30:00Z"}, PLANNER), 200
        )
        assert clock["previous_utc"].startswith("2026-08-03T09:00:00"), (
            f"previous_utc should report the replaced instant, got {clock['previous_utc']}"
        )
        assert clock["current_utc"].startswith("2026-08-03T09:30:00"), (
            f"current_utc should report the new instant, got {clock['current_utc']}"
        )

    def test_network_planner_uses_its_shared_write_routes_and_the_shared_cost_read(
        self, api
    ):
        """PRD §3.6: "Pickup windows are scheduled per node by a `CarrierCoordinator` or a `NetworkPlanner`, with a `carrier_code` identifying the carrier, an inclusive `window_start_utc`, an exclusive `window_end_utc` that must be strictly later (otherwise `ERR_INVALID_WINDOW`), and a `parcel_capacity` of at least 1 giving the parcels the carrier will accept in that window."
        PRD §3.1: "Cycle counts, shrink write-offs, receipts and markdown pulls all arrive as adjustments, which a `NetworkPlanner` or the node's own `StoreAssociate` may post."
        PRD §3.1: "Receiving packaging is a restock, available to a planner or to the node's own associate, which adds a supplied `added_units` count to `on_hand_units`, re-derives `reorder_flag`, and increments the row's `version`."
        PRD §3.8: "A planner or a care agent may also read the comparison directly for an order."

        Design: Corner/rbac/network_planner_runs_every_configuration_and_engine_operation
        """
        ctx = setup_committed_assignment(
            clock=CLOCK,
            with_packaging=True,
            packaging_on_hand=4,
            with_pickup=False,
            order_code="O-H002",
            customer_ref="C-941",
        )

        pickup = validate_success(
            api.create_carrier_pickup(
                ctx["store"]["id"],
                create_carrier_pickup_payload(
                    carrier_code="UPS",
                    window_start_utc="2026-08-03T08:30:00Z",
                    window_end_utc="2026-08-03T10:00:00Z",
                    parcel_capacity=5,
                ),
                PLANNER,
            ),
            201,
        )
        assert pickup["status"] == "SCHEDULED", (
            f"a planner-scheduled window starts SCHEDULED, got {pickup['status']}"
        )
        assert pickup["reserved_parcels"] == 0, "a new window holds no parcels"
        assert pickup["version"] == 1, f"a new window is at version 1, got {pickup['version']}"

        inv_v = inventory_version(ctx["inventory"]["id"])
        adjusted = validate_success(
            api.adjust_store_inventory(
                ctx["inventory"]["id"],
                inventory_adjustment_payload(inv_v, 12, "CYCLE_COUNT"),
                PLANNER,
            ),
            200,
        )
        assert adjusted["last_adjustment_reason"] == "CYCLE_COUNT", (
            f"the reason is recorded, got {adjusted['last_adjustment_reason']}"
        )
        assert adjusted["on_hand_units"] == 12, (
            f"on_hand_units is overwritten with the counted figure, got {adjusted['on_hand_units']}"
        )
        assert adjusted["reserved_units"] == 2, (
            f"the committed assignment still holds 2 units, got {adjusted['reserved_units']}"
        )
        assert adjusted["available_to_promise_units"] == 8, (
            f"12 on hand less 2 reserved less 2 safety is 8, got {adjusted['available_to_promise_units']}"
        )
        assert adjusted["version"] == inv_v + 1, (
            f"the adjustment increments the row version to {inv_v + 1}, got {adjusted['version']}"
        )

        restocked = validate_success(
            api.restock_packaging_supply(ctx["supply"]["id"], {"added_units": 6}, PLANNER),
            200,
        )
        assert restocked["on_hand_units"] == 10, (
            f"4 on hand plus 6 received is 10, got {restocked['on_hand_units']}"
        )
        assert restocked["reorder_flag"] is False, (
            "10 on hand is above the reorder point, so reorder_flag is false"
        )

        comparison = validate_success(api.get_cost_comparison(ctx["order"]["id"], PLANNER), 200)
        assert_cost_comparison(comparison)
        assert comparison["variant"] == "PROVISIONAL", (
            f"the order is not SHIPPED, so the variant is PROVISIONAL, got {comparison['variant']}"
        )
        assert comparison["store_cost_cents"] == 1416, (
            f"store_cost_cents should be 1416, got {comparison['store_cost_cents']}"
        )
        assert comparison["dc_baseline_cost_cents"] == 2090, (
            f"dc_baseline_cost_cents should be 2090, got {comparison['dc_baseline_cost_cents']}"
        )
        assert comparison["cost_index_bps"] == 6775, (
            f"cost_index_bps should be 6775, got {comparison['cost_index_bps']}"
        )
        assert comparison["savings_vs_dc_cents"] == 674, (
            f"savings_vs_dc_cents should be 674, got {comparison['savings_vs_dc_cents']}"
        )


# ======================================================================
# StoreAssociate at its own node
# ======================================================================


class TestStoreAssociateOwnNodeRoutes:
    def test_store_associate_walks_accept_pick_pack_and_ship_at_its_own_node(self, api):
        """PRD §2.1: "A `StoreAssociate` executes pick, pack and ship work inside exactly one node."
        PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."
        PRD §3.5: "From `ACCEPTED`, the associate records the pick with a `picked_units` total and a `line_picks` array whose entries each pair an `assignment_line_id` with a `units_picked` count, covering every assignment line of the assignment exactly once."
        PRD §3.5: "From either `PICKED` or `SHORT_PICKED`, the associate records packing with the `package_type` actually used, moving the assignment to `PACKED`."
        PRD §3.6: "The associate supplies the `carrier_pickup_id` and the `expected_pickup_version` guard."

        Design: Corner/rbac/store_associate_runs_the_full_in_store_workflow_at_its_own_node
        """
        ctx = setup_committed_assignment(
            clock=CLOCK,
            with_packaging=True,
            packaging_on_hand=4,
            with_pickup=True,
            pickup_start="2026-08-03T08:30:00Z",
            pickup_end="2026-08-03T10:00:00Z",
            parcel_capacity=5,
            order_code="O-I001",
            customer_ref="C-950",
        )
        own = make_store_associate_headers(ctx["store"]["id"])
        assignment_id = ctx["assignment"]["id"]

        accepted = validate_success(api.accept_assignment(assignment_id, own), 200)
        assert accepted["status"] == "ACCEPTED", (
            f"accept moves the assignment to ACCEPTED, got {accepted['status']}"
        )
        assert accepted["accepted_at"].startswith("2026-08-03T09:00:00"), (
            f"accepted_at is the clock instant, got {accepted['accepted_at']}"
        )
        assert accepted["version"] == 2, (
            f"accept increments version to 2, got {accepted['version']}"
        )

        lines = find_assignment_lines(assignment_id)
        picked = validate_success(
            api.pick_assignment(
                assignment_id,
                pick_payload(2, [line_pick(lines[0]["id"], 2)]),
                own,
            ),
            200,
        )
        assert picked["status"] == "PICKED", (
            f"a full pick moves the assignment to PICKED, got {picked['status']}"
        )
        assert picked["picked_units"] == 2, f"picked_units is 2, got {picked['picked_units']}"
        assert picked["shortfall_units"] == 0, (
            f"a full pick leaves shortfall_units at 0, got {picked['shortfall_units']}"
        )
        assert picked["version"] == 3, f"pick increments version to 3, got {picked['version']}"

        packed = validate_success(
            api.pack_assignment(assignment_id, {"package_type": "MEDIUM_BOX"}, own), 200
        )
        assert packed["status"] == "PACKED", (
            f"pack moves the assignment to PACKED, got {packed['status']}"
        )
        assert packed["package_type"] == "MEDIUM_BOX", (
            f"the recorded package_type is MEDIUM_BOX, got {packed['package_type']}"
        )
        assert packed["labor_minutes_actual"] == 0, (
            "accepted_at and packed_at are the same clock instant, so labor_minutes_actual is 0, "
            f"got {packed['labor_minutes_actual']}"
        )
        assert packed["version"] == 4, f"pack increments version to 4, got {packed['version']}"
        assert read_packaging(ctx["supply"]["id"])["on_hand_units"] == 3, (
            "packing consumes one packaging unit out of the 4 stocked"
        )

        pickup_v = pickup_version(ctx["pickup"]["id"])
        shipped = validate_success(
            api.ship_assignment(
                assignment_id, ship_payload(ctx["pickup"]["id"], pickup_v), own
            ),
            200,
        )
        assert shipped["status"] == "SHIPPED", (
            f"the tender moves the assignment to SHIPPED, got {shipped['status']}"
        )
        assert shipped["carrier_pickup_id"] == ctx["pickup"]["id"], (
            "the tendered window is stored on the assignment"
        )
        assert shipped["cycle_time_minutes"] == 0, (
            f"created_at and shipped_at share the clock instant, got {shipped['cycle_time_minutes']}"
        )
        assert shipped["final_cost_cents"] == 1000, (
            f"final_cost_cents should be 1000, got {shipped['final_cost_cents']}"
        )
        assert shipped["version"] == 5, f"ship increments version to 5, got {shipped['version']}"

        pickup_after = read_pickup(ctx["pickup"]["id"])
        assert pickup_after["reserved_parcels"] == 1, (
            f"the tender claims one parcel slot, got {pickup_after['reserved_parcels']}"
        )
        assert pickup_after["version"] == pickup_v + 1, (
            f"the tender increments the pickup version to {pickup_v + 1}, got {pickup_after['version']}"
        )

    def test_store_associate_rejects_an_assignment_at_its_own_node(self, api):
        """PRD §3.7: "An associate may reject an assignment from either `ASSIGNED` or `ACCEPTED`, supplying a `reject_reason_code` of `NO_STOCK_ON_FLOOR`, `LABOR_UNAVAILABLE`, `DAMAGED_UNITS` or `STORE_CLOSED`."
        PRD §2.1: "A `StoreAssociate` executes pick, pack and ship work inside exactly one node."

        Design: Corner/rbac/store_associate_runs_the_full_in_store_workflow_at_its_own_node
        """
        ctx = setup_committed_assignment(
            clock=CLOCK,
            with_packaging=False,
            with_pickup=False,
            order_code="O-I002",
            customer_ref="C-951",
        )
        own = make_store_associate_headers(ctx["store"]["id"])

        rejected = validate_success(
            api.reject_assignment(
                ctx["assignment"]["id"], {"reject_reason_code": "NO_STOCK_ON_FLOOR"}, own
            ),
            200,
        )
        assert rejected["status"] == "REJECTED", (
            f"the node's own associate may hand the work back, got {rejected['status']}"
        )
        assert rejected["reject_reason_code"] == "NO_STOCK_ON_FLOOR", (
            f"the supplied reason is stored, got {rejected['reject_reason_code']}"
        )

    def test_store_associate_posts_an_adjustment_and_a_restock_at_its_own_node(self, api):
        """PRD §3.1: "Cycle counts, shrink write-offs, receipts and markdown pulls all arrive as adjustments, which a `NetworkPlanner` or the node's own `StoreAssociate` may post."
        PRD §3.1: "Receiving packaging is a restock, available to a planner or to the node's own associate, which adds a supplied `added_units` count to `on_hand_units`, re-derives `reorder_flag`, and increments the row's `version`."

        Design: Corner/rbac/store_associate_runs_the_full_in_store_workflow_at_its_own_node
        """
        ctx = setup_committed_assignment(
            clock=CLOCK,
            with_packaging=True,
            packaging_on_hand=3,
            with_pickup=False,
            order_code="O-I003",
            customer_ref="C-952",
        )
        own = make_store_associate_headers(ctx["store"]["id"])

        inv_v = inventory_version(ctx["inventory"]["id"])
        adjusted = validate_success(
            api.adjust_store_inventory(
                ctx["inventory"]["id"],
                inventory_adjustment_payload(inv_v, 10, "CYCLE_COUNT"),
                own,
            ),
            200,
        )
        assert adjusted["on_hand_units"] == 10, (
            f"the associate's counted figure is written, got {adjusted['on_hand_units']}"
        )
        assert adjusted["last_adjustment_reason"] == "CYCLE_COUNT", (
            f"the reason is recorded, got {adjusted['last_adjustment_reason']}"
        )

        restocked = validate_success(
            api.restock_packaging_supply(ctx["supply"]["id"], {"added_units": 5}, own), 200
        )
        assert restocked["on_hand_units"] == 8, (
            f"3 on hand plus 5 received is 8, got {restocked['on_hand_units']}"
        )


# ======================================================================
# CarrierCoordinator
# ======================================================================


class TestCarrierCoordinatorRoutes:
    def test_carrier_coordinator_schedules_then_closes_then_departs_a_window(self, api):
        """PRD §3.6: "Pickup windows are scheduled per node by a `CarrierCoordinator` or a `NetworkPlanner`, with a `carrier_code` identifying the carrier, an inclusive `window_start_utc`, an exclusive `window_end_utc` that must be strictly later (otherwise `ERR_INVALID_WINDOW`), and a `parcel_capacity` of at least 1 giving the parcels the carrier will accept in that window."
        PRD §3.6: "A coordinator closes a `SCHEDULED` window, moving it `SCHEDULED → CLOSED`, after which no further parcel may be tendered to it — a later tender fails with `ERR_PICKUP_STATE_INVALID` — and the pickup's `version` increments."
        PRD §3.6: "A coordinator records the carrier's departure from a `CLOSED` window, moving it `CLOSED → DEPARTED`, which seals the pickup and freezes `reserved_parcels`, again incrementing `version`."

        Design: Corner/rbac/carrier_coordinator_owns_the_pickup_lifecycle_end_to_end
        """
        set_clock(CLOCK)
        store = register_node("S1")

        p1 = validate_success(
            api.create_carrier_pickup(
                store["id"],
                create_carrier_pickup_payload(
                    carrier_code="UPS",
                    window_start_utc="2026-08-03T08:30:00Z",
                    window_end_utc="2026-08-03T10:00:00Z",
                    parcel_capacity=5,
                ),
                CARRIER,
            ),
            201,
        )
        assert p1["status"] == "SCHEDULED", f"a new window is SCHEDULED, got {p1['status']}"
        assert p1["reserved_parcels"] == 0, "a new window holds no parcels"
        assert p1["version"] == 1, f"a new window is at version 1, got {p1['version']}"

        p2 = validate_success(
            api.create_carrier_pickup(
                store["id"],
                create_carrier_pickup_payload(
                    carrier_code="FEDEX",
                    window_start_utc="2026-08-03T11:00:00Z",
                    window_end_utc="2026-08-03T12:00:00Z",
                    parcel_capacity=3,
                ),
                CARRIER,
            ),
            201,
        )
        assert p2["status"] == "SCHEDULED", (
            "the 60-minute gap clears the dead-band, so the second window schedules too"
        )
        assert p2["version"] == 1, f"the second window is at version 1, got {p2['version']}"

        closed = validate_success(api.close_carrier_pickup(p1["id"], CARRIER), 200)
        assert closed["status"] == "CLOSED", (
            f"the coordinator's close moves the window to CLOSED, got {closed['status']}"
        )
        assert closed["version"] == 2, f"close increments version to 2, got {closed['version']}"

        departed = validate_success(api.depart_carrier_pickup(p1["id"], CARRIER), 200)
        assert departed["status"] == "DEPARTED", (
            f"the coordinator's depart seals the window, got {departed['status']}"
        )
        assert departed["version"] == 3, (
            f"depart increments version to 3, got {departed['version']}"
        )

    def test_carrier_coordinator_cancels_an_empty_scheduled_window(self, api):
        """PRD §3.6: "A coordinator may also cancel a `SCHEDULED` window, moving it `SCHEDULED → CANCELLED`, which releases its slot so a new overlapping window may be scheduled at the node and increments `version`; cancellation is permitted only while `reserved_parcels` is exactly 0, and a window holding parcels is refused with `ERR_PICKUP_HAS_PARCELS`."
        PRD §2.1: "A `CarrierCoordinator` owns the pickup lifecycle once a window has been scheduled."

        Design: Corner/rbac/carrier_coordinator_owns_the_pickup_lifecycle_end_to_end
        """
        set_clock(CLOCK)
        store = register_node("S1")

        pickup = validate_success(
            api.create_carrier_pickup(
                store["id"],
                create_carrier_pickup_payload(
                    carrier_code="FEDEX",
                    window_start_utc="2026-08-03T11:00:00Z",
                    window_end_utc="2026-08-03T12:00:00Z",
                    parcel_capacity=3,
                ),
                CARRIER,
            ),
            201,
        )
        assert pickup["reserved_parcels"] == 0, "the window is empty, so cancel is permitted"

        cancelled = validate_success(api.cancel_carrier_pickup(pickup["id"], CARRIER), 200)
        assert cancelled["status"] == "CANCELLED", (
            f"the coordinator's cancel releases the slot, got {cancelled['status']}"
        )
        assert cancelled["version"] == 2, (
            f"cancel increments version to 2, got {cancelled['version']}"
        )


# ======================================================================
# CustomerCare
# ======================================================================


class TestCustomerCareRoutes:
    def test_customer_care_takes_an_order_and_adds_a_demand_line(self, api):
        """PRD §2.1: "A `CustomerCare` agent owns order intake, demand lines, and customer-driven cancellation of an order or of a single assignment."
        PRD §3.2: "A `CustomerCare` agent takes an order with an `order_code` unique across all orders (`ERR_DUPLICATE_ORDER_CODE` otherwise), a `customer_ref` opaque handle used on customer notifications, a `destination_zone` from 1 to 8 giving the carrier destination zone of the ship-to address, a `service_level` of either `GROUND` or `EXPEDITED`, and a `promised_ship_by_utc` instant echoed onto notifications."
        PRD §3.2: "Intake sets `routing_status` to `UNROUTED`, `fulfillment_status` to `PENDING`, and every unit counter — `total_units`, `shipped_units`, `unassigned_units`, `dc_fallback_units`, `split_count`, `reroute_attempt_count` — to 0, with `provisional_cost_cents` 0, `final_cost_cents` null, `cost_variance_cents` null and `cost_index_bps` 0."

        Design: Corner/rbac/customer_care_owns_intake_reads_and_both_cancellation_routes
        """
        net = setup_network(
            node_presets=("S1",),
            sku_presets=("SKU-A",),
            clock=CLOCK,
            stock=[("S1", "SKU-A", 12, 2)],
        )

        order = validate_success(
            api.create_order(
                create_order_payload(
                    order_code="O-J003",
                    customer_ref="C-962",
                    destination_zone=2,
                    service_level="EXPEDITED",
                    promised_ship_by_utc="2026-08-05T15:00:00Z",
                ),
                CARE,
            ),
            201,
        )
        assert order["routing_status"] == "UNROUTED", (
            f"intake sets routing_status UNROUTED, got {order['routing_status']}"
        )
        assert order["fulfillment_status"] == "PENDING", (
            f"intake sets fulfillment_status PENDING, got {order['fulfillment_status']}"
        )
        assert order["total_units"] == 0, "intake starts every unit counter at 0"

        line = validate_success(
            api.create_order_line(
                order["id"],
                create_order_line_payload(net["skus"]["SKU-A"]["id"], 3, 4500),
                CARE,
            ),
            201,
        )
        assert line["open_units"] == 3, (
            f"a new demand line's open_units equals its quantity, got {line['open_units']}"
        )
        assert line["line_status"] == "OPEN", (
            f"a new demand line starts OPEN, got {line['line_status']}"
        )
        assert read_order(order["id"])["total_units"] == 3, (
            "adding the line recomputes the order's total_units to 3"
        )

    def test_customer_care_reads_the_cost_comparison_then_cancels_one_assignment(self, api):
        """PRD §3.8: "A planner or a care agent may also read the comparison directly for an order."
        PRD §3.7: "A `CustomerCare` agent may cancel an assignment sitting at `ASSIGNED`, `ACCEPTED`, `PICKED` or `SHORT_PICKED`, supplying a `cancel_reason_code` and a `reroute` boolean."
        PRD §3.7: "All four permitted source states carry the same cascade: `status` becomes `CANCELLED` and the `cancel_reason_code` is stored; each assignment line's `units_cancelled` becomes its `units_assigned` minus its `units_picked`, releasing that much of the served demand line's `assigned_units`; the node's inventory `reserved_units`, `units_committed_epoch` and `reserved_labor_minutes` all decrease and its `eligibility_score` is recomputed — including, for a `PICKED` or `SHORT_PICKED` source, the units already physically picked, which are returned to the node's reservations and then released; when `reroute` is true a system reroute run excluding this node is created, at `initiated_by` `SYSTEM_REROUTE` or, for a deactivation cascade, `SYSTEM_DEACTIVATION`, while when `reroute` is false the released units become the demand lines' `cancelled_units`; a customer notification is emitted; the order's `routing_status` and `fulfillment_status` are re-derived; and the assignment's `version` increments."

        Design: Corner/rbac/customer_care_owns_intake_reads_and_both_cancellation_routes
        """
        ctx = setup_committed_assignment(
            clock=CLOCK,
            with_packaging=False,
            with_pickup=False,
            order_code="O-J001",
            customer_ref="C-960",
        )

        comparison = validate_success(api.get_cost_comparison(ctx["order"]["id"], CARE), 200)
        assert_cost_comparison(comparison)
        assert comparison["store_cost_cents"] == 1416, (
            f"store_cost_cents should be 1416, got {comparison['store_cost_cents']}"
        )
        assert comparison["dc_baseline_cost_cents"] == 2090, (
            f"dc_baseline_cost_cents should be 2090, got {comparison['dc_baseline_cost_cents']}"
        )
        assert comparison["cost_index_bps"] == 6775, (
            f"cost_index_bps should be 6775, got {comparison['cost_index_bps']}"
        )
        assert comparison["savings_vs_dc_cents"] == 674, (
            f"savings_vs_dc_cents should be 674, got {comparison['savings_vs_dc_cents']}"
        )

        cancelled = validate_success(
            api.cancel_assignment(
                ctx["assignment"]["id"],
                {"cancel_reason_code": "CUSTOMER_REQUEST", "reroute": False},
                CARE,
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED", (
            f"care's assignment cancel moves it to CANCELLED, got {cancelled['status']}"
        )
        assert cancelled["cancel_reason_code"] == "CUSTOMER_REQUEST", (
            f"the supplied reason is stored, got {cancelled['cancel_reason_code']}"
        )
        assert len(find_routing_runs(order_id=ctx["order"]["id"])) == 1, (
            "with reroute false no replacement routing run is created"
        )

        inventory = read_inventory(ctx["inventory"]["id"])
        assert inventory["reserved_units"] == 0, (
            f"the cancel releases the reservation, got {inventory['reserved_units']}"
        )
        assert inventory["available_to_promise_units"] == 10, (
            f"12 on hand less 0 reserved less 2 safety is 10, got {inventory['available_to_promise_units']}"
        )
        store = read_store(ctx["store"]["id"])
        assert store["units_committed_epoch"] == 0, (
            f"the node's committed units are released, got {store['units_committed_epoch']}"
        )
        assert store["reserved_labor_minutes"] == 0, (
            f"the node's reserved labour is released, got {store['reserved_labor_minutes']}"
        )

    def test_customer_care_cancels_a_whole_order_with_no_shipped_units(self, api):
        """PRD §3.2: "A care agent may cancel the whole order outright, supplying a `cancel_reason_code`, but only while `fulfillment_status` is `PENDING` and `shipped_units` is 0; otherwise the request is rejected with `ERR_ORDER_ALREADY_SHIPPED_UNITS`."
        PRD §2.1: "A `CustomerCare` agent owns order intake, demand lines, and customer-driven cancellation of an order or of a single assignment."

        Design: Corner/rbac/customer_care_owns_intake_reads_and_both_cancellation_routes
        """
        net = setup_network(
            node_presets=("S1",),
            sku_presets=("SKU-A",),
            clock=CLOCK,
            stock=[("S1", "SKU-A", 12, 2)],
        )
        built = setup_order_with_lines(
            [(net["skus"]["SKU-A"]["id"], 1, 4500)],
            order_code="O-J002",
            customer_ref="C-961",
        )
        assert built["order"]["shipped_units"] == 0, "the order was never routed or shipped"

        cancelled = validate_success(
            api.cancel_order(
                built["order"]["id"], {"cancel_reason_code": "CUSTOMER_REQUEST"}, CARE
            ),
            200,
        )
        assert cancelled["fulfillment_status"] == "CANCELLED", (
            "a PENDING order with no shipped units cancels outright, got "
            f"{cancelled['fulfillment_status']}"
        )


# ======================================================================
# Cross-role writes on another role's exclusive route
# ======================================================================


class TestForbiddenRoleOnExclusiveRoutes:
    def test_planner_exclusive_routes_refuse_the_other_roles(self, api):
        """PRD §2.1: "A request whose role is recognised but is not listed among the authorised roles for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `NetworkPlanner` owns network configuration (nodes, SKUs, inventory, packaging), the routing engine, node reactivation and the operations run that closes performance windows."
        PRD §3.4: "A `NetworkPlanner` routes an order by starting a routing run, supplying a `mode` of either `PROVISIONAL` or `COMMIT`, the `expected_order_version` guard from §2.8, and optionally `override_cost_guardrail`."
        PRD §3.9: "Node performance is settled by a network-wide operations run that a `NetworkPlanner` triggers."

        Design: Corner/rbac/cross_role_writes_on_another_roles_exclusive_route_return_forbidden_role
        """
        ctx = _committed_assignment_with_a_pickup()
        order_v = ctx["order"]["version"]

        validate_error(
            api.create_store(create_store_payload("S9"), CARE), "ERR_FORBIDDEN_ROLE"
        )
        validate_error(
            api.create_routing_run(
                ctx["order"]["id"], create_routing_run_payload(order_v, "COMMIT"), CARE
            ),
            "ERR_FORBIDDEN_ROLE",
        )
        validate_error(
            api.close_performance_windows(CARRIER), "ERR_FORBIDDEN_ROLE"
        )

        rows, meta = validate_paginated(api.list_stores(PLANNER))
        assert meta["total_count"] == 1, (
            f"the refused node registration wrote nothing, got total_count {meta['total_count']}"
        )
        assert read_order(ctx["order"]["id"])["version"] == order_v, (
            "the refused routing run left the order's version untouched even though its "
            "expected_order_version was correct"
        )
        windows = find_windows(store_id=ctx["store"]["id"])
        assert [row["status"] for row in windows] == ["OPEN"], (
            f"the refused ops run closed no window, got {[row['status'] for row in windows]}"
        )

    def test_store_associate_exclusive_accept_refuses_the_planner(self, api):
        """PRD §2.1: "A request whose role is recognised but is not listed among the authorised roles for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."
        PRD §2.1: "They are peers — no role is a superset of another."

        Design: Corner/rbac/cross_role_writes_on_another_roles_exclusive_route_return_forbidden_role
        """
        ctx = _committed_assignment_with_a_pickup()

        validate_error(
            api.accept_assignment(ctx["assignment"]["id"], PLANNER), "ERR_FORBIDDEN_ROLE"
        )

        assignment = read_assignment(ctx["assignment"]["id"])
        assert assignment["status"] == "ASSIGNED", (
            f"the refused accept left the assignment at ASSIGNED, got {assignment['status']}"
        )
        assert assignment["version"] == 1, (
            f"the refused accept mutated nothing, got version {assignment['version']}"
        )
        assert assignment["accepted_at"] is None, "accepted_at stays null after a refusal"

    def test_carrier_coordinator_exclusive_close_refuses_the_planner(self, api):
        """PRD §2.1: "A request whose role is recognised but is not listed among the authorised roles for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `CarrierCoordinator` owns the pickup lifecycle once a window has been scheduled."
        PRD §3.6: "A coordinator closes a `SCHEDULED` window, moving it `SCHEDULED → CLOSED`, after which no further parcel may be tendered to it — a later tender fails with `ERR_PICKUP_STATE_INVALID` — and the pickup's `version` increments."

        Design: Corner/rbac/cross_role_writes_on_another_roles_exclusive_route_return_forbidden_role
        """
        ctx = _committed_assignment_with_a_pickup()

        validate_error(
            api.close_carrier_pickup(ctx["pickup"]["id"], PLANNER), "ERR_FORBIDDEN_ROLE"
        )

        pickup = read_pickup(ctx["pickup"]["id"])
        assert pickup["status"] == "SCHEDULED", (
            "the planner may schedule a window but not close one, so the window is still "
            f"SCHEDULED, got {pickup['status']}"
        )
        assert pickup["version"] == 1, (
            f"the refused close mutated nothing, got version {pickup['version']}"
        )

    def test_customer_care_exclusive_routes_refuse_the_other_roles(self, api):
        """PRD §2.1: "A request whose role is recognised but is not listed among the authorised roles for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `CustomerCare` agent owns order intake, demand lines, and customer-driven cancellation of an order or of a single assignment."
        PRD §2.11: "Identity first: header presence and role validity, then whether the acting role is authorised for the operation."
        PRD §2.11: "Node-scope ownership fourth, as `ERR_STORE_SCOPE_VIOLATION`."

        Design: Corner/rbac/cross_role_writes_on_another_roles_exclusive_route_return_forbidden_role
        """
        ctx = _committed_assignment_with_a_pickup()
        order_v = ctx["order"]["version"]

        validate_error(
            api.create_order(create_order_payload(order_code="O-K999", customer_ref="C-999"), PLANNER),
            "ERR_FORBIDDEN_ROLE",
        )
        validate_error(
            api.create_order_line(
                ctx["order"]["id"], create_order_line_payload(ctx["sku"]["id"], 1, 4500), CARRIER
            ),
            "ERR_FORBIDDEN_ROLE",
        )
        validate_error(
            api.cancel_assignment(
                ctx["assignment"]["id"],
                {"cancel_reason_code": "CUSTOMER_REQUEST", "reroute": False},
                make_store_associate_headers(ctx["store"]["id"]),
            ),
            "ERR_FORBIDDEN_ROLE",
        )

        rows, meta = validate_paginated(api.list_orders(PLANNER))
        assert meta["total_count"] == 1, (
            f"the refused intake wrote no order, got total_count {meta['total_count']}"
        )
        assert read_order(ctx["order"]["id"])["version"] == order_v, (
            "the refused demand line left the order's version untouched"
        )
        assignment = read_assignment(ctx["assignment"]["id"])
        assert assignment["status"] == "ASSIGNED", (
            "the associate's cancel is refused on role membership before the node-scope "
            f"comparison, so the assignment is untouched, got {assignment['status']}"
        )
        assert assignment["version"] == 1, (
            f"the refused cancel mutated nothing, got version {assignment['version']}"
        )

    def test_shared_cost_comparison_read_refuses_the_store_associate(self, api):
        """PRD §3.8: "A planner or a care agent may also read the comparison directly for an order."
        PRD §2.1: "A request whose role is recognised but is not listed among the authorised roles for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "Reads are exempt: every list and detail endpoint is network-wide and is not scope-checked."

        Design: Corner/rbac/cross_role_writes_on_another_roles_exclusive_route_return_forbidden_role
        """
        ctx = _committed_assignment_with_a_pickup()
        own = make_store_associate_headers(ctx["store"]["id"])

        validate_error(
            api.get_cost_comparison(ctx["order"]["id"], own), "ERR_FORBIDDEN_ROLE"
        )

        detail = validate_success(api.get_assignment(ctx["assignment"]["id"], own), 200)
        assert detail["id"] == ctx["assignment"]["id"], (
            "the same associate identity still reads the ordinary detail endpoints"
        )
        rows, meta = validate_paginated(api.list_orders(own))
        assert meta["total_count"] == 1, (
            "the associate may list orders even though the computed cost read is closed to it"
        )


# ======================================================================
# Unauthenticated before everything else
# ======================================================================


class TestUnauthenticatedIdentity:
    def test_a_request_with_no_identity_headers_is_unauthenticated_on_an_open_read(
        self, api
    ):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts."
        PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_or_unknown_role_headers_are_unauthenticated_before_any_other_check
        """
        set_clock(CLOCK)
        register_node("S1")

        validate_error(api.list_stores({}), "ERR_UNAUTHENTICATED")

        rows, meta = validate_paginated(api.list_stores(PLANNER))
        assert meta["total_count"] == 1, (
            "the same list read succeeds for a declared role, so the 401 came from the "
            f"missing headers alone, got total_count {meta['total_count']}"
        )

    def test_a_declared_role_without_a_user_id_header_is_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "When `X-User-Role` is `NetworkPlanner`, `CarrierCoordinator` or `CustomerCare`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record or log it, but it never compares it to any entity's `id` and never derives ownership from it."

        Design: Corner/rbac/missing_or_unknown_role_headers_are_unauthenticated_before_any_other_check
        """
        set_clock(CLOCK)
        register_node("S1")

        validate_error(
            api.create_store(create_store_payload("S8"), {"X-User-Role": "NetworkPlanner"}),
            "ERR_UNAUTHENTICATED",
        )

        rows, meta = validate_paginated(api.list_stores(PLANNER))
        assert meta["total_count"] == 1, (
            f"the refused registration wrote nothing, got total_count {meta['total_count']}"
        )

    def test_an_undeclared_role_name_is_unauthenticated_rather_than_forbidden(self, api):
        """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "The four roles are `NetworkPlanner`, `StoreAssociate`, `CarrierCoordinator` and `CustomerCare`."
        PRD §2.11: "Identity first: header presence and role validity, then whether the acting role is authorised for the operation."

        Design: Corner/rbac/missing_or_unknown_role_headers_are_unauthenticated_before_any_other_check
        """
        set_clock(CLOCK)
        register_node("S1")

        validate_error(
            api.create_store(
                create_store_payload("S7"), build_user_headers("auditor-1", "Auditor")
            ),
            "ERR_UNAUTHENTICATED",
        )

        rows, meta = validate_paginated(api.list_stores(PLANNER))
        assert meta["total_count"] == 1, (
            f"the refused registration wrote nothing, got total_count {meta['total_count']}"
        )

    def test_a_store_associate_with_no_user_id_is_unauthenticated_before_the_scope_check(
        self, api
    ):
        """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "When `X-User-Role` is `StoreAssociate`, `X-User-ID` is the `id` of the acting `Store`; ownership checks on any resource that references a `Store` compare the resource's store foreign key to `X-User-ID`."
        PRD §2.11: "Identity first: header presence and role validity, then whether the acting role is authorised for the operation."
        PRD §2.11: "Node-scope ownership fourth, as `ERR_STORE_SCOPE_VIOLATION`."

        Design: Corner/rbac/missing_or_unknown_role_headers_are_unauthenticated_before_any_other_check
        """
        ctx = _committed_assignment_only()

        validate_error(
            api.accept_assignment(
                ctx["assignment"]["id"], {"X-User-Role": "StoreAssociate"}
            ),
            "ERR_UNAUTHENTICATED",
        )

        assignment = read_assignment(ctx["assignment"]["id"])
        assert assignment["status"] == "ASSIGNED", (
            "a missing X-User-ID fails identity before the node-scope comparison, so the "
            f"assignment is untouched, got {assignment['status']}"
        )
        assert assignment["version"] == 1, (
            f"the refused accept mutated nothing, got version {assignment['version']}"
        )

    def test_an_undeclared_role_with_a_malformed_body_is_unauthenticated_not_invalid(
        self, api
    ):
        """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.11: "Identity first: header presence and role validity, then whether the acting role is authorised for the operation."
        PRD §2.11: "Request shape second: required fields present, types correct, enum members inside their declared sets, integers inside their declared ranges — `limit` from 1 to 100, `offset` at least 0, `quantity` at least 1, `picked_units` at least 0, `parcel_capacity` at least 1, and both `origin_zone` and `destination_zone` from 1 to 8 — all reported as `ERR_INVALID_REQUEST`."

        Design: Corner/rbac/missing_or_unknown_role_headers_are_unauthenticated_before_any_other_check
        """
        ctx = _committed_assignment_only()

        validate_error(
            api.create_order(
                {
                    "customer_ref": "C-981",
                    "destination_zone": 99,
                    "service_level": "TELEPORT",
                    "promised_ship_by_utc": "2026-08-04T15:00:00Z",
                },
                build_user_headers("auditor-1", "Auditor"),
            ),
            "ERR_UNAUTHENTICATED",
        )

        rows, meta = validate_paginated(api.list_orders(PLANNER))
        assert meta["total_count"] == 1, (
            "only the fixture's own order exists, so the malformed intake wrote nothing, got "
            f"total_count {meta['total_count']}"
        )
        assert read_assignment(ctx["assignment"]["id"])["version"] == 1, (
            "the refused call mutated no domain row"
        )


# ======================================================================
# Node scope: writes are owned, reads are network-wide
# ======================================================================


class TestStoreAssociateNodeScope:
    def test_store_associate_cannot_accept_another_nodes_assignment_but_the_owner_can(
        self, api
    ):
        """PRD §2.1: "Concretely, when a `StoreAssociate` accepts, rejects, picks, packs or ships an assignment, or posts an inventory adjustment, or restocks packaging, the `store_id` of the targeted assignment, inventory row or packaging row must equal `X-User-ID`; a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.1: "They are peers — no role is a superset of another."
        PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."

        Design: Corner/rbac/a_store_associate_cannot_write_another_nodes_rows_while_reads_stay_network_wide
        """
        ctx = _order_committed_to_the_second_node()
        assignment_id = ctx["assignment"]["id"]
        assert ctx["assignment"]["store_id"] == ctx["s2"]["id"], (
            "only S2 stocks the SKU, so the assignment belongs to S2"
        )
        s1_candidates = find_routing_candidates(
            routing_run_id=ctx["run"]["id"], store_id=ctx["s1"]["id"]
        )
        assert s1_candidates[0]["eligible"] is False, "S1 has no inventory row for the SKU"
        assert s1_candidates[0]["ineligible_reason"] == "NO_ATP", (
            f"S1 loses on promise-able units, got {s1_candidates[0]['ineligible_reason']}"
        )

        validate_error(
            api.accept_assignment(
                assignment_id, make_store_associate_headers(ctx["s1"]["id"])
            ),
            "ERR_STORE_SCOPE_VIOLATION",
        )
        refused = read_assignment(assignment_id)
        assert refused["status"] == "ASSIGNED", (
            f"the cross-node accept is inert, got {refused['status']}"
        )
        assert refused["version"] == 1, (
            f"the cross-node accept mutated nothing, got version {refused['version']}"
        )

        accepted = validate_success(
            api.accept_assignment(
                assignment_id, make_store_associate_headers(ctx["s2"]["id"])
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED", (
            f"the owning node's associate performs the identical write, got {accepted['status']}"
        )
        assert accepted["version"] == 2, (
            f"the accepted assignment moves to version 2, got {accepted['version']}"
        )

    def test_store_associate_cannot_adjust_another_nodes_inventory_row(self, api):
        """PRD §2.1: "Concretely, when a `StoreAssociate` accepts, rejects, picks, packs or ships an assignment, or posts an inventory adjustment, or restocks packaging, the `store_id` of the targeted assignment, inventory row or packaging row must equal `X-User-ID`; a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.11: "Node-scope ownership fourth, as `ERR_STORE_SCOPE_VIOLATION`."
        PRD §2.11: "Stale-version protection fifth, as described in §2.8."

        Design: Corner/rbac/a_store_associate_cannot_write_another_nodes_rows_while_reads_stay_network_wide
        """
        ctx = _order_committed_to_the_second_node()
        inventory_id = ctx["inventory"]["id"]
        inv_v = inventory_version(inventory_id)
        intruder = make_store_associate_headers(ctx["s1"]["id"])

        validate_error(
            api.adjust_store_inventory(
                inventory_id,
                inventory_adjustment_payload(inv_v, 12, "CYCLE_COUNT"),
                intruder,
            ),
            "ERR_STORE_SCOPE_VIOLATION",
        )
        validate_error(
            api.adjust_store_inventory(
                inventory_id,
                inventory_adjustment_payload(inv_v + 5, 12, "CYCLE_COUNT"),
                intruder,
            ),
            "ERR_STORE_SCOPE_VIOLATION",
        )

        inventory = read_inventory(inventory_id)
        assert inventory["version"] == inv_v, (
            "both refusals are inert, including the one whose expected_inventory_version was "
            f"also stale, got version {inventory['version']} against {inv_v}"
        )
        assert inventory["on_hand_units"] == 12, (
            f"the counted figure was never written, got {inventory['on_hand_units']}"
        )

    def test_store_associate_cannot_restock_another_nodes_packaging_row(self, api):
        """PRD §2.1: "Concretely, when a `StoreAssociate` accepts, rejects, picks, packs or ships an assignment, or posts an inventory adjustment, or restocks packaging, the `store_id` of the targeted assignment, inventory row or packaging row must equal `X-User-ID`; a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."
        PRD §3.1: "Receiving packaging is a restock, available to a planner or to the node's own associate, which adds a supplied `added_units` count to `on_hand_units`, re-derives `reorder_flag`, and increments the row's `version`."

        Design: Corner/rbac/a_store_associate_cannot_write_another_nodes_rows_while_reads_stay_network_wide
        """
        ctx = _order_committed_to_the_second_node()

        validate_error(
            api.restock_packaging_supply(
                ctx["supply"]["id"],
                {"added_units": 5},
                make_store_associate_headers(ctx["s1"]["id"]),
            ),
            "ERR_STORE_SCOPE_VIOLATION",
        )

        supply = read_packaging(ctx["supply"]["id"])
        assert supply["on_hand_units"] == 4, (
            f"the refused restock added nothing, got {supply['on_hand_units']}"
        )
        assert supply["version"] == 1, (
            f"the refused restock mutated nothing, got version {supply['version']}"
        )

    def test_store_associate_reads_another_nodes_rows_because_reads_are_network_wide(
        self, api
    ):
        """PRD §2.1: "Reads are exempt: every list and detail endpoint is network-wide and is not scope-checked."
        PRD §2.1: "When `X-User-Role` is `StoreAssociate`, `X-User-ID` is the `id` of the acting `Store`; ownership checks on any resource that references a `Store` compare the resource's store foreign key to `X-User-ID`."

        Design: Corner/rbac/a_store_associate_cannot_write_another_nodes_rows_while_reads_stay_network_wide
        """
        ctx = _order_committed_to_the_second_node()
        outsider = make_store_associate_headers(ctx["s1"]["id"])

        assignment = validate_success(
            api.get_assignment(ctx["assignment"]["id"], outsider), 200
        )
        assert assignment["store_id"] == ctx["s2"]["id"], (
            "S1's associate reads an assignment owned by S2"
        )

        inventory = validate_success(
            api.get_store_inventory(ctx["inventory"]["id"], outsider), 200
        )
        assert inventory["store_id"] == ctx["s2"]["id"], (
            "S1's associate reads an inventory row owned by S2"
        )

        supply = validate_success(
            api.get_packaging_supply(ctx["supply"]["id"], outsider), 200
        )
        assert supply["store_id"] == ctx["s2"]["id"], (
            "S1's associate reads a packaging row owned by S2"
        )

        rows, meta = validate_paginated(
            api.list_store_inventories(outsider, params={"store_id": ctx["s2"]["id"]})
        )
        assert meta["total_count"] == 1, (
            "the list read is network-wide too, so S2's row is visible to S1's associate, got "
            f"total_count {meta['total_count']}"
        )
