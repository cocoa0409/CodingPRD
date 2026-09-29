"""Transitive cascades: a store receive, a run commit and a store closure."""
from test_helpers import (
    STORE_SPECS_FOUR,
    ApiErrorId,
    actions_for,
    create_receipt,
    line_for_store,
    make_store_operator_headers,
    lines_for_run,
    propose_transfer,
    receive_transfer,
    refresh_item,
    refresh_position,
    refresh_program,
    refresh_receipt,
    run_detection,
    set_store_status,
    setup_detected_action,
    setup_network,
    setup_network_with_staged_receipt,
    size_units,
    validate_error,
    validate_success,
)


def _dispatched_rebalance_over_a_pending_action(api, headers):
    """A PENDING assortment action on 0101 plus a six-unit rebalance from 0102 that
    has been proposed, approved and dispatched."""
    scenario = setup_detected_action()
    scenario["transfer"] = propose_transfer(scenario, units=6)
    validate_success(api.approve_transfer(scenario["transfer"]["id"], headers))
    validate_success(api.dispatch_transfer(scenario["transfer"]["id"], headers))
    return scenario


def test_receiving_a_rebalance_cascades_position_then_sku_then_the_pending_action(
    api, allocation_manager_headers
):
    """PRD §3.8: "The transfer's `units` move out of the receiving position's
    `in_transit_units` and into its `on_hand_units`, and the `size_split` entries are
    merged into its `size_on_hand`." "Any assortment action still `PENDING` for the
    receiving position's SKU-and-store pair whose triggering condition no longer
    holds is driven to `SUPERSEDED`."

    The arrival closes 0101's two size holes, which drops the SKU's
    `broken_store_count` to 0 and returns it to ACTIVE, which in turn retires the
    detection sweep's action — and the action keeps the figures it snapshotted.

    Design: Difficulty/transitive_cascade/transfer_receive_cascades_position_then_item_then_assortment_action
    """
    scenario = _dispatched_rebalance_over_a_pending_action(
        api, allocation_manager_headers
    )
    action_id = scenario["action"]["id"]

    receive_transfer(scenario, to_code="0101")

    receiver = refresh_position(scenario, "0101")
    assert receiver["on_hand_units"] == 10
    assert size_units(receiver, "size_on_hand") == {"S": 4, "M": 3, "L": 1, "XL": 2}
    assert receiver["in_transit_units"] == 0
    assert receiver["broken_size_count"] == 0
    assert receiver["assortment_status"] == "COMPLETE"
    assert receiver["stock_status"] == "LOW"

    item = refresh_item(scenario)
    assert item["broken_store_count"] == 0
    assert item["size_out_store_count"] == 0
    assert item["lifecycle_state"] == "ACTIVE"

    action = validate_success(
        api.get_assortment_action(action_id, allocation_manager_headers)
    )
    assert action["status"] == "SUPERSEDED"
    assert action["broken_size_count"] == 2
    assert action["units_at_detection"] == 4


def test_the_donor_side_of_a_receive_cascades_no_further_than_its_own_position(
    api, allocation_manager_headers
):
    """PRD §3.8: "Both positions have `broken_size_count`, `stock_status` and
    `assortment_status` re-derived." PRD §3.3: "`reserved_out_units` is the sum of
    `units` over transfer recommendations for this SKU whose `from_store_id` is this
    store and whose `status` is `APPROVED` or `DISPATCHED` — stock the store still
    physically holds but has already promised away."

    Once the recommendation reaches RECEIVED the donor's reservation stops counting,
    so 0102 shows 24 available against 24 on hand and sits in IN_STOCK with its
    assortment never having moved.

    Design: Difficulty/transitive_cascade/transfer_receive_cascades_position_then_item_then_assortment_action
    """
    scenario = _dispatched_rebalance_over_a_pending_action(
        api, allocation_manager_headers
    )

    receive_transfer(scenario, to_code="0101")

    donor = refresh_position(scenario, "0102")
    assert donor["on_hand_units"] == 24
    assert donor["reserved_out_units"] == 0
    assert donor["available_units"] == 24
    assert donor["stock_status"] == "IN_STOCK"
    assert donor["assortment_status"] == "COMPLETE"


def test_a_second_receive_is_refused_on_the_state_rung_and_moves_nothing(
    api, allocation_manager_headers, store_operator_headers
):
    """PRD §2.10: "a dispatch requires an `APPROVED` recommendation; a transfer
    receive requires a `DISPATCHED` recommendation". PRD §3.8: "takes the
    recommendation `DISPATCHED → RECEIVED`, which is terminal."

    The second confirmation is refused and every figure the first one wrote stands
    unchanged.

    Design: Difficulty/transitive_cascade/transfer_receive_cascades_position_then_item_then_assortment_action
    """
    scenario = _dispatched_rebalance_over_a_pending_action(
        api, allocation_manager_headers
    )
    receive_transfer(scenario, to_code="0101")
    before = refresh_position(scenario, "0101")

    validate_error(
        api.receive_transfer(
            scenario["transfer"]["id"],
            make_store_operator_headers(scenario["stores"]["0101"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    after = refresh_position(scenario, "0101")
    assert after["on_hand_units"] == before["on_hand_units"] == 10
    assert after["version"] == before["version"]
    assert refresh_item(scenario)["lifecycle_state"] == "ACTIVE"


def _proposed_run_over_a_pool_equal_to_network_need(api, headers):
    """A 44-unit receipt is exactly the 26 + 10 + 8 the network needs under
    FORWARD_LOOKING, so the waterfall places every unit."""
    scenario = setup_network_with_staged_receipt(
        units_received=44,
        size_received=[
            {"size_code": "S", "units": 8},
            {"size_code": "M", "units": 16},
            {"size_code": "L", "units": 14},
            {"size_code": "XL", "units": 6},
        ],
    )
    receipt = scenario["receipt"]
    run = validate_success(
        api.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": receipt["version"],
            },
            headers,
        ),
        201,
    )
    scenario["run"] = validate_success(api.propose_run(run["id"], headers))
    return scenario


def test_commit_books_the_lines_then_the_receipt_ledger_then_the_program_reserve(
    api, allocator_headers, allocation_manager_headers
):
    """PRD §3.7: "Every line's `units_allocated` is set equal to its `units_proposed`
    and its `fulfillment_status` is set to `PENDING`." "The receipt's
    `units_committed` and `units_unallocated` are recomputed, and if
    `units_unallocated` reaches 0 the receipt is driven `ALLOCATING → ALLOCATED`."
    PRD §2.9: "`open_reserve_units` is `total_units_received` minus
    `total_units_committed`, representing the DC-side units not yet committed to any
    store."

    The three lines book 26, 10 and 8 units, which empties the 44-unit pool exactly,
    which flips the receipt to ALLOCATED, which drives the program's open reserve to
    zero.

    Design: Difficulty/transitive_cascade/run_commit_cascades_lines_then_receipt_ledger_then_program_reserve
    """
    scenario = _proposed_run_over_a_pool_equal_to_network_need(api, allocator_headers)
    run_id = scenario["run"]["id"]
    stores = scenario["stores"]

    committed = validate_success(api.commit_run(run_id, allocation_manager_headers))

    allocated = {
        code: line_for_store(run_id, stores[code]["id"])
        for code in ("0101", "0103", "0104")
    }
    assert allocated["0101"]["units_allocated"] == 26
    assert allocated["0103"]["units_allocated"] == 10
    assert allocated["0104"]["units_allocated"] == 8
    assert all(
        line["fulfillment_status"] == "PENDING" for line in allocated.values()
    )
    assert len(lines_for_run(run_id)) == 3

    receipt = refresh_receipt(scenario)
    assert receipt["units_committed"] == 44
    assert receipt["units_unallocated"] == 0
    assert receipt["status"] == "ALLOCATED"

    program = refresh_program(scenario)
    assert program["total_units_received"] == 44
    assert program["total_units_committed"] == 44
    assert program["open_reserve_units"] == 0

    assert committed["status"] == "COMMITTED"
    assert committed["units_committed"] == 44
    assert committed["unallocated_remainder_units"] == 0
    assert committed["proposed_by_user_id"] != committed["committed_by_user_id"]


def test_commit_books_the_ledger_without_moving_a_single_unit_of_store_stock(
    api, allocator_headers, allocation_manager_headers
):
    """PRD §2.9: "Only the DC-to-store leg changes the sum: releasing an allocation
    line from the DC raises it by exactly that line's `units_allocated`, because units
    that were sitting at the DC become in-transit stock in the network, while the
    store's later confirmation merely converts in-transit units into on-hand units and
    changes nothing." PRD §3.6: "A line's `units_allocated` is 0 while the run is
    merely `PROPOSED`, becomes equal to its `units_proposed` once the run is
    `COMMITTED`, and returns to 0 if the run is later recalled."

    Store 0101 still holds its opening six units with nothing in transit after the
    commit, because only a release from the DC moves stock.

    Design: Difficulty/transitive_cascade/run_commit_cascades_lines_then_receipt_ledger_then_program_reserve
    """
    scenario = _proposed_run_over_a_pool_equal_to_network_need(api, allocator_headers)

    before = refresh_position(scenario, "0101")
    assert before["on_hand_units"] == 6
    assert line_for_store(
        scenario["run"]["id"], scenario["stores"]["0101"]["id"]
    )["units_allocated"] == 0

    validate_success(api.commit_run(scenario["run"]["id"], allocation_manager_headers))

    after = refresh_position(scenario, "0101")
    assert after["on_hand_units"] == 6
    assert after["in_transit_units"] == 0
    assert after["available_units"] == 6


def _two_store_network_with_one_empty_position():
    """Store 0101 holds nothing at all, so all four CORE sizes are missing and the SKU
    opens BROKEN; store 0102 holds twelve units across every size and is COMPLETE."""
    fixture_specs = {
        code: {
            "fixture_count": 2,
            "facings_per_fixture": 3,
            "units_per_facing": 4,
            "presentation_min_units": 8,
        }
        for code in ("0101", "0102")
    }
    position_specs = {
        "0101": {
            "on_hand_units": 0,
            "size_on_hand": [],
            "min_units": 12,
            "max_units": 24,
            "weekly_forecast_units": 9,
            "trailing_4wk_sales_units": 30,
        },
        "0102": {
            "on_hand_units": 12,
            "size_on_hand": [
                {"size_code": "S", "units": 3},
                {"size_code": "M", "units": 3},
                {"size_code": "L", "units": 3},
                {"size_code": "XL", "units": 3},
            ],
            "min_units": 8,
            "max_units": 24,
            "weekly_forecast_units": 5,
            "trailing_4wk_sales_units": 16,
        },
    }
    scenario = setup_network(
        store_specs=STORE_SPECS_FOUR[:2],
        fixture_specs=fixture_specs,
        position_specs=position_specs,
    )
    run_detection(scenario["program"]["id"])
    matches = actions_for(
        scenario["program"]["id"],
        item_id=scenario["item"]["id"],
        store_id=scenario["stores"]["0101"]["id"],
    )
    assert matches, "Setup failed: detection raised no action for the empty position"
    scenario["action"] = matches[0]
    return scenario


def test_a_closing_store_that_still_holds_units_cannot_reach_closed(
    api, planning_admin_headers
):
    """PRD §3.1: "`CLOSING → CLOSED` is permitted only when every position of the
    store holds `on_hand_units` of 0, and is otherwise refused with
    `ERR_STORE_HAS_INVENTORY`".

    Store 0102 still holds twelve units, so the closure is refused and the store is
    left in CLOSING with its position untouched — the cascade never starts.

    Design: Difficulty/transitive_cascade/store_closed_cascades_position_exit_then_item_lifecycle
    """
    scenario = _two_store_network_with_one_empty_position()
    store_id = scenario["stores"]["0102"]["id"]

    set_store_status(store_id, "CLOSING")

    validate_error(
        api.set_store_status(
            store_id, {"target_status": "CLOSED"}, planning_admin_headers
        ),
        ApiErrorId.ERR_STORE_HAS_INVENTORY.value,
        409,
    )

    assert validate_success(api.get_store(store_id, planning_admin_headers))["status"] == (
        "CLOSING"
    )
    position = refresh_position(scenario, "0102")
    assert position["assortment_status"] == "COMPLETE"
    assert position["stock_status"] == "IN_STOCK"


def test_closing_a_store_exits_its_positions_and_re_derives_the_sku_with_no_stock_moving(
    api, planning_admin_headers, allocation_manager_headers
):
    """PRD §3.1: "when it succeeds it sets `assortment_status` to `EXITED` on every
    position of the store, recomputes `broken_store_count` and `size_out_store_count`
    on every affected SKU and re-derives each of those SKUs' `lifecycle_state`, and
    advances `version` by one." PRD §3.3: "One more knock-on: whenever a position's
    `assortment_status` returns to `COMPLETE`, any assortment action still sitting at
    `PENDING` for that same SKU-and-store pair is driven to `SUPERSEDED` and its
    `version` advances by one".

    The empty position leaves the count of broken doors at zero purely by exiting, so
    the SKU returns to ACTIVE without a unit moving; the sweep's MARKDOWN action stays
    PENDING because EXITED is not COMPLETE.

    Design: Difficulty/transitive_cascade/store_closed_cascades_position_exit_then_item_lifecycle
    """
    scenario = _two_store_network_with_one_empty_position()
    store_id = scenario["stores"]["0101"]["id"]
    action = scenario["action"]

    assert action["action_type"] == "MARKDOWN"
    assert action["consolidation_target_store_id"] is None
    assert action["markdown_pct_bp"] == 4500
    assert refresh_item(scenario)["lifecycle_state"] == "BROKEN"

    set_store_status(store_id, "CLOSING")
    set_store_status(store_id, "CLOSED")

    exited = refresh_position(scenario, "0101")
    assert exited["assortment_status"] == "EXITED"
    assert exited["stock_status"] == "STOCKOUT"
    assert exited["on_hand_units"] == 0

    item = refresh_item(scenario)
    assert item["broken_store_count"] == 0
    assert item["size_out_store_count"] == 0
    assert item["lifecycle_state"] == "ACTIVE"

    assert validate_success(
        api.get_assortment_action(action["id"], allocation_manager_headers)
    )["status"] == "PENDING"

    untouched = refresh_position(scenario, "0102")
    assert untouched["assortment_status"] == "COMPLETE"
    assert untouched["stock_status"] == "IN_STOCK"
