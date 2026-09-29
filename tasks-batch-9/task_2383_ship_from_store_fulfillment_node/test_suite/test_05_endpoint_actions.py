"""Endpoint-level action semantics: node patch, packaging restock, the ops-run
bulk close, nested pickup creation and the conditional cost guardrail.

Every test builds its own network from scratch — the server is relaunched with
an empty database before each one.
"""

import pytest

from test_helpers import (
    CARRIER,
    NON_EXISTENT_UUID,
    PLANNER,
    add_order_line,
    api_client,
    assert_carrier_pickup,
    assert_node_performance_window,
    assert_packaging_supply,
    assert_store,
    assert_version_incremented,
    commit_routing,
    cost_comparison,
    create_carrier_pickup_payload,
    create_routing_run_payload,
    find_assignment,
    find_assignments,
    find_windows,
    intake_order,
    make_store_associate_headers,
    order_version,
    provisional_routing,
    read_order,
    read_packaging,
    read_store,
    register_node,
    register_nodes,
    register_sku,
    restock_packaging,
    set_clock,
    stock_inventory,
    stock_packaging,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_MORNING = "2026-08-03T09:00:00Z"
CLOCK_EVENING = "2026-08-03T18:00:00Z"


# ======================================================================
# module-private preambles
# ======================================================================


def _network_of_three_nodes() -> dict:
    """Clock at 09:00 and three nodes registered in the order S1, S3, S2.

    No SKU, no inventory and no order, so every node's first performance
    window stays empty.
    """
    set_clock(CLOCK_MORNING)
    s1, s3, s2 = register_nodes("S1", "S3", "S2")
    return {"s1": s1, "s3": s3, "s2": s2}


def _guardrail_order() -> dict:
    """A single hazmat-certified node holding 20 promise-able hazmat units, and
    a 20-unit EXPEDITED order to zone 1 whose store cost dwarfs the DC baseline.
    """
    set_clock(CLOCK_MORNING)
    store = register_node("S2")
    sku = register_sku("SKU-H")
    stock_inventory(store["id"], sku["id"], 22, 2)

    order = intake_order(
        order_code="O-C001",
        customer_ref="C-401",
        destination_zone=1,
        service_level="EXPEDITED",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    add_order_line(order["id"], sku["id"], 20, 6900)

    return {"store": store, "sku": sku, "order": read_order(order["id"])}


# ======================================================================
# PATCH /fulfillment-network/stores/{store_id}
# ======================================================================


class TestNodePatch:
    def test_patching_a_subset_of_node_fields_rescores_and_versions_the_node(self):
        """PRD §3.1: "A planner may later adjust a node's posture, supplying any subset of `daily_unit_capacity`, `staffed_labor_minutes`, `labor_standard_minutes_per_order`, `pick_labor_minutes_per_unit`, `labor_rate_cents_per_minute`, `cutoff_utc_minutes` and `hazmat_certified`."
        PRD §3.1: "Such an adjustment recomputes `eligibility_score` using whichever basis the node currently carries, and increments the node's `version`."
        PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
        PRD §3.3: "That headroom is divided by a reference of 200 units, the quotient is capped at 1, and the result is multiplied by a weight of 40."
        PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

        Design: Corner/endpoints/patching_a_node_rescores_it_and_bumps_its_version
        """
        set_clock(CLOCK_MORNING)
        store = register_node("S1")

        assert store["daily_unit_capacity"] == 120, "the node registers at capacity 120"
        assert store["eligibility_score"] == pytest.approx(72.00, abs=0.01), (
            "a cold-start node at capacity 120 of a 200-unit reference and 480 "
            f"staffed minutes scores 72.00, got {store['eligibility_score']}"
        )
        assert store["version"] == 1, "a freshly registered node is at version 1"

        response = api_client.patch_store(
            store["id"],
            {
                "daily_unit_capacity": 200,
                "cutoff_utc_minutes": 1080,
                "hazmat_certified": True,
            },
            PLANNER,
        )
        patched = validate_success(response, expected_status=200)
        assert_store(patched)

        assert patched["daily_unit_capacity"] == 200, (
            "the patched daily_unit_capacity must be 200"
        )
        assert patched["cutoff_utc_minutes"] == 1080, (
            "the patched cutoff_utc_minutes must be 1080"
        )
        assert patched["hazmat_certified"] is True, (
            "the patched hazmat_certified must be true"
        )

        assert patched["eligibility_score"] == pytest.approx(88.00, abs=0.01), (
            "capacity headroom 200 of the 200-unit reference caps the capacity "
            "component at 40, so the recomputed eligibility_score is 88.00, got "
            f"{patched['eligibility_score']}"
        )
        assert patched["eligibility_score_basis"] == "COLD_START", (
            "the node still has zero closed windows, so the basis stays COLD_START"
        )
        assert_version_incremented(patched["version"], store["version"])
        assert patched["version"] == 2, (
            f"one adjustment moves the node to version 2, got {patched['version']}"
        )

    def test_patching_a_node_leaves_every_unpatched_field_untouched(self):
        """PRD §3.1: "A planner may later adjust a node's posture, supplying any subset of `daily_unit_capacity`, `staffed_labor_minutes`, `labor_standard_minutes_per_order`, `pick_labor_minutes_per_unit`, `labor_rate_cents_per_minute`, `cutoff_utc_minutes` and `hazmat_certified`."
        PRD §2.10: "Every posture change except reactivation is produced by the operations run; reactivation is a deliberate planner action."

        Design: Corner/endpoints/patching_a_node_rescores_it_and_bumps_its_version
        """
        set_clock(CLOCK_MORNING)
        store = register_node("S1")

        response = api_client.patch_store(
            store["id"],
            {
                "daily_unit_capacity": 200,
                "cutoff_utc_minutes": 1080,
                "hazmat_certified": True,
            },
            PLANNER,
        )
        patched = validate_success(response, expected_status=200)

        assert patched["store_code"] == "S1-DOWNTOWN", (
            "store_code is not in the patchable subset and must be unchanged"
        )
        assert patched["region_code"] == "WEST", (
            "region_code is not in the patchable subset and must be unchanged"
        )
        assert patched["origin_zone"] == 4, (
            "origin_zone is not in the patchable subset and must be unchanged"
        )
        assert patched["staffed_labor_minutes"] == 480, (
            "staffed_labor_minutes was not supplied and must stay 480"
        )
        assert patched["labor_standard_minutes_per_order"] == 12, (
            "labor_standard_minutes_per_order was not supplied and must stay 12"
        )
        assert patched["pick_labor_minutes_per_unit"] == 3, (
            "pick_labor_minutes_per_unit was not supplied and must stay 3"
        )
        assert patched["labor_rate_cents_per_minute"] == 42, (
            "labor_rate_cents_per_minute was not supplied and must stay 42"
        )
        assert patched["node_status"] == "ELIGIBLE", (
            "a planner adjustment is not a posture change, so node_status stays ELIGIBLE"
        )

        assert read_store(store["id"])["store_code"] == "S1-DOWNTOWN", (
            "the persisted row must agree with the patch response"
        )


# ======================================================================
# POST /fulfillment-network/packaging-supplies/{supply_id}/restock
# ======================================================================


class TestPackagingRestock:
    def test_restock_adds_units_and_flips_the_reorder_flag_off(self):
        """PRD §3.1: "Creation sets `lifetime_consumed_units` to 0 and derives `reorder_flag` as true exactly when `on_hand_units` is less than or equal to `reorder_point_units`."
        PRD §3.1: "Receiving packaging is a restock, available to a planner or to the node's own associate, which adds a supplied `added_units` count to `on_hand_units`, re-derives `reorder_flag`, and increments the row's `version`."
        PRD §2.1: "Concretely, when a `StoreAssociate` accepts, rejects, picks, packs or ships an assignment, or posts an inventory adjustment, or restocks packaging, the `store_id` of the targeted assignment, inventory row or packaging row must equal `X-User-ID`; a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/endpoints/restocking_packaging_clears_the_reorder_flag
        """
        set_clock(CLOCK_MORNING)
        store = register_node("S1")
        supply = stock_packaging(
            store["id"], "MEDIUM_BOX", on_hand_units=1, reorder_point_units=5
        )

        assert_packaging_supply(supply)
        assert supply["reorder_flag"] is True, (
            "on_hand 1 is at or below the reorder point 5, so reorder_flag starts true"
        )
        assert supply["lifetime_consumed_units"] == 0, (
            "creation sets lifetime_consumed_units to 0"
        )
        assert supply["version"] == 1, "a freshly stocked packaging row is at version 1"

        restocked = restock_packaging(
            supply["id"], 20, headers=make_store_associate_headers(store["id"])
        )
        assert_packaging_supply(restocked)

        assert restocked["on_hand_units"] == 21, (
            "20 added units on top of 1 on hand gives 21, got "
            f"{restocked['on_hand_units']}"
        )
        assert restocked["reorder_flag"] is False, (
            "21 on hand is above the reorder point 5, so the re-derived reorder_flag "
            "is false"
        )
        assert restocked["lifetime_consumed_units"] == 0, (
            "a restock consumes nothing, so lifetime_consumed_units stays 0"
        )
        assert_version_incremented(restocked["version"], supply["version"])
        assert restocked["version"] == 2, (
            f"one restock moves the row to version 2, got {restocked['version']}"
        )

        persisted = read_packaging(supply["id"])
        assert persisted["on_hand_units"] == 21, (
            "the persisted packaging row must agree with the restock response"
        )
        assert persisted["reorder_flag"] is False, (
            "the persisted reorder_flag must agree with the restock response"
        )

    def test_a_restocked_row_leaves_the_reorder_flag_filter(self):
        """PRD §3.1: "Receiving packaging is a restock, available to a planner or to the node's own associate, which adds a supplied `added_units` count to `on_hand_units`, re-derives `reorder_flag`, and increments the row's `version`."
        PRD §2.4: "Packaging rows may be filtered by `store_id`, `package_type` and `reorder_flag`."
        PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

        Design: Corner/endpoints/restocking_packaging_clears_the_reorder_flag
        """
        set_clock(CLOCK_MORNING)
        store = register_node("S1")
        supply = stock_packaging(
            store["id"], "MEDIUM_BOX", on_hand_units=1, reorder_point_units=5
        )

        below, below_meta = validate_paginated(
            api_client.list_packaging_supplies(
                PLANNER, params={"store_id": store["id"], "reorder_flag": "true"}
            )
        )
        assert below_meta["total_count"] == 1, (
            "before the restock the row is below its reorder point, so the "
            f"reorder_flag=true filter matches 1 row, got {below_meta['total_count']}"
        )
        assert [row["id"] for row in below] == [supply["id"]], (
            "the reorder_flag=true filter must return exactly the under-stocked row"
        )

        restock_packaging(
            supply["id"], 20, headers=make_store_associate_headers(store["id"])
        )

        cleared, cleared_meta = validate_paginated(
            api_client.list_packaging_supplies(
                PLANNER, params={"store_id": store["id"], "reorder_flag": "false"}
            )
        )
        assert cleared_meta["total_count"] == 1, (
            "after the restock the row no longer needs reordering, so the "
            f"reorder_flag=false filter matches 1 row, got {cleared_meta['total_count']}"
        )
        assert [row["id"] for row in cleared] == [supply["id"]], (
            "the reorder_flag=false filter must return exactly the restocked row"
        )

        still_below, still_below_meta = validate_paginated(
            api_client.list_packaging_supplies(
                PLANNER, params={"store_id": store["id"], "reorder_flag": "true"}
            )
        )
        assert still_below_meta["total_count"] == 0, (
            "the restocked row must have left the reorder_flag=true filter, got "
            f"{still_below_meta['total_count']} rows"
        )
        assert still_below == [], "no packaging row is below its reorder point any more"


# ======================================================================
# POST /fulfillment-network/performance-windows/close
# ======================================================================


class TestOpsRunClosesOpenWindows:
    def test_ops_run_closes_every_open_window_in_ascending_node_creation_order(self):
        """PRD §3.9: "It executes seven steps in exactly this order, and it answers with the windows it closed, in ascending node `created_at` order."
        PRD §3.9: "Each window's `status` becomes `CLOSED`, its `closed_at_utc` is set to the clock instant, and each node's `units_committed_epoch` is reset to 0."
        PRD §3.1: "Registration also opens the node's first performance window at the network's current epoch — the highest `epoch` across all existing windows, or 1 when no window exists anywhere yet — with `opened_at_utc` set to the clock instant and `closed_at_utc` null."

        Design: Corner/endpoints/the_ops_run_closes_every_open_window_in_store_creation_order
        """
        nodes = _network_of_three_nodes()

        set_clock(CLOCK_EVENING)
        closed = validate_success(
            api_client.close_performance_windows(PLANNER), expected_status=200
        )

        assert len(closed) == 3, (
            f"three nodes each hold one OPEN window, so three close, got {len(closed)}"
        )
        assert [row["store_id"] for row in closed] == [
            nodes["s1"]["id"],
            nodes["s3"]["id"],
            nodes["s2"]["id"],
        ], (
            "the closed windows must come back in ascending node created_at order "
            "(S1-DOWNTOWN, then S3-SUBURB, then S2-HARBOR), never by node id"
        )

        for row in closed:
            assert_node_performance_window(row)
            assert row["status"] == "CLOSED", (
                f"every closed window's status must be CLOSED, got {row['status']}"
            )
            assert row["epoch"] == 1, (
                f"the first window of every node sits at epoch 1, got {row['epoch']}"
            )
            assert row["closed_at_utc"] is not None, (
                "closed_at_utc is set to the clock instant on close"
            )
            assert row["closed_at_utc"].startswith("2026-08-03T18:00:00"), (
                "closed_at_utc must be the clock instant 2026-08-03T18:00:00Z, got "
                f"{row['closed_at_utc']}"
            )

        for store in (nodes["s1"], nodes["s3"], nodes["s2"]):
            assert read_store(store["id"])["units_committed_epoch"] == 0, (
                "the close resets each node's units_committed_epoch to 0"
            )

    def test_an_empty_window_measures_as_inert_and_changes_no_posture(self):
        """PRD §3.9: "From that set: `assignments_created` is the count of all of them; `assignments_shipped`, `assignments_rejected` and `assignments_cancelled` are the counts at `status` `SHIPPED`, `REJECTED` and `CANCELLED` respectively; `units_promised` is the sum of `assigned_units` over all of them; and `units_shipped` is the sum of `picked_units` over those at `SHIPPED`."
        PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."
        PRD §3.9: "`avg_cycle_time_minutes` is exactly 0.00 when `assignments_shipped` is 0, and otherwise the sum of `cycle_time_minutes` over the shipped assignments divided by `assignments_shipped`, rounded half-up to two decimal places."
        PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
        PRD §3.9: "`node_action` is `NONE` when `assignments_created` is 0 — an empty window is inert."
        PRD §3.9: "`consecutive_breach_windows` is then set to 0 when the window was non-empty and not breached, incremented by 1 when the window was non-empty and breached, and left completely unchanged when the window was empty — so an empty window never changes posture and never resets the breach counter."
        PRD §3.9: "The window's `cost_index_bps` is 0 when `dc_cost_per_order_cents` is 0, and otherwise `store_cost_per_order_cents` multiplied by 10000, divided by `dc_cost_per_order_cents`, rounded half-up."

        Design: Corner/endpoints/the_ops_run_closes_every_open_window_in_store_creation_order
        """
        nodes = _network_of_three_nodes()

        set_clock(CLOCK_EVENING)
        closed = validate_success(
            api_client.close_performance_windows(PLANNER), expected_status=200
        )

        for row in closed:
            assert row["assignments_created"] == 0, (
                "no assignment was ever created, so assignments_created is 0"
            )
            assert row["units_promised"] == 0, (
                "no assignment was ever created, so units_promised is 0"
            )
            assert row["units_shipped"] == 0, (
                "nothing shipped, so units_shipped is 0"
            )
            assert row["fill_rate"] == pytest.approx(1.0000, abs=0.01), (
                f"fill_rate is exactly 1.0000 when units_promised is 0, got "
                f"{row['fill_rate']}"
            )
            assert row["avg_cycle_time_minutes"] == pytest.approx(0.00, abs=0.01), (
                "avg_cycle_time_minutes is exactly 0.00 when assignments_shipped is 0, "
                f"got {row['avg_cycle_time_minutes']}"
            )
            assert row["cancellation_rate"] == pytest.approx(0.0000, abs=0.01), (
                "cancellation_rate is exactly 0.0000 when assignments_created is 0, "
                f"got {row['cancellation_rate']}"
            )
            assert row["breach_flags"] == [], (
                f"an empty window breaches nothing, got {row['breach_flags']}"
            )
            assert row["breached"] is False, (
                "breached is true exactly when breach_flags is non-empty"
            )
            assert row["node_action"] == "NONE", (
                f"an empty window is inert, so node_action is NONE, got "
                f"{row['node_action']}"
            )
            assert row["cost_index_bps"] == 0, (
                "with no shipped assignment dc_cost_per_order_cents is 0, so the "
                f"window's cost_index_bps is 0, got {row['cost_index_bps']}"
            )

        for store in (nodes["s1"], nodes["s3"], nodes["s2"]):
            after = read_store(store["id"])
            assert after["node_status"] == "ELIGIBLE", (
                f"an empty window never changes posture, got {after['node_status']} "
                f"for {after['store_code']}"
            )
            assert after["consecutive_breach_windows"] == 0, (
                "an empty window never touches consecutive_breach_windows, got "
                f"{after['consecutive_breach_windows']} for {after['store_code']}"
            )
            assert after["deactivated_at_epoch"] is None, (
                "no node was deactivated, so deactivated_at_epoch stays null"
            )

    def test_ops_run_writes_review_scores_and_rescores_on_the_trailing_window(self):
        """PRD §3.9: "Each window's `node_action` is decided and applied, and each node's `review_score` is written on the governance-blended basis of §3.3 from the pre-reset counters."
        PRD §3.3: "`review_score` blends two windows: seven tenths of the performance ratio of the window being closed plus three tenths of the performance ratio of the previous closed window, or, when no previous closed window exists, the ratio of the window being closed on its own."
        PRD §3.3: "For any closed performance window, that window's performance ratio is one half of its `fill_rate`, plus three tenths of one minus its `cancellation_rate`, plus two tenths of its cycle-time factor."
        PRD §3.3: "That headroom is divided by a reference of eight staffed hours, the quotient is capped at 1, and the result is multiplied by a weight of 30."
        PRD §3.9: "Every node whose `node_status` is `ELIGIBLE` or `PROBATION` has its `eligibility_score` recomputed against the just-closed window, with `eligibility_score_basis` set to `TRAILING_WINDOW`."

        Design: Corner/endpoints/the_ops_run_closes_every_open_window_in_store_creation_order
        """
        nodes = _network_of_three_nodes()

        set_clock(CLOCK_EVENING)
        validate_success(
            api_client.close_performance_windows(PLANNER), expected_status=200
        )

        expected = {"s1": 84.00, "s3": 100.00, "s2": 60.75}
        for key, score in expected.items():
            after = read_store(nodes[key]["id"])
            assert after["review_score"] == pytest.approx(score, abs=0.01), (
                f"{after['store_code']} must carry review_score {score} against an "
                f"empty window whose performance ratio is 1.0, got "
                f"{after['review_score']}"
            )
            assert after["eligibility_score"] == pytest.approx(score, abs=0.01), (
                f"{after['store_code']} must be rescored to {score} against the "
                f"just-closed window, got {after['eligibility_score']}"
            )
            assert after["eligibility_score_basis"] == "TRAILING_WINDOW", (
                "step 7 sets eligibility_score_basis to TRAILING_WINDOW, got "
                f"{after['eligibility_score_basis']}"
            )

    def test_ops_run_opens_one_next_epoch_window_per_routable_node(self):
        """PRD §3.9: "A new performance window at `status` `OPEN` and at the previous `epoch` plus 1 is created for every node whose `node_status` is `ELIGIBLE` or `PROBATION`, with `opened_at_utc` at the clock instant and `closed_at_utc` null."
        PRD §2.4: "Performance windows may be filtered by `store_id`, `epoch`, `status` and `breached`."

        Design: Corner/endpoints/the_ops_run_closes_every_open_window_in_store_creation_order
        """
        nodes = _network_of_three_nodes()

        set_clock(CLOCK_EVENING)
        validate_success(
            api_client.close_performance_windows(PLANNER), expected_status=200
        )

        open_rows, open_meta = validate_paginated(
            api_client.list_performance_windows(PLANNER, params={"status": "OPEN"})
        )
        assert open_meta["total_count"] == 3, (
            "each of the three ELIGIBLE nodes gets one next-epoch window, got "
            f"{open_meta['total_count']}"
        )
        assert len(open_rows) == 3, (
            f"three OPEN windows must come back, got {len(open_rows)}"
        )
        for row in open_rows:
            assert row["epoch"] == 2, (
                f"the next epoch is the previous epoch plus 1, got {row['epoch']}"
            )
            assert row["closed_at_utc"] is None, (
                "a newly opened window carries a null closed_at_utc"
            )
            assert row["opened_at_utc"].startswith("2026-08-03T18:00:00"), (
                "opened_at_utc is the clock instant 2026-08-03T18:00:00Z, got "
                f"{row['opened_at_utc']}"
            )

        assert {row["store_id"] for row in open_rows} == {
            nodes["s1"]["id"],
            nodes["s3"]["id"],
            nodes["s2"]["id"],
        }, "every routable node must own exactly one of the new OPEN windows"

        for key in ("s1", "s3", "s2"):
            rows = find_windows(store_id=nodes[key]["id"])
            assert len(rows) == 2, (
                f"each node holds its closed epoch-1 window plus a new epoch-2 "
                f"window, got {len(rows)}"
            )


# ======================================================================
# POST /fulfillment-network/stores/{store_id}/carrier-pickups
# ======================================================================


class TestNestedPickupCreation:
    def test_pickup_takes_its_node_from_the_path_and_is_visible_under_that_filter(self):
        """PRD §3.6: "Pickup windows are scheduled per node by a `CarrierCoordinator` or a `NetworkPlanner`, with a `carrier_code` identifying the carrier, an inclusive `window_start_utc`, an exclusive `window_end_utc` that must be strictly later (otherwise `ERR_INVALID_WINDOW`), and a `parcel_capacity` of at least 1 giving the parcels the carrier will accept in that window."
        PRD §3.6: "A new window begins at `status` `SCHEDULED` with `reserved_parcels` 0."
        PRD §2.4: "Carrier pickups may be filtered by `store_id`, `status` and `carrier_code`."

        Design: Corner/endpoints/pickups_are_created_through_the_nested_store_path
        """
        set_clock(CLOCK_MORNING)
        s1 = register_node("S1")
        s3 = register_node("S3")

        response = api_client.create_carrier_pickup(
            s1["id"],
            create_carrier_pickup_payload(
                carrier_code="ACME",
                window_start_utc="2026-08-03T09:30:00Z",
                window_end_utc="2026-08-03T11:00:00Z",
                parcel_capacity=3,
            ),
            CARRIER,
        )
        pickup = validate_success(response, expected_status=201)
        assert_carrier_pickup(pickup)

        assert pickup["store_id"] == s1["id"], (
            "the pickup's store_id comes from the path node, got "
            f"{pickup['store_id']}"
        )
        assert pickup["carrier_code"] == "ACME", "carrier_code must be stored as sent"
        assert pickup["parcel_capacity"] == 3, "parcel_capacity must be stored as sent"
        assert pickup["status"] == "SCHEDULED", (
            f"a new window begins at SCHEDULED, got {pickup['status']}"
        )
        assert pickup["reserved_parcels"] == 0, (
            f"a new window begins with reserved_parcels 0, got "
            f"{pickup['reserved_parcels']}"
        )

        mine, mine_meta = validate_paginated(
            api_client.list_carrier_pickups(
                PLANNER, params={"store_id": s1["id"], "carrier_code": "ACME"}
            )
        )
        assert mine_meta["total_count"] == 1, (
            "the node-and-carrier filter matches exactly the one scheduled window, "
            f"got {mine_meta['total_count']}"
        )
        assert [row["id"] for row in mine] == [pickup["id"]], (
            "the filtered read must return exactly the window scheduled at that node"
        )

        sibling, sibling_meta = validate_paginated(
            api_client.list_carrier_pickups(PLANNER, params={"store_id": s3["id"]})
        )
        assert sibling_meta["total_count"] == 0, (
            "the window belongs to the path node only, so the sibling node shows "
            f"none, got {sibling_meta['total_count']}"
        )
        assert sibling == [], "no pickup may be visible under the sibling node"

    def test_scheduling_a_pickup_at_an_unknown_node_is_refused_before_any_row_exists(
        self,
    ):
        """PRD §2.4: "Scheduling a pickup at a node that does not exist therefore returns `ERR_STORE_NOT_FOUND` and never reaches any pickup-level rule."
        PRD §2.4: "Carrier pickups may be filtered by `store_id`, `status` and `carrier_code`."

        Design: Corner/endpoints/pickups_are_created_through_the_nested_store_path
        """
        set_clock(CLOCK_MORNING)
        register_node("S1")

        response = api_client.create_carrier_pickup(
            NON_EXISTENT_UUID,
            create_carrier_pickup_payload(
                carrier_code="ACME",
                window_start_utc="2026-08-03T09:30:00Z",
                window_end_utc="2026-08-03T11:00:00Z",
                parcel_capacity=3,
            ),
            CARRIER,
        )
        validate_error(response, "ERR_STORE_NOT_FOUND")

        rows, meta = validate_paginated(api_client.list_carrier_pickups(PLANNER))
        assert meta["total_count"] == 0, (
            "the refused request never reaches any pickup-level rule, so no orphan "
            f"pickup row exists, got {meta['total_count']}"
        )
        assert rows == [], "no pickup row may be created by a refused request"


# ======================================================================
# POST /fulfillment-network/orders/{order_id}/routing-runs — cost guardrail
# ======================================================================


class TestCostGuardrail:
    def test_commit_above_the_cost_index_ceiling_is_refused_and_changes_nothing(self):
        """PRD §3.4: "The fiscal guardrail then applies: a `COMMIT` run whose `projected_cost_index_bps` exceeds 15000 basis points is refused with `ERR_COST_INDEX_GUARDRAIL` unless the caller passed `override_cost_guardrail` as true, in which case the run proceeds and records `guardrail_overridden` as true."
        PRD §3.4: "`PROVISIONAL` runs are never blocked, and neither are system reroute runs."
        PRD §3.4: "A `PROVISIONAL` run persists candidate rows and the run's projections with `status` `EVALUATED`; it creates no assignment, moves no reservation, emits no notification, and reports the cost guardrail without ever being blocked by it."
        PRD §3.4: "`projected_cost_index_bps` is `projected_cost_cents` multiplied by 10000, divided by `projected_dc_cost_cents`, rounded half-up — and 0 when the baseline is 0."
        PRD §3.4: "A successful run re-derives the order's `routing_status`, recomputes `split_count` — the number of the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — recomputes `provisional_cost_cents`, `dc_baseline_cost_cents` and `cost_index_bps`, and increments the order's `version`."

        Design: Corner/endpoints/commit_is_refused_by_the_cost_guardrail_unless_overridden
        """
        ctx = _guardrail_order()
        order_id = ctx["order"]["id"]

        evaluated = provisional_routing(order_id)
        assert evaluated["status"] == "EVALUATED", (
            "a PROVISIONAL run is never blocked by the guardrail and settles at "
            f"EVALUATED, got {evaluated['status']}"
        )
        assert evaluated["projected_cost_cents"] == 6740, (
            "the projected store cost of the 20-unit EXPEDITED allocation at S2 is "
            f"6740 cents, got {evaluated['projected_cost_cents']}"
        )
        assert evaluated["projected_dc_cost_cents"] == 3850, (
            "the zone-1 DC baseline for 20 units is 3850 cents, got "
            f"{evaluated['projected_dc_cost_cents']}"
        )
        assert evaluated["projected_cost_index_bps"] == 17506, (
            "6740 * 10000 / 3850 rounds half-up to 17506 basis points, got "
            f"{evaluated['projected_cost_index_bps']}"
        )
        assert evaluated["guardrail_overridden"] is False, (
            "no override was requested on the PROVISIONAL run"
        )
        assert find_assignments(order_id=order_id) == [], (
            "a PROVISIONAL run creates no assignment"
        )

        before = read_order(order_id)

        response = api_client.create_routing_run(
            order_id,
            create_routing_run_payload(before["version"], "COMMIT"),
            PLANNER,
        )
        validate_error(response, "ERR_COST_INDEX_GUARDRAIL")

        after = read_order(order_id)
        assert after["version"] == before["version"], (
            "only a successful run increments the order's version, so the refused "
            f"COMMIT leaves it at {before['version']}, got {after['version']}"
        )
        assert after["routing_status"] == before["routing_status"], (
            "the refused COMMIT re-derives nothing, so routing_status stays "
            f"{before['routing_status']}, got {after['routing_status']}"
        )
        assert find_assignments(order_id=order_id) == [], (
            "a COMMIT blocked by the cost guardrail creates no assignment"
        )

    def test_override_admits_the_commit_and_records_the_guardrail_override(self):
        """PRD §3.4: "The fiscal guardrail then applies: a `COMMIT` run whose `projected_cost_index_bps` exceeds 15000 basis points is refused with `ERR_COST_INDEX_GUARDRAIL` unless the caller passed `override_cost_guardrail` as true, in which case the run proceeds and records `guardrail_overridden` as true."
        PRD §3.4: "A `COMMIT` run runs the supersede step first, creates assignments and reservations, emits notifications, and is blocked by the cost guardrail unless `override_cost_guardrail` is true."
        PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
        PRD §3.4: "The winner's `selected` flag is set to true and its `assigned_units` is set equal to its `coverage_units`."
        PRD §3.8: "Savings versus the distribution centre are the baseline minus the store cost, and may of course be negative."

        Design: Corner/endpoints/commit_is_refused_by_the_cost_guardrail_unless_overridden
        """
        ctx = _guardrail_order()
        order_id = ctx["order"]["id"]

        run = commit_routing(
            order_id, expected_order_version=order_version(order_id),
            override_cost_guardrail=True,
        )
        assert run["status"] == "COMMITTED", (
            f"the overridden COMMIT run must settle at COMMITTED, got {run['status']}"
        )
        assert run["guardrail_overridden"] is True, (
            "a run admitted by override_cost_guardrail records guardrail_overridden true"
        )
        assert run["projected_cost_index_bps"] == 17506, (
            "the override does not change the projection: 17506 basis points, got "
            f"{run['projected_cost_index_bps']}"
        )

        assignment = find_assignment(order_id=order_id, store_id=ctx["store"]["id"])
        assert assignment["assigned_units"] == 20, (
            "the winning node covers all 20 open units, got "
            f"{assignment['assigned_units']}"
        )
        assert assignment["provisional_cost_cents"] == 6544, (
            "the assignment's provisional cost is 6544 cents, got "
            f"{assignment['provisional_cost_cents']}"
        )

        order = read_order(order_id)
        assert order["provisional_cost_cents"] == 6740, (
            "the order-level provisional cost is 6740 cents, got "
            f"{order['provisional_cost_cents']}"
        )
        assert order["cost_index_bps"] == 17506, (
            f"the order's cost_index_bps is 17506, got {order['cost_index_bps']}"
        )

        comparison = cost_comparison(order_id)
        assert comparison["store_cost_cents"] == 6740, (
            f"the comparison read reports a store cost of 6740, got "
            f"{comparison['store_cost_cents']}"
        )
        assert comparison["dc_baseline_cost_cents"] == 3850, (
            "the comparison read reports a DC baseline of 3850, got "
            f"{comparison['dc_baseline_cost_cents']}"
        )
        assert comparison["savings_vs_dc_cents"] == -2890, (
            "3850 minus 6740 is a negative saving of -2890 cents, got "
            f"{comparison['savings_vs_dc_cents']}"
        )
