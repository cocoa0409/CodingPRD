"""Crate registration, the crate location lifecycle and the advance warehouse's
committed hundredweight."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    BASE_CLOCK,
    advance_show,
    assert_crate,
    assert_timestamp_format,
    assert_warehouse,
    check_in_crate,
    create_crate_payload,
    create_exhibitor,
    create_warehouse,
    get_crate,
    get_shipment,
    get_warehouse,
    make_exhibitor_headers,
    make_warehouse_agent_headers,
    move_crate,
    receive_shipment,
    register_crate,
    set_clock,
    setup_show_ground,
    setup_warehouse_with_crate,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["show_operations_headers"]


# ---------------------------------------------------------------------------
# Local scenario builders, composed only from test_helpers primitives.
# ---------------------------------------------------------------------------

def _tiny_warehouse_and_registered_crate(capacity_cwt=10, weight_lbs=1250):
    """A warehouse whose capacity_cwt is 10 and one REGISTERED crate of 1250 lb,
    which rounds up to 13 hundredweight and therefore cannot fit."""
    set_clock(BASE_CLOCK)
    warehouse = create_warehouse(name="Tiny Annex", capacity_cwt=capacity_cwt)
    exhibitor = create_exhibitor()
    crate = register_crate(exhibitor["id"], weight_lbs=weight_lbs)
    return {"warehouse": warehouse, "exhibitor": exhibitor, "crate": crate}


def _advance_freight_ready_to_check_in(weight_lbs=1250):
    """Show ground plus a warehouse, and one crate listed on a RECEIVED
    ADVANCE_WAREHOUSE shipment for a show that has reached ADVANCE_CLOSED."""
    ground = setup_show_ground(show_status="OPEN_FOR_ORDERS", with_warehouse=True)
    crate = register_crate(ground["exhibitor"]["id"], weight_lbs=weight_lbs)
    ground["crate"] = crate
    ground["shipment"] = receive_shipment(
        ground["show"]["id"], ground["exhibitor"]["id"], [crate["id"]],
        warehouse_id=ground["warehouse"]["id"])
    advance_show(ground["show"]["id"], "ADVANCE_CLOSED")
    return ground


def _receive_direct_to_show(ground, weight_lbs=1250, crate_label="ACME-C1"):
    """Register one crate and tender it on a DIRECT_TO_SHOW receipt, which never
    touches a warehouse."""
    crate = register_crate(ground["exhibitor"]["id"], weight_lbs=weight_lbs,
                           crate_label=crate_label)
    shipment = receive_shipment(
        ground["show"]["id"], ground["exhibitor"]["id"], [crate["id"]],
        warehouse_id=ground["warehouse"]["id"], channel="DIRECT_TO_SHOW")
    return crate, shipment


def _walk_show_from_open_for_orders_to_on_site(show_id):
    for to_status in ("ADVANCE_CLOSED", "MOVE_IN", "ON_SITE"):
        advance_show(show_id, to_status)


# ---------------------------------------------------------------------------
# Check-in is gated by the warehouse's remaining capacity.
# ---------------------------------------------------------------------------

def test_check_in_over_warehouse_capacity_is_refused(api):
    """PRD §3.6: "Both edges require the warehouse's `status` to be `ACCEPTING`
    and require that the warehouse's current `committed_cwt` plus this crate's
    own hundredweight — its `weight_lbs` divided by one hundred and rounded up to
    a whole number — be no greater than the warehouse's `capacity_cwt`; a closed
    warehouse or an overflow is refused with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`."
    PRD §2.9: "Warehouse capacity and receiving status — otherwise
    `ERR_WAREHOUSE_CAPACITY_EXCEEDED` (409). Applies to
    `POST /crates/{id}/warehouse-check-in`."

    Design: Difficulty/cross_entity_state_dependency/crate_checkin_gated_by_warehouse_capacity
    """
    scenario = _tiny_warehouse_and_registered_crate()
    warehouse = scenario["warehouse"]

    response = api.warehouse_check_in(
        scenario["crate"]["id"],
        {"warehouse_id": warehouse["id"],
         "expected_warehouse_version": warehouse["version"]},
        make_warehouse_agent_headers(warehouse["id"]))

    validate_error(response, ApiErrorId.ERR_WAREHOUSE_CAPACITY_EXCEEDED.value, 409)


def test_refused_check_in_leaves_crate_registered_and_committed_cwt_at_zero(api):
    """PRD §3.6: "Both edges require the warehouse's `status` to be `ACCEPTING`
    and require that the warehouse's current `committed_cwt` plus this crate's
    own hundredweight — its `weight_lbs` divided by one hundred and rounded up to
    a whole number — be no greater than the warehouse's `capacity_cwt`; a closed
    warehouse or an overflow is refused with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`."
    PRD §3.6: "`Warehouse.committed_cwt` is a full recomputation, never a delta:
    it is the sum, over every crate whose `warehouse_id` is this warehouse and
    whose `status` is `AT_ADVANCE_WAREHOUSE` or `RETURNED_TO_WAREHOUSE`, of that
    crate's `weight_lbs` divided by one hundred and rounded up to a whole
    hundredweight."
    PRD §3.6: "Crates are born `REGISTERED` with `warehouse_id` null,
    `shipment_id` null, `stored_since` null and `storage_charge_cents` at 0, and
    may be listed and filtered by `exhibitor_id`, `asset_id`, `warehouse_id`,
    `shipment_id` and `status`."

    Design: Difficulty/cross_entity_state_dependency/crate_checkin_gated_by_warehouse_capacity
    """
    scenario = _tiny_warehouse_and_registered_crate()
    warehouse = scenario["warehouse"]

    api.warehouse_check_in(
        scenario["crate"]["id"],
        {"warehouse_id": warehouse["id"],
         "expected_warehouse_version": warehouse["version"]},
        make_warehouse_agent_headers(warehouse["id"]))

    crate_after = get_crate(scenario["crate"]["id"])
    warehouse_after = get_warehouse(warehouse["id"])
    assert_crate(crate_after)
    assert_warehouse(warehouse_after)
    assert crate_after["status"] == "REGISTERED", (
        "A 13 cwt crate refused by a 10 cwt warehouse stays REGISTERED, got "
        f"{crate_after['status']}")
    assert crate_after["warehouse_id"] is None, (
        "The refused crate never acquires a warehouse_id, got "
        f"{crate_after['warehouse_id']}")
    assert crate_after["stored_since"] is None, (
        "The refused crate never has its storage clock stamped, got "
        f"{crate_after['stored_since']}")
    assert warehouse_after["committed_cwt"] == 0, (
        "No crate is held, so committed_cwt stays 0, got "
        f"{warehouse_after['committed_cwt']}")


# ---------------------------------------------------------------------------
# Check-in then departure is a perfect round trip on committed_cwt.
# ---------------------------------------------------------------------------

def test_check_in_then_departure_round_trips_committed_cwt_to_zero(api):
    """PRD §2.11: "None of them is maintained as an incremental delta, because a
    forward action and its compensating reversal must land the aggregate back on
    exactly the figure it held before — issuing and then voiding an invoice is a
    perfect round trip, and checking a crate in and then moving it out returns a
    warehouse's committed weight to its prior value."
    PRD §3.6: "`Warehouse.committed_cwt` is a full recomputation, never a delta:
    it is the sum, over every crate whose `warehouse_id` is this warehouse and
    whose `status` is `AT_ADVANCE_WAREHOUSE` or `RETURNED_TO_WAREHOUSE`, of that
    crate's `weight_lbs` divided by one hundred and rounded up to a whole
    hundredweight."
    PRD §3.6: "Rounding up happens per crate and the whole numbers are then
    added; summing raw pounds across crates and rounding once at the end is not
    the rule."

    Design: Difficulty/compensating_invariant/crate_checkin_then_ship_conserves_warehouse_committed_cwt
    """
    ground = _advance_freight_ready_to_check_in()
    warehouse_id = ground["warehouse"]["id"]
    crate_id = ground["crate"]["id"]

    committed_before = get_warehouse(warehouse_id)["committed_cwt"]
    check_in_crate(crate_id, warehouse_id)
    committed_at_peak = get_warehouse(warehouse_id)["committed_cwt"]
    move_crate(crate_id, "IN_TRANSIT_TO_SHOW")
    warehouse_after = get_warehouse(warehouse_id)

    assert_warehouse(warehouse_after)
    assert committed_before == 0, (
        f"An empty warehouse starts at committed_cwt 0, got {committed_before}")
    assert committed_at_peak == 13, (
        "A 1250 lb crate rounds up to 13 hundredweight while it is held, got "
        f"{committed_at_peak}")
    assert warehouse_after["committed_cwt"] == 0, (
        "Departure returns committed_cwt to exactly the figure it held before "
        f"the check-in, got {warehouse_after['committed_cwt']}")


def test_departure_clears_storage_fields_and_moves_shipment_to_in_transit(api):
    """PRD §3.6: "On success the crate's `warehouse_id` is set, its
    `stored_since` is stamped with the logical clock's current instant, the
    warehouse's `committed_cwt` is recomputed upward and the warehouse's
    `version` increases by one."
    PRD §3.6: "From `AT_ADVANCE_WAREHOUSE` a crate moves to `IN_TRANSIT_TO_SHOW`
    provided its `shipment_id` is non-null and that shipment's show is in
    `ADVANCE_CLOSED`, `MOVE_IN` or `ON_SITE`; departure clears `warehouse_id` and
    `stored_since` back to null, recomputes the warehouse's `committed_cwt`
    downward, and moves the shipment from `RECEIVED` to `IN_TRANSIT` if it was
    still `RECEIVED`."
    PRD §3.6: "The base rate is 9800 cents per hundredweight when `channel` is
    `ADVANCE_WAREHOUSE` and 11500 cents per hundredweight when it is
    `DIRECT_TO_SHOW`."

    Design: Difficulty/compensating_invariant/crate_checkin_then_ship_conserves_warehouse_committed_cwt
    """
    ground = _advance_freight_ready_to_check_in()
    warehouse_id = ground["warehouse"]["id"]
    crate_id = ground["crate"]["id"]
    shipment_id = ground["shipment"]["id"]

    crate_held = check_in_crate(crate_id, warehouse_id)
    assert crate_held["status"] == "AT_ADVANCE_WAREHOUSE", (
        f"A REGISTERED crate checks in to AT_ADVANCE_WAREHOUSE, got {crate_held['status']}")
    assert crate_held["warehouse_id"] == warehouse_id, (
        "Check-in sets the crate's warehouse_id to the receiving warehouse")
    assert crate_held["stored_since"] is not None, (
        "Check-in stamps stored_since with the logical clock's current instant")

    move_crate(crate_id, "IN_TRANSIT_TO_SHOW")
    crate_after = get_crate(crate_id)
    shipment_after = get_shipment(shipment_id)

    assert_crate(crate_after)
    assert crate_after["status"] == "IN_TRANSIT_TO_SHOW", (
        f"The crate leaves the warehouse for the floor, got {crate_after['status']}")
    assert crate_after["warehouse_id"] is None, (
        f"Departure clears warehouse_id, got {crate_after['warehouse_id']}")
    assert crate_after["stored_since"] is None, (
        f"Departure clears stored_since, got {crate_after['stored_since']}")
    assert shipment_after["status"] == "IN_TRANSIT", (
        "The first crate leaving the warehouse moves the shipment RECEIVED -> "
        f"IN_TRANSIT, got {shipment_after['status']}")
    assert shipment_after["drayage_charge_cents"] == 127400, (
        "13 billable cwt at the 9800 cent advance rate with no surcharge is "
        f"127400 cents, got {shipment_after['drayage_charge_cents']}")


# ---------------------------------------------------------------------------
# Crate registration mints its own system fields.
# ---------------------------------------------------------------------------

def test_new_crate_is_born_registered_with_server_minted_system_fields(api):
    """PRD §3.6: "Crates are born `REGISTERED` with `warehouse_id` null,
    `shipment_id` null, `stored_since` null and `storage_charge_cents` at 0, and
    may be listed and filtered by `exhibitor_id`, `asset_id`, `warehouse_id`,
    `shipment_id` and `status`."
    PRD §2.5: "Every resource the API persists carries an `id`: a server-minted
    UUID, with no type prefix and no embedded semantics."
    PRD §2.5: "`version` — an integer that begins at 1 when the row is created
    and increases by exactly 1 on every mutation of that row, again including
    server-initiated cascades."
    PRD §2.5: "`created_at` — an ISO 8601 UTC timestamp with three fractional
    digits, stamped when the row is first written and never changed afterwards."

    Design: Corner/entities/crate_system_fields_generated_and_client_values_ignored
    """
    set_clock(BASE_CLOCK)
    exhibitor = create_exhibitor()

    crate = validate_success(
        api.create_crate(
            create_crate_payload(exhibitor["id"], crate_label="ACME-C1",
                                 crate_type="FIBER_CASE", weight_lbs=640),
            make_exhibitor_headers(exhibitor["id"])),
        201)

    assert_crate(crate)
    assert crate["status"] == "REGISTERED", (
        f"A crate is born REGISTERED, got {crate['status']}")
    assert crate["warehouse_id"] is None, (
        f"A newborn crate has no warehouse_id, got {crate['warehouse_id']}")
    assert crate["shipment_id"] is None, (
        f"A newborn crate has no shipment_id, got {crate['shipment_id']}")
    assert crate["stored_since"] is None, (
        f"A newborn crate has no storage clock, got {crate['stored_since']}")
    assert crate["storage_charge_cents"] == 0, (
        f"A newborn crate carries storage_charge_cents 0, got {crate['storage_charge_cents']}")
    assert crate["version"] == 1, (
        f"A freshly written row starts at version 1, got {crate['version']}")
    assert_timestamp_format(crate["created_at"])
    fractional_part = crate["created_at"].rstrip("Z").split(".")
    assert len(fractional_part) == 2 and len(fractional_part[1]) == 3, (
        "created_at is an ISO 8601 UTC timestamp with three fractional digits, got "
        f"{crate['created_at']}")


# ---------------------------------------------------------------------------
# RELEASED_TO_CARRIER is terminal.
# ---------------------------------------------------------------------------

def test_released_to_carrier_crate_rejects_further_movement(api):
    """PRD §3.6: "From `OUTBOUND_STAGED` it either goes back to the warehouse
    through a check-in, or moves to `RELEASED_TO_CARRIER`, which is terminal and
    accepts no further movement."
    PRD §2.9: "The target is not already in a terminal state of its machine —
    otherwise `ERR_ENTITY_TERMINAL` (409). Applies to every state-transition
    endpoint."
    PRD §3.6: "`LOST` is the other terminal crate status and is reachable from
    every non-terminal one — that is, from anything other than
    `RELEASED_TO_CARRIER` and `LOST` itself."

    Design: Corner/state_machines/released_crate_is_terminal_and_rejects_further_movement
    """
    ground = setup_show_ground(show_status="OPEN_FOR_ORDERS", with_warehouse=True)
    crate, _shipment = _receive_direct_to_show(ground)
    _walk_show_from_open_for_orders_to_on_site(ground["show"]["id"])
    move_crate(crate["id"], "ON_SHOW_FLOOR")
    advance_show(ground["show"]["id"], "MOVE_OUT")
    move_crate(crate["id"], "OUTBOUND_STAGED")
    released = move_crate(crate["id"], "RELEASED_TO_CARRIER")
    assert released["status"] == "RELEASED_TO_CARRIER", (
        f"The crate is handed to the outbound carrier, got {released['status']}")

    response = api.move_crate(crate["id"], {"to_status": "LOST"}, OPS)

    validate_error(response, ApiErrorId.ERR_ENTITY_TERMINAL.value, 409)
    crate_after = get_crate(crate["id"])
    assert crate_after["status"] == "RELEASED_TO_CARRIER", (
        "A terminal crate keeps its status after the refused movement, got "
        f"{crate_after['status']}")


# ---------------------------------------------------------------------------
# The on-floor emptying cycle.
# ---------------------------------------------------------------------------

def test_crate_cycles_between_show_floor_and_empty_stored(api):
    """PRD §3.6: "During the show a crate cycles between `ON_SHOW_FLOOR` and
    `EMPTY_STORED`."
    PRD §3.6: "Emptying it requires the show to be in `MOVE_IN` or `ON_SITE` and
    deliberately does **not** set `stored_since`: accessible empty-crate storage
    during a show is not metered storage and is never billed by a storage run."
    PRD §3.6: "Bringing it back to `ON_SHOW_FLOOR` requires the show to be in
    `ON_SITE` or `MOVE_OUT` and re-evaluates the shipment bubble-up."
    PRD §3.6: "Crates in any other status contribute nothing at all — an
    `EMPTY_STORED` crate sits in accessible storage on the show floor, carries no
    `warehouse_id`, and is invisible to this aggregate."

    Design: Corner/state_machines/crate_empty_stored_returns_to_show_floor_cycle
    """
    ground = setup_show_ground(show_status="OPEN_FOR_ORDERS", with_warehouse=True)
    crate, _shipment = _receive_direct_to_show(ground)
    _walk_show_from_open_for_orders_to_on_site(ground["show"]["id"])
    move_crate(crate["id"], "ON_SHOW_FLOOR")

    emptied = move_crate(crate["id"], "EMPTY_STORED")
    back_on_floor = move_crate(crate["id"], "ON_SHOW_FLOOR")
    warehouse_after = get_warehouse(ground["warehouse"]["id"])

    assert_crate(emptied)
    assert emptied["status"] == "EMPTY_STORED", (
        f"Emptying the crate lands it on EMPTY_STORED, got {emptied['status']}")
    assert emptied["stored_since"] is None, (
        "Accessible empty-crate storage during a show never stamps stored_since, got "
        f"{emptied['stored_since']}")
    assert back_on_floor["status"] == "ON_SHOW_FLOOR", (
        f"The emptied crate returns to the booth, got {back_on_floor['status']}")
    assert back_on_floor["warehouse_id"] is None, (
        "Neither leg of the on-floor cycle touches a warehouse, got "
        f"{back_on_floor['warehouse_id']}")
    assert warehouse_after["committed_cwt"] == 0, (
        "Direct-to-show freight never contributes to committed_cwt, got "
        f"{warehouse_after['committed_cwt']}")


# ---------------------------------------------------------------------------
# committed_cwt filters on the two warehouse-bearing statuses.
# ---------------------------------------------------------------------------

def test_committed_cwt_counts_only_warehouse_bearing_statuses(api):
    """PRD §3.6: "`Warehouse.committed_cwt` is a full recomputation, never a
    delta: it is the sum, over every crate whose `warehouse_id` is this warehouse
    and whose `status` is `AT_ADVANCE_WAREHOUSE` or `RETURNED_TO_WAREHOUSE`, of
    that crate's `weight_lbs` divided by one hundred and rounded up to a whole
    hundredweight."
    PRD §3.6: "Crates in any other status contribute nothing at all — an
    `EMPTY_STORED` crate sits in accessible storage on the show floor, carries no
    `warehouse_id`, and is invisible to this aggregate."
    PRD §3.6: "Rounding up happens per crate and the whole numbers are then
    added; summing raw pounds across crates and rounding once at the end is not
    the rule."

    Design: Corner/calculations/committed_cwt_counts_only_warehouse_bearing_statuses
    """
    ground = setup_warehouse_with_crate(weight_lbs=1250, capacity_cwt=1000,
                                        checked_in_at=None,
                                        show_status="OPEN_FOR_ORDERS")
    floor_crate, _shipment = _receive_direct_to_show(ground, weight_lbs=2000,
                                                     crate_label="ACME-C2")
    _walk_show_from_open_for_orders_to_on_site(ground["show"]["id"])
    move_crate(floor_crate["id"], "ON_SHOW_FLOOR")

    emptied = move_crate(floor_crate["id"], "EMPTY_STORED")
    warehouse_after = get_warehouse(ground["warehouse"]["id"])

    assert_crate(emptied)
    assert_warehouse(warehouse_after)
    assert emptied["status"] == "EMPTY_STORED", (
        f"The show-floor crate is emptied, got {emptied['status']}")
    assert emptied["warehouse_id"] is None, (
        f"An EMPTY_STORED crate carries no warehouse_id, got {emptied['warehouse_id']}")
    assert warehouse_after["committed_cwt"] == 13, (
        "Only the checked-in 1250 lb crate counts, for 13 hundredweight, got "
        f"{warehouse_after['committed_cwt']}")
    assert warehouse_after["committed_cwt"] != 33, (
        "The 2000 lb EMPTY_STORED crate must not add its 20 hundredweight to the "
        "aggregate")


# ---------------------------------------------------------------------------
# Optimistic concurrency on the shared warehouse parent.
# ---------------------------------------------------------------------------

def test_stale_warehouse_version_rejects_second_crate_check_in(api):
    """PRD §2.7: "Checking a crate into a warehouse —
    `POST /crates/{id}/warehouse-check-in` — requires
    `expected_warehouse_version`, carrying the client's last observed `version`
    of the target `Warehouse`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_WAREHOUSE_VERSION` (HTTP
    412)."
    PRD §3.6: "On success the crate's `warehouse_id` is set, its `stored_since`
    is stamped with the logical clock's current instant, the warehouse's
    `committed_cwt` is recomputed upward and the warehouse's `version` increases
    by one."

    Design: Corner/cross_cutting_layers/occ_stale_warehouse_version_rejects_second_crate_checkin
    """
    set_clock(BASE_CLOCK)
    warehouse = create_warehouse(capacity_cwt=1000)
    version_before_any_arrival = warehouse["version"]
    exhibitor = create_exhibitor()
    first_crate = register_crate(exhibitor["id"], weight_lbs=1250,
                                 crate_label="ACME-C1")
    second_crate = register_crate(exhibitor["id"], weight_lbs=830,
                                  crate_label="ACME-C2")
    check_in_crate(first_crate["id"], warehouse["id"],
                   expected_warehouse_version=version_before_any_arrival)

    response = api.warehouse_check_in(
        second_crate["id"],
        {"warehouse_id": warehouse["id"],
         "expected_warehouse_version": version_before_any_arrival},
        make_warehouse_agent_headers(warehouse["id"]))

    validate_error(response, ApiErrorId.ERR_STALE_WAREHOUSE_VERSION.value, 412)
    second_after = get_crate(second_crate["id"])
    warehouse_after = get_warehouse(warehouse["id"])
    assert second_after["status"] == "REGISTERED", (
        "The rejected write changes no state, so the second crate stays REGISTERED, "
        f"got {second_after['status']}")
    assert second_after["warehouse_id"] is None, (
        f"The second crate never enters the warehouse, got {second_after['warehouse_id']}")
    assert warehouse_after["committed_cwt"] == 13, (
        "Only the first 1250 lb crate is held, for 13 hundredweight, got "
        f"{warehouse_after['committed_cwt']}")
    held_crates, meta = validate_paginated(
        api.list_crates(OPS, {"warehouse_id": warehouse["id"]}))
    assert meta["total_count"] == 1, (
        f"Exactly one crate sits at the warehouse, got {meta['total_count']}")
    assert len(held_crates) == 1 and held_crates[0]["id"] == first_crate["id"], (
        "The only crate at the warehouse is the one whose check-in succeeded")


# ---------------------------------------------------------------------------
# WarehouseAgent ownership on the check-in.
# ---------------------------------------------------------------------------

def test_warehouse_agent_cannot_check_in_to_another_warehouse(api):
    """PRD §2.1: "When `X-User-Role` is `WarehouseAgent`, `X-User-ID` is the `id`
    of the `Warehouse` the agent staffs; warehouse-scoped writes compare the
    `warehouse_id` the request targets to `X-User-ID` and reject a mismatch with
    the same `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.9: "Ownership: an acting `Exhibitor`'s `X-User-ID` equals the
    `exhibitor_id` reachable from the target resource, and an acting
    `WarehouseAgent`'s `X-User-ID` equals the `warehouse_id` the request targets
    — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/rbac/warehouse_agent_cannot_check_in_to_another_warehouse
    """
    set_clock(BASE_CLOCK)
    target_warehouse = create_warehouse(name="Chicago Advance WH", capacity_cwt=1000)
    other_warehouse = create_warehouse(name="Second Annex", capacity_cwt=1000)
    exhibitor = create_exhibitor()
    crate = register_crate(exhibitor["id"], weight_lbs=1250)

    response = api.warehouse_check_in(
        crate["id"],
        {"warehouse_id": target_warehouse["id"],
         "expected_warehouse_version": target_warehouse["version"]},
        make_warehouse_agent_headers(other_warehouse["id"]))

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    crate_after = get_crate(crate["id"])
    warehouse_after = get_warehouse(target_warehouse["id"])
    assert crate_after["status"] == "REGISTERED", (
        "The crate an unauthorised agent tried to check in stays REGISTERED, got "
        f"{crate_after['status']}")
    assert crate_after["warehouse_id"] is None, (
        f"The crate never enters the warehouse, got {crate_after['warehouse_id']}")
    assert warehouse_after["committed_cwt"] == 0, (
        "The targeted warehouse holds nothing, so committed_cwt stays 0, got "
        f"{warehouse_after['committed_cwt']}")
