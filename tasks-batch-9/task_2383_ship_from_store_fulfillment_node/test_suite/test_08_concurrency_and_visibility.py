"""Stale-version protection on the three guarded writes, and immediate visibility.

The three guarded writes named by the PRD — starting a routing run, tendering a
parcel and posting an inventory adjustment — each carry a required expected-version
field for a *parent* row. Every test here is deterministic rather than a race: the
first write is performed, the parent's version moves, and the second write is then
replayed with the version captured before it moved. The last group asserts the
other half of that model: one COMMIT call settles every row it touches, so the very
next read already sees the final figures.

Every test builds its whole world from an empty database.
"""

import pytest

from test_helpers import (
    PLANNER,
    accept,
    add_order_line,
    adjust_inventory,
    assert_version_incremented,
    commit_routing,
    create_routing_run_payload,
    find_assignment,
    find_assignment_lines,
    find_assignments,
    find_routing_candidates,
    find_routing_runs,
    intake_order,
    inventory_adjustment_payload,
    inventory_version,
    make_store_associate_headers,
    order_version,
    pack,
    pick_full,
    pickup_version,
    read_assignment,
    read_inventory,
    read_order,
    read_order_line,
    read_pickup,
    read_routing_run,
    read_store,
    schedule_pickup,
    setup_network,
    setup_order_with_lines,
    ship,
    ship_payload,
    validate_error,
    validate_success,
)


# ======================================================================
# Shared preambles
# ======================================================================


def _order_whose_version_moved_after_the_planner_read() -> dict:
    """Node S1 stocking SKU-A 12/2 and SKU-B 6/1 at 09:00Z, plus order O-N001
    which gets an A x 2 line, is then read by the planner, and only afterwards
    gets a B x 1 line — so the planner's captured version is one behind."""
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A", "SKU-B"),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2), ("S1", "SKU-B", 6, 1)],
    )
    order = intake_order(
        order_code="O-N001",
        customer_ref="C-1000",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-04T15:00:00Z",
    )
    add_order_line(order["id"], net["skus"]["SKU-A"]["id"], 2, 4500)
    stale_order_version = order_version(order["id"])
    add_order_line(order["id"], net["skus"]["SKU-B"]["id"], 1, 1900)
    return {
        "store": net["stores"]["S1"],
        "order": order,
        "stale_order_version": stale_order_version,
    }


def _two_packed_parcels_contending_for_one_pickup_window() -> dict:
    """Node S1 with SKU-A 12/2 and a MEDIUM_BOX supply of 4, one pickup window
    08:30Z-10:00Z of capacity 5 whose version is read up front, and two
    two-unit orders each committed to S1 and carried to PACKED. The clock stays
    at 09:00Z throughout."""
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2)],
        packaging=[("S1", "MEDIUM_BOX", 4, 1)],
    )
    store = net["stores"]["S1"]
    sku = net["skus"]["SKU-A"]

    pickup = schedule_pickup(
        store["id"],
        carrier_code="UPS",
        window_start_utc="2026-08-03T08:30:00Z",
        window_end_utc="2026-08-03T10:00:00Z",
        parcel_capacity=5,
    )
    stale_pickup_version = pickup["version"]

    packed = []
    for order_code, customer_ref in (("O-O001", "C-1010"), ("O-O002", "C-1011")):
        built = setup_order_with_lines(
            [(sku["id"], 2, 4500)],
            order_code=order_code,
            customer_ref=customer_ref,
            destination_zone=4,
            service_level="GROUND",
            promised_ship_by_utc="2026-08-04T15:00:00Z",
        )
        commit_routing(built["order"]["id"])
        assignment = find_assignment(
            order_id=built["order"]["id"], store_id=store["id"]
        )
        accept(assignment["id"], store["id"])
        pick_full(assignment["id"], store["id"])
        pack(assignment["id"], store["id"], "MEDIUM_BOX")
        packed.append(read_assignment(assignment["id"]))

    return {
        "store": store,
        "sku": sku,
        "pickup": pickup,
        "stale_pickup_version": stale_pickup_version,
        "first": packed[0],
        "second": packed[1],
    }


def _inventory_row_read_once_by_two_counters() -> dict:
    """One node, one SKU and one inventory row at on-hand 12 / safety 2, whose
    version is captured once and then replayed by two separate counts."""
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2)],
    )
    inventory = net["inventories"][("S1", "SKU-A")]
    return {
        "store": net["stores"]["S1"],
        "inventory": inventory,
        "stale_inventory_version": inventory["version"],
    }


def _network_where_only_the_first_node_stocks_the_ordered_sku() -> dict:
    """S1 (registered first) stocks SKU-A 12/2 and S3 stocks nothing, with a
    single A x 2 order waiting to be committed at 09:00Z."""
    net = setup_network(
        node_presets=("S1", "S3"),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2)],
    )
    built = setup_order_with_lines(
        [(net["skus"]["SKU-A"]["id"], 2, 4500)],
        order_code="O-P001",
        customer_ref="C-1020",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-04T15:00:00Z",
    )
    return {
        "s1": net["stores"]["S1"],
        "s3": net["stores"]["S3"],
        "inventory": net["inventories"][("S1", "SKU-A")],
        "order": built["order"],
        "line": built["lines"][0],
    }


# ======================================================================
# expected_order_version on a COMMIT routing run
# ======================================================================


def test_commit_run_refused_when_expected_order_version_predates_a_new_line(api):
    """PRD §2.8: "`POST /fulfillment-network/orders/{order_id}/routing-runs` requires `expected_order_version`, carrying the client's last observed `version` of the target `CustomerOrder`."
    PRD §2.8: "If it does not match the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §2.8: "In each case the guard field is a required, non-optional part of the request body, it must carry the client's last observed `version` of the named parent, and a value that does not equal that parent's current `version` is rejected before any state changes."
    PRD §3.2: "Adding a line recomputes the order's `total_units`, `unassigned_units` and `dc_baseline_cost_cents`, and increments the order's `version`."

    The order's version advanced because a second demand line was appended after
    the planner read it, so the otherwise valid COMMIT payload is refused at the
    guard and leaves no routing run and no assignment behind.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_order_version_blocks_a_commit_run_that_would_supersede_unseen_lines
    """
    ctx = _order_whose_version_moved_after_the_planner_read()
    order_id = ctx["order"]["id"]
    stale = ctx["stale_order_version"]

    assert stale == 2, (
        "intake mints version 1 and the first line append increments it by "
        f"exactly 1, so the planner's captured version should be 2, got {stale}"
    )
    assert order_version(order_id) == 3, (
        "the second line append should have moved the order to version 3"
    )

    response = api.create_routing_run(
        order_id, create_routing_run_payload(stale, "COMMIT"), PLANNER
    )
    validate_error(response, "ERR_STALE_ORDER_VERSION")

    assert find_routing_runs(order_id=order_id) == [], (
        "a guard rejected before any state changes must not persist a RoutingRun row"
    )
    assert find_assignments(order_id=order_id) == [], (
        "the refused COMMIT must not have created any FulfillmentAssignment"
    )

    after = read_order(order_id)
    assert after["routing_status"] == "UNROUTED", (
        "no routing run exists for the order, so routing_status stays UNROUTED, got "
        f"{after['routing_status']}"
    )
    assert after["version"] == 3, (
        f"the refused run must not mutate the order: version should still be 3, got {after['version']}"
    )


def test_commit_run_retried_with_the_fresh_order_version_covers_both_lines(api):
    """PRD §2.8: "If it does not match the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §3.4: "A successful run re-derives the order's `routing_status`, recomputes `split_count` — the number of the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — recomputes `provisional_cost_cents`, `dc_baseline_cost_cents` and `cost_index_bps`, and increments the order's `version`."
    PRD §3.5: "Alongside the assignment, one assignment line is created per demand line served, each carrying `assignment_id`, `order_line_id` and `units_assigned` — immutable after creation — with `units_picked` and `units_cancelled` both starting at 0."
    PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
    PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."

    Nothing about the payload changes except the guard value: once the planner
    re-reads the order it commits successfully, covering the line it had never
    seen, and the accepted write moves the guarded parent by exactly one.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_order_version_blocks_a_commit_run_that_would_supersede_unseen_lines
    """
    ctx = _order_whose_version_moved_after_the_planner_read()
    order_id = ctx["order"]["id"]

    refused = api.create_routing_run(
        order_id,
        create_routing_run_payload(ctx["stale_order_version"], "COMMIT"),
        PLANNER,
    )
    validate_error(refused, "ERR_STALE_ORDER_VERSION")

    fresh = order_version(order_id)
    assert fresh == 3, f"the order's live version should be 3, got {fresh}"

    run = validate_success(
        api.create_routing_run(
            order_id, create_routing_run_payload(fresh, "COMMIT"), PLANNER
        ),
        201,
    )
    assert run["status"] == "COMMITTED", (
        f"the retry should commit, got status {run['status']}"
    )
    assert run["selected_store_count"] == 1, (
        f"one node covers all three units, got selected_store_count {run['selected_store_count']}"
    )

    assignment = find_assignment(order_id=order_id)
    assert assignment["assigned_units"] == 3, (
        "the assignment covers the A x 2 line plus the B x 1 line the stale caller "
        f"had not seen, got assigned_units {assignment['assigned_units']}"
    )
    lines = find_assignment_lines(assignment["id"])
    assert len(lines) == 2, (
        f"one assignment line per demand line served, got {len(lines)}"
    )
    assert assignment["provisional_cost_cents"] == 1822, (
        "provisional cost is 882 labour (21 standard minutes at 42 cents) plus 175 "
        "packaging plus 765 freight, got "
        f"{assignment['provisional_cost_cents']}"
    )

    assert read_order(order_id)["version"] == 4, (
        "a successful run increments the order's version, so it should be 4"
    )


def test_replaying_a_committed_run_payload_is_stale_and_supersedes_nothing(api):
    """PRD §2.8: "`POST /fulfillment-network/orders/{order_id}/routing-runs` requires `expected_order_version`, carrying the client's last observed `version` of the target `CustomerOrder`."
    PRD §2.8: "If it does not match the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §3.4: "A `COMMIT` run begins with a supersede step, before any evaluation: every assignment of this order still sitting at `ASSIGNED` is cancelled with cancellation reason `SUPERSEDED`, stamped with `superseded_by_routing_run_id` naming this run, and has its units released back to the demand lines and its reservations released at its node."

    A successful COMMIT bumps the very version it was guarded on, so an immediate
    replay of the identical payload is stale in its turn — which is exactly what
    keeps it from tearing down the assignment the first run created.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_order_version_blocks_a_commit_run_that_would_supersede_unseen_lines
    """
    ctx = _order_whose_version_moved_after_the_planner_read()
    order_id = ctx["order"]["id"]

    fresh = order_version(order_id)
    commit_routing(order_id, expected_order_version=fresh)
    assert order_version(order_id) == 4, (
        "the accepted COMMIT should have moved the order from version 3 to 4"
    )

    replay = api.create_routing_run(
        order_id, create_routing_run_payload(fresh, "COMMIT"), PLANNER
    )
    validate_error(replay, "ERR_STALE_ORDER_VERSION")

    runs = find_routing_runs(order_id=order_id)
    assert len(runs) == 1, (
        f"only the accepted run should be persisted, got {len(runs)} runs"
    )
    assignments = find_assignments(order_id=order_id)
    assert len(assignments) == 1, (
        f"the refused replay must not create a second assignment, got {len(assignments)}"
    )
    assert assignments[0]["status"] == "ASSIGNED", (
        "the refused replay must not run the supersede step, so the assignment is "
        f"still ASSIGNED, got {assignments[0]['status']}"
    )
    assert assignments[0]["superseded_by_routing_run_id"] is None, (
        "no superseding run stamp may be written by a request refused at the guard"
    )
    assert assignments[0]["cancel_reason_code"] is None, (
        "the assignment must not carry a SUPERSEDED cancellation reason"
    )
    assert read_order(order_id)["version"] == 4, (
        "the refused replay must not mutate the order again"
    )


# ======================================================================
# expected_pickup_version on a parcel tender
# ======================================================================


def test_first_tender_claims_a_parcel_slot_and_bumps_the_pickup_version(api):
    """PRD §2.8: "Each successful tender consumes one of the window's parcel slots and increments the pickup's `version`, so a stale-version tender would be claiming a slot count the client never observed."
    PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    The tender that arrives first holds a live version, so it is accepted and it
    is what makes the other associate's captured version stale.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_pickup_version_blocks_the_second_parcel_tender
    """
    ctx = _two_packed_parcels_contending_for_one_pickup_window()
    stale = ctx["stale_pickup_version"]
    assert stale == 1, (
        f"a newly scheduled pickup starts at version 1, got {stale}"
    )

    shipped = validate_success(
        api.ship_assignment(
            ctx["first"]["id"],
            ship_payload(ctx["pickup"]["id"], stale),
            make_store_associate_headers(ctx["store"]["id"]),
        ),
        200,
    )
    assert shipped["status"] == "SHIPPED", (
        f"the first tender should move the assignment to SHIPPED, got {shipped['status']}"
    )

    pickup = read_pickup(ctx["pickup"]["id"])
    assert pickup["reserved_parcels"] == 1, (
        f"the tender consumes one parcel slot, got reserved_parcels {pickup['reserved_parcels']}"
    )
    assert pickup["version"] == 2, (
        f"the tender increments the pickup's version to 2, got {pickup['version']}"
    )
    assert_version_incremented(pickup["version"], stale)


def test_second_tender_replaying_the_pre_ship_pickup_version_is_refused_as_stale(api):
    """PRD §2.8: "`POST /fulfillment-network/assignments/{assignment_id}/ship` requires `expected_pickup_version`, carrying the client's last observed `version` of the `CarrierPickup` named by `carrier_pickup_id`."
    PRD §2.8: "If it does not match that pickup's current `version`, the tender is rejected with `ERR_STALE_PICKUP_VERSION` (HTTP 412)."
    PRD §2.8: "In each case the guard field is a required, non-optional part of the request body, it must carry the client's last observed `version` of the named parent, and a value that does not equal that parent's current `version` is rejected before any state changes."

    Both parcels were packed before either shipped, so the second associate
    replays the version read before the first tender. The window still has four
    free slots and the clock still sits inside it, so nothing but slot-count
    staleness can explain the refusal.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_pickup_version_blocks_the_second_parcel_tender
    """
    ctx = _two_packed_parcels_contending_for_one_pickup_window()
    stale = ctx["stale_pickup_version"]

    ship(
        ctx["first"]["id"],
        ctx["store"]["id"],
        ctx["pickup"]["id"],
        expected_pickup_version=stale,
    )

    response = api.ship_assignment(
        ctx["second"]["id"],
        ship_payload(ctx["pickup"]["id"], stale),
        make_store_associate_headers(ctx["store"]["id"]),
    )
    validate_error(response, "ERR_STALE_PICKUP_VERSION")

    pickup = read_pickup(ctx["pickup"]["id"])
    assert pickup["parcel_capacity"] == 5, "the window was scheduled with capacity 5"
    assert pickup["reserved_parcels"] == 1, (
        "only one slot is claimed, so capacity exhaustion cannot explain the refusal, "
        f"got reserved_parcels {pickup['reserved_parcels']}"
    )
    assert pickup["version"] == 2, (
        f"the refused tender must not move the pickup's version off 2, got {pickup['version']}"
    )

    second = read_assignment(ctx["second"]["id"])
    assert second["status"] == "PACKED", (
        f"the refused tender is inert: the assignment stays PACKED, got {second['status']}"
    )
    assert second["carrier_pickup_id"] is None, (
        "no pickup may be stamped onto an assignment whose tender was refused"
    )


def test_second_tender_succeeds_on_the_pickup_version_the_first_tender_left(api):
    """PRD §2.8: "If it does not match that pickup's current `version`, the tender is rejected with `ERR_STALE_PICKUP_VERSION` (HTTP 412)."
    PRD §2.9: "A pickup's `reserved_parcels` equals the count of assignments whose `carrier_pickup_id` names that pickup and whose `status` is `SHIPPED`, and `reserved_parcels` never exceeds `parcel_capacity`."
    PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
    PRD §3.8: "The **final** variant, written to `final_cost_cents` at ship, charges *actual* clocked labour: the greater of `labor_minutes_actual` and a 10-minute billable minimum, where `labor_minutes_actual` is the whole minutes from `accepted_at` to `packed_at` with remaining seconds discarded."

    Re-reading the pickup after the refusal is all it takes: the same tender is
    then accepted, the second slot is claimed, and the parcel count agrees with
    the number of SHIPPED assignments pointing at the window.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_pickup_version_blocks_the_second_parcel_tender
    """
    ctx = _two_packed_parcels_contending_for_one_pickup_window()
    pickup_id = ctx["pickup"]["id"]

    ship(
        ctx["first"]["id"],
        ctx["store"]["id"],
        pickup_id,
        expected_pickup_version=ctx["stale_pickup_version"],
    )
    refused = api.ship_assignment(
        ctx["second"]["id"],
        ship_payload(pickup_id, ctx["stale_pickup_version"]),
        make_store_associate_headers(ctx["store"]["id"]),
    )
    validate_error(refused, "ERR_STALE_PICKUP_VERSION")

    fresh = pickup_version(pickup_id)
    assert fresh == 2, f"the live pickup version after one tender should be 2, got {fresh}"

    retried = validate_success(
        api.ship_assignment(
            ctx["second"]["id"],
            ship_payload(pickup_id, fresh),
            make_store_associate_headers(ctx["store"]["id"]),
        ),
        200,
    )
    assert retried["status"] == "SHIPPED", (
        f"the retry with the fresh version should ship, got {retried['status']}"
    )

    pickup = read_pickup(pickup_id)
    assert pickup["reserved_parcels"] == 2, (
        f"both parcels are now tendered, got reserved_parcels {pickup['reserved_parcels']}"
    )
    assert pickup["version"] == 3, (
        f"each accepted tender increments the pickup by exactly 1, got {pickup['version']}"
    )

    shipped_here = find_assignments(carrier_pickup_id=pickup_id, status="SHIPPED")
    assert pickup["reserved_parcels"] == len(shipped_here), (
        f"reserved_parcels {pickup['reserved_parcels']} must equal the "
        f"{len(shipped_here)} SHIPPED assignments naming this pickup"
    )

    for assignment_id in (ctx["first"]["id"], ctx["second"]["id"]):
        final = read_assignment(assignment_id)["final_cost_cents"]
        assert final == 1000, (
            "each parcel seals 420 labour (the 10-minute billable minimum at 42 "
            "cents) plus 160 packaging plus 420 freight, got "
            f"{final}"
        )


# ======================================================================
# expected_inventory_version on a counted adjustment
# ======================================================================


def test_first_counted_adjustment_writes_the_shrink_and_bumps_the_row(api):
    """PRD §3.1: "On success `on_hand_units` is overwritten with `counted_on_hand_units`, `last_adjustment_reason` records the supplied `reason`, `available_to_promise_units` is recomputed, the node's `eligibility_score` is recomputed, and the row's `version` increments."
    PRD §3.1: "`available_to_promise_units` is recomputed from the formula above whenever `reserved_units` moves, whenever the row is adjusted, and at row creation."
    PRD §2.8: "An adjustment overwrites `on_hand_units` outright with a counted figure, so an adjustment computed from a stale on-hand reading would silently erase an intervening receipt or an intervening ship decrement."

    The first of the two counters holds a live version, so its 3-unit shrink is
    written and the row moves to version 2 — which is what the other counter's
    captured version is now behind.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_inventory_version_blocks_a_second_cycle_count
    """
    ctx = _inventory_row_read_once_by_two_counters()
    inventory_id = ctx["inventory"]["id"]
    stale = ctx["stale_inventory_version"]
    assert stale == 1, f"a freshly stocked row starts at version 1, got {stale}"

    adjusted = validate_success(
        api.adjust_store_inventory(
            inventory_id,
            inventory_adjustment_payload(stale, 9, "SHRINK"),
            PLANNER,
        ),
        200,
    )
    assert adjusted["on_hand_units"] == 9, (
        f"the counted figure overwrites on-hand outright, got {adjusted['on_hand_units']}"
    )
    assert adjusted["available_to_promise_units"] == 7, (
        "available_to_promise_units is 9 on hand less 0 reserved less 2 safety, got "
        f"{adjusted['available_to_promise_units']}"
    )
    assert adjusted["last_adjustment_reason"] == "SHRINK", (
        f"the supplied reason is recorded, got {adjusted['last_adjustment_reason']}"
    )
    assert adjusted["version"] == 2, (
        f"the accepted adjustment increments the row to version 2, got {adjusted['version']}"
    )
    assert_version_incremented(adjusted["version"], stale)


def test_second_adjustment_replaying_the_pre_shrink_version_is_refused_as_stale(api):
    """PRD §2.8: "`POST /fulfillment-network/store-inventories/{inventory_id}/adjustments` requires `expected_inventory_version`, carrying the client's last observed `version` of the `StoreInventory` row."
    PRD §2.8: "If it does not match the row's current `version`, the adjustment is rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412)."
    PRD §2.8: "An adjustment overwrites `on_hand_units` outright with a counted figure, so an adjustment computed from a stale on-hand reading would silently erase an intervening receipt or an intervening ship decrement."

    The second counter posts a count of 12 against the version it read before the
    shrink. The acting associate is the row's own node, so the refusal is a
    genuine staleness verdict, and the 3-unit shrink survives untouched.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_inventory_version_blocks_a_second_cycle_count
    """
    ctx = _inventory_row_read_once_by_two_counters()
    inventory_id = ctx["inventory"]["id"]
    stale = ctx["stale_inventory_version"]

    adjust_inventory(inventory_id, 9, "SHRINK", expected_inventory_version=stale)

    response = api.adjust_store_inventory(
        inventory_id,
        inventory_adjustment_payload(stale, 12, "CYCLE_COUNT"),
        make_store_associate_headers(ctx["store"]["id"]),
    )
    validate_error(response, "ERR_STALE_INVENTORY_VERSION")

    row = read_inventory(inventory_id)
    assert row["on_hand_units"] == 9, (
        f"the refused count of 12 must not erase the shrink, got on_hand_units {row['on_hand_units']}"
    )
    assert row["available_to_promise_units"] == 7, (
        f"available_to_promise_units stays at 7, got {row['available_to_promise_units']}"
    )
    assert row["last_adjustment_reason"] == "SHRINK", (
        "the refused CYCLE_COUNT must not overwrite the recorded reason, got "
        f"{row['last_adjustment_reason']}"
    )
    assert row["version"] == 2, (
        f"a refused adjustment never increments the row, got version {row['version']}"
    )


def test_retried_cycle_count_with_the_fresh_inventory_version_is_accepted(api):
    """PRD §2.8: "If it does not match the row's current `version`, the adjustment is rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412)."
    PRD §3.1: "On success `on_hand_units` is overwritten with `counted_on_hand_units`, `last_adjustment_reason` records the supplied `reason`, `available_to_promise_units` is recomputed, the node's `eligibility_score` is recomputed, and the row's `version` increments."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Re-reading the row is what makes the second count legitimate: the same payload
    with the fresh guard is accepted, and the row has moved 1 to 2 to 3 across
    three adjustment calls of which one was refused.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_inventory_version_blocks_a_second_cycle_count
    """
    ctx = _inventory_row_read_once_by_two_counters()
    inventory_id = ctx["inventory"]["id"]
    stale = ctx["stale_inventory_version"]
    associate = make_store_associate_headers(ctx["store"]["id"])

    adjust_inventory(inventory_id, 9, "SHRINK", expected_inventory_version=stale)
    refused = api.adjust_store_inventory(
        inventory_id,
        inventory_adjustment_payload(stale, 12, "CYCLE_COUNT"),
        associate,
    )
    validate_error(refused, "ERR_STALE_INVENTORY_VERSION")

    fresh = inventory_version(inventory_id)
    assert fresh == 2, f"the live row version after one accepted write is 2, got {fresh}"

    retried = validate_success(
        api.adjust_store_inventory(
            inventory_id,
            inventory_adjustment_payload(fresh, 12, "CYCLE_COUNT"),
            associate,
        ),
        200,
    )
    assert retried["on_hand_units"] == 12, (
        f"the counted figure of 12 is now written, got {retried['on_hand_units']}"
    )
    assert retried["available_to_promise_units"] == 10, (
        "available_to_promise_units is 12 on hand less 0 reserved less 2 safety, got "
        f"{retried['available_to_promise_units']}"
    )
    assert retried["last_adjustment_reason"] == "CYCLE_COUNT", (
        f"the retried reason is recorded, got {retried['last_adjustment_reason']}"
    )
    assert retried["version"] == 3, (
        "version increments by exactly 1 on every accepted write and never on a "
        f"refused one, so the row should be at 3, got {retried['version']}"
    )


# ======================================================================
# Immediate visibility of a COMMIT run's side effects
# ======================================================================


def test_commit_run_projections_are_final_in_the_response_and_on_the_next_read(api):
    """PRD §2.10: "Cascades in this system are immediate and multi-hop."
    PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
    PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
    PRD §3.4: "Within each iteration every node in the network is evaluated in ascending node `created_at` order, and every evaluation is persisted as a candidate row carrying `routing_run_id`, `store_id` and the 1-based `iteration` in which it happened."
    PRD §3.4: "Candidates that failed the eligibility filter carry a null `routing_score` and a null `rank`; they are still persisted so the planner can see why they lost."
    PRD §3.4: "`projected_cost_index_bps` is `projected_cost_cents` multiplied by 10000, divided by `projected_dc_cost_cents`, rounded half-up — and 0 when the baseline is 0."

    The COMMIT response already carries its final projections, the immediately
    following read of the same run agrees field for field, and the candidate rows
    the same call persisted are already listable — there is no intermediate or
    settling status anywhere in the run's lifecycle.

    Design: Corner/consistency_model/every_side_effect_of_a_commit_run_is_visible_to_the_very_next_read
    """
    ctx = _network_where_only_the_first_node_stocks_the_ordered_sku()
    order_id = ctx["order"]["id"]

    created = validate_success(
        api.create_routing_run(
            order_id,
            create_routing_run_payload(order_version(order_id), "COMMIT"),
            PLANNER,
        ),
        201,
    )
    assert created["status"] == "COMMITTED", (
        f"the run settles at COMMITTED in its own response, got {created['status']}"
    )
    assert created["selected_store_count"] == 1, (
        f"one node was selected, got {created['selected_store_count']}"
    )
    assert created["planned_split_count"] == 1, (
        f"planned_split_count equals the nodes selected, got {created['planned_split_count']}"
    )
    assert created["unfulfillable_units"] == 0, (
        f"all demand was covered, got unfulfillable_units {created['unfulfillable_units']}"
    )
    assert created["projected_cost_cents"] == 1416, (
        f"1336 component plus an 80-cent 6.0% network fee, got {created['projected_cost_cents']}"
    )
    assert created["projected_cost_index_bps"] == 6775, (
        f"1416 * 10000 / 2090 rounded half-up, got {created['projected_cost_index_bps']}"
    )

    reread = read_routing_run(created["id"])
    for field in (
        "status",
        "selected_store_count",
        "planned_split_count",
        "unfulfillable_units",
        "projected_cost_cents",
        "projected_cost_index_bps",
    ):
        assert reread[field] == created[field], (
            f"the next read of the run must already show the committed {field}: "
            f"{reread[field]} != {created[field]}"
        )

    candidates = find_routing_candidates(routing_run_id=created["id"])
    assert [row["store_id"] for row in candidates] == [
        ctx["s1"]["id"],
        ctx["s3"]["id"],
    ], "both evaluations are persisted by the same call, in ascending node created_at order"

    s1_candidate, s3_candidate = candidates
    assert s1_candidate["eligible"] is True, "S1 stocks the SKU and is eligible"
    assert s1_candidate["selected"] is True, "S1 is the winner of iteration 1"
    assert s1_candidate["routing_score"] == pytest.approx(82.58, abs=0.01), (
        "45 * 1.0000 coverage + 25 * 0.4150 cost + 20 * 1.0000 speed + 10 * 0.7200 "
        f"health, got {s1_candidate['routing_score']}"
    )
    assert s3_candidate["eligible"] is False, "S3 stocks no row for the SKU"
    assert s3_candidate["ineligible_reason"] == "NO_ATP", (
        f"S3 has no promise-able units, got {s3_candidate['ineligible_reason']}"
    )
    assert s3_candidate["routing_score"] is None, (
        "an ineligible candidate carries a null routing_score"
    )
    assert s3_candidate["rank"] is None, "an ineligible candidate carries a null rank"


def test_assignment_and_order_are_settled_on_the_first_read_after_the_commit(api):
    """PRD §2.10: "Cascades in this system are immediate and multi-hop."
    PRD §3.2: "After every routing run and after every change to any of the order's assignment statuses, it is re-derived from persisted rows."
    PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
    PRD §3.2: "A demand line's `open_units` is always its `quantity` less `assigned_units`, less `shipped_units`, less `cancelled_units`, less `dc_fallback_units`."
    PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."
    PRD §3.5: "And `pick_deadline_utc` is the earlier of two instants: four hours after the assignment's `created_at`, and the instant on the creation date's UTC calendar day that falls `cutoff_utc_minutes` minutes after midnight UTC."
    PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."

    One COMMIT call creates the assignment, its assignment line, the order's
    re-derived routing posture and the demand line's counters, and every one of
    them is already at its final value on the very next read.

    Design: Corner/consistency_model/every_side_effect_of_a_commit_run_is_visible_to_the_very_next_read
    """
    ctx = _network_where_only_the_first_node_stocks_the_ordered_sku()
    order_id = ctx["order"]["id"]

    run = commit_routing(order_id)

    assignment = find_assignment(routing_run_id=run["id"])
    assert assignment["status"] == "ASSIGNED", (
        f"the assignment is born ASSIGNED, got {assignment['status']}"
    )
    assert assignment["version"] == 1, (
        f"a freshly created assignment sits at version 1, got {assignment['version']}"
    )
    assert assignment["store_id"] == ctx["s1"]["id"], (
        "the only node stocking the SKU won the iteration"
    )
    assert assignment["assigned_units"] == 2, (
        f"both ordered units were allocated, got {assignment['assigned_units']}"
    )
    assert assignment["epoch"] == 1, (
        f"the assignment is stamped with its node's open window epoch, got {assignment['epoch']}"
    )
    assert assignment["provisional_cost_cents"] == 1336, (
        "756 labour (18 standard minutes at 42 cents) plus 160 packaging plus 420 "
        f"freight, got {assignment['provisional_cost_cents']}"
    )
    assert assignment["labor_minutes_reserved"] == pytest.approx(18.00, abs=0.01), (
        "12 minutes per order plus 3 per unit on 2 units, got "
        f"{assignment['labor_minutes_reserved']}"
    )
    assert assignment["pick_deadline_utc"].startswith("2026-08-03T13:00:00"), (
        "four hours after the 09:00Z creation is earlier than the 17:00Z cutoff, got "
        f"{assignment['pick_deadline_utc']}"
    )

    lines = find_assignment_lines(assignment["id"])
    assert len(lines) == 1, f"one assignment line per demand line served, got {len(lines)}"
    assert lines[0]["units_assigned"] == 2, (
        f"the line carries both units, got {lines[0]['units_assigned']}"
    )

    order = read_order(order_id)
    assert order["routing_status"] == "ROUTED", (
        "covered units plus cancelled units equals total_units, got "
        f"{order['routing_status']}"
    )
    assert order["fulfillment_status"] == "PENDING", (
        f"nothing has shipped yet, got {order['fulfillment_status']}"
    )
    assert order["provisional_cost_cents"] == 1416, (
        f"the order-level provisional cost is settled immediately, got {order['provisional_cost_cents']}"
    )
    assert order["cost_index_bps"] == 6775, (
        f"1416 * 10000 / 2090 rounded half-up, got {order['cost_index_bps']}"
    )
    assert order["version"] == 3, (
        f"intake, one line append and this run make version 3, got {order['version']}"
    )

    line = read_order_line(ctx["line"]["id"])
    assert line["open_units"] == 0, (
        f"no demand unit is left open, got {line['open_units']}"
    )
    assert line["assigned_units"] == 2, (
        f"both units are held by the live assignment, got {line['assigned_units']}"
    )


def test_node_and_inventory_counters_are_settled_on_the_first_read_after_the_commit(api):
    """PRD §2.9: "They are invariants, not endpoints: they hold after every routing-run commit, accept, reject, cancel, short pick, ship, inventory adjustment and operations run."
    PRD §3.4: "On a `COMMIT` run each winner also produces a `FulfillmentAssignment` and its `AssignmentLine` rows, as described in §3.5, which raises that node's inventory `reserved_units`, `units_committed_epoch` and `reserved_labor_minutes` and recomputes its `eligibility_score`."
    PRD §3.1: "`available_to_promise_units` is recomputed from the formula above whenever `reserved_units` moves, whenever the row is adjusted, and at row creation."
    PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
    PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

    The reservation and the node's rescore are hops of the same synchronous
    chain: no reconciliation pass stands between the COMMIT call and the reserved
    inventory, the committed unit counter, the reserved labour or the new score.

    Design: Corner/consistency_model/every_side_effect_of_a_commit_run_is_visible_to_the_very_next_read
    """
    ctx = _network_where_only_the_first_node_stocks_the_ordered_sku()

    commit_routing(ctx["order"]["id"])

    inventory = read_inventory(ctx["inventory"]["id"])
    assert inventory["reserved_units"] == 2, (
        f"the allocation reserved both units, got {inventory['reserved_units']}"
    )
    assert inventory["available_to_promise_units"] == 8, (
        "12 on hand less 2 reserved less 2 safety, got "
        f"{inventory['available_to_promise_units']}"
    )
    assert inventory["version"] == 2, (
        f"the reservation mutated the row exactly once, got version {inventory['version']}"
    )

    store = read_store(ctx["s1"]["id"])
    assert store["units_committed_epoch"] == 2, (
        f"the epoch's committed units include the new allocation, got {store['units_committed_epoch']}"
    )
    assert store["reserved_labor_minutes"] == pytest.approx(18.00, abs=0.01), (
        f"the assignment's labour standard is held at the node, got {store['reserved_labor_minutes']}"
    )
    assert store["eligibility_score"] == pytest.approx(70.48, abs=0.01), (
        "23.6000 capacity at 118/200 plus 28.8750 labour at 462/480 plus 18.0000 "
        f"cold-start performance, got {store['eligibility_score']}"
    )
    assert store["eligibility_score_basis"] == "COLD_START", (
        "the node still has no closed window, got "
        f"{store['eligibility_score_basis']}"
    )
