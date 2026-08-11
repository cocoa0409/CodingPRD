"""Parts lots, reservations, the partial floor and unit conservation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_parts_conservation,
    assert_parts_lot,
    make_technician_headers,
    new_parts_lot,
    parts_allocation_payload,
    parts_lot_payload,
    read_parts_lot,
    reserve_parts,
    setup_rebuild_order_pending,
    start_service_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


def test_full_reservation_moves_every_unit_out_of_stock(api):
    """PRD 3.6: "If the lot's `on_hand_qty` is at least the requested quantity, the
    allocation's `status` is `RESERVED` and its `allocated_qty` equals the full request."
    PRD 3.6: "A successful reservation moves `allocated_qty` out of `on_hand_qty` on the
    lot and bumps the lot's `version` by 1; a lot whose `on_hand_qty` reaches 0 moves to
    `DEPLETED`."
    PRD 2.10: "**Parts units.** For every lot, `on_hand_qty` plus `allocated_qty` plus
    `consumed_qty` equals `initial_qty`."

    Design: Difficulty/compensating_invariant/parts_lot_unit_conservation_across_allocate_and_release
    """
    ctx = setup_rebuild_order_pending(deviation=60.0)
    lot = new_parts_lot("HAMMER_SET", 4)
    assert_parts_lot(lot)
    assert lot["on_hand_qty"] == 4 and lot["allocated_qty"] == 0

    allocation = reserve_parts(ctx["order"]["id"], lot["id"], 4, lot["version"])
    assert allocation["status"] == "RESERVED"
    assert allocation["allocated_qty"] == 4

    after = read_parts_lot(lot["id"])
    assert (after["on_hand_qty"], after["allocated_qty"], after["consumed_qty"]) == (0, 4, 0)
    assert after["status"] == "DEPLETED"
    assert_parts_conservation(after)


def test_releasing_an_allocation_restores_the_pool_with_zero_drift(api):
    """PRD 3.6: "Alternatively a `ShopManager` releases it, which moves the units from
    `allocated_qty` back into `on_hand_qty`, leaves `consumed_qty` untouched, returns a
    `DEPLETED` lot to `OPEN` once `on_hand_qty` is greater than 0, and bumps the lot's
    `version` by 1."
    PRD 2.10: "**Parts units.** For every lot, `on_hand_qty` plus `allocated_qty` plus
    `consumed_qty` equals `initial_qty`. The forward action is reserving units against a
    rebuild; the compensating action is releasing an allocation."

    Design: Difficulty/compensating_invariant/parts_lot_unit_conservation_across_allocate_and_release
    """
    ctx = setup_rebuild_order_pending(deviation=60.0)
    lot = new_parts_lot("HAMMER_SET", 4)
    allocation = reserve_parts(ctx["order"]["id"], lot["id"], 4, lot["version"])

    released = validate_success(api.release_parts_allocation(allocation["id"], MANAGER))
    assert released["status"] == "RELEASED"

    after = read_parts_lot(lot["id"])
    assert (after["on_hand_qty"], after["allocated_qty"], after["consumed_qty"]) == (4, 0, 0)
    assert after["status"] == "OPEN"
    assert after["initial_qty"] == 4
    assert_parts_conservation(after)


def test_request_at_the_partial_floor_is_filled_partially(api):
    """PRD 3.6: "If `on_hand_qty` falls short of the request but is at least the partial
    floor, the `status` is `PARTIAL` and `allocated_qty` equals whatever remains on hand
    — the shortfall is absorbed silently rather than raised as an error."
    PRD 3.6: "The ceiling on the floor matters: requesting 5 units with 2 on hand
    computes a floor of 3 and is refused, while requesting 4 units with 2 on hand
    computes a floor of 2 and is filled partially."

    Design: Corner/calculations/parts_partial_allocation_at_the_fifty_percent_floor
    """
    ctx = setup_rebuild_order_pending(deviation=45.0)
    lot = new_parts_lot("ACTION_PARTS", 2)

    allocation = validate_success(
        api.create_parts_allocation(
            ctx["order"]["id"],
            parts_allocation_payload(lot["id"], 4, lot["version"]),
            MANAGER,
        ),
        201,
    )
    assert allocation["status"] == "PARTIAL"
    assert allocation["allocated_qty"] == 2
    assert allocation["requested_qty"] == 4

    after = read_parts_lot(lot["id"])
    assert (after["on_hand_qty"], after["allocated_qty"], after["consumed_qty"]) == (0, 2, 0)
    assert after["status"] == "DEPLETED"
    assert_parts_conservation(after)

    refused = api.create_parts_allocation(
        ctx["order"]["id"],
        parts_allocation_payload(lot["id"], 5, after["version"]),
        MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_PARTS_INSUFFICIENT.value)


def test_consuming_an_allocation_moves_units_into_consumed(api):
    """PRD 3.6: "An allocation in `RESERVED` or `PARTIAL` may be consumed by a
    technician while its order is `IN_PROGRESS` or `COMPLETED`, which moves the units
    from the lot's `allocated_qty` into its `consumed_qty` and leaves `on_hand_qty`
    untouched, bumping the lot's `version` by 1."
    PRD 3.6: "`CONSUMED` and `RELEASED` are both terminal."
    PRD 2.8: "**Not already terminal.** The target resource must not already sit in a
    terminal state of its own machine. Otherwise `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/calculations/parts_consume_moves_units_from_allocated_to_consumed
    """
    ctx = setup_rebuild_order_pending(deviation=45.0, in_shop=True)
    lot = new_parts_lot("ACTION_PARTS", 2)
    allocation = reserve_parts(ctx["order"]["id"], lot["id"], 2, lot["version"])
    start_service_order(ctx["order"]["id"])

    technician_headers = make_technician_headers(ctx["technician"]["id"])
    consumed = validate_success(
        api.consume_parts_allocation(allocation["id"], technician_headers)
    )
    assert consumed["status"] == "CONSUMED"

    after = read_parts_lot(lot["id"])
    assert (after["on_hand_qty"], after["allocated_qty"], after["consumed_qty"]) == (0, 0, 2)
    assert after["status"] == "DEPLETED"
    assert_parts_conservation(after)

    second = api.consume_parts_allocation(allocation["id"], technician_headers)
    validate_error(second, ApiErrorId.ERR_ALREADY_TERMINAL.value)


def test_request_below_the_partial_floor_is_refused_outright(api):
    """PRD 3.6: "Below the partial floor the request is refused with
    `ERR_PARTS_INSUFFICIENT`."
    PRD 2.8: "**Parts sufficiency.** The lot's `on_hand_qty` must be at least the
    requested quantity multiplied by 0.50 and rounded up to a whole unit; below that the
    request is refused rather than partially filled. Otherwise `ERR_PARTS_INSUFFICIENT`
    (409). Applies to `POST /service-orders/{id}/parts-allocations`."

    Design: Corner/errors/parts_request_below_the_partial_floor_returns_parts_insufficient
    """
    ctx = setup_rebuild_order_pending(deviation=50.0)
    lot = new_parts_lot("HAMMER_SET", 1)

    response = api.create_parts_allocation(
        ctx["order"]["id"],
        parts_allocation_payload(lot["id"], 4, lot["version"]),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_PARTS_INSUFFICIENT.value)

    after = read_parts_lot(lot["id"])
    assert (after["on_hand_qty"], after["allocated_qty"], after["consumed_qty"]) == (1, 0, 0)
    assert after["status"] == "OPEN"

    rows, _ = validate_paginated(
        api.list_parts_allocations(
            MANAGER, params={"service_order_id": ctx["order"]["id"]}
        )
    )
    assert rows == []


def test_duplicate_lot_code_is_refused_across_part_types(api):
    """PRD 2.8: "**Lot-code uniqueness.** `lot_code` must be unique across all lots.
    Otherwise `ERR_DUPLICATE_LOT_CODE` (409). Applies to parts-lot creation."
    PRD 3.6: "A lot is received into stock with a `part_type` of `HAMMER_SET`,
    `STRING_SET` or `ACTION_PARTS`, a `lot_code` unique across all lots, and an
    `initial_qty` between 1 and 1000."

    Design: Corner/errors/parts_lot_duplicate_lot_code_returns_duplicate_lot_code
    """
    first = validate_success(
        api.create_parts_lot(
            parts_lot_payload("HAMMER_SET", 5, lot_code="LOT-SHARED-A"), MANAGER
        ),
        201,
    )

    response = api.create_parts_lot(
        parts_lot_payload("STRING_SET", 3, lot_code="LOT-SHARED-A"), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_LOT_CODE.value)

    after = read_parts_lot(first["id"])
    assert after["on_hand_qty"] == 5
    assert after["initial_qty"] == 5


def test_second_reservation_quoting_a_stale_lot_version_is_rejected(api):
    """PRD 2.7: "Reserving parts against a rebuild requires `expected_parts_lot_version`
    carrying the client's last observed `version` of the lot, and rejects a mismatch
    with `ERR_STALE_PARTS_LOT_VERSION` (HTTP 412). A partial allocation is a legitimate
    outcome here, so without the check a second writer's request would quietly succeed
    with a smaller `allocated_qty` than it believed it was asking for."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_parts_lot_version_on_second_allocation
    """
    ctx = setup_rebuild_order_pending(deviation=50.0)
    lot = new_parts_lot("HAMMER_SET", 6)
    stale_version = lot["version"]

    reserve_parts(ctx["order"]["id"], lot["id"], 4, stale_version)

    response = api.create_parts_allocation(
        ctx["order"]["id"],
        parts_allocation_payload(lot["id"], 2, stale_version),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_PARTS_LOT_VERSION.value)

    after = read_parts_lot(lot["id"])
    assert (after["on_hand_qty"], after["allocated_qty"], after["consumed_qty"]) == (2, 4, 0)
    assert_parts_conservation(after)

    rows, _ = validate_paginated(
        api.list_parts_allocations(
            MANAGER, params={"service_order_id": ctx["order"]["id"]}
        )
    )
    assert len(rows) == 1
