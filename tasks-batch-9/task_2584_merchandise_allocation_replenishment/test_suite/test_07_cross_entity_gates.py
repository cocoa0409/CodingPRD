"""Cross-entity gates: one entity's state deciding what another entity may do."""
from test_helpers import (
    ApiErrorId,
    POSITION_SPECS_REBALANCE,
    actions_for,
    create_committed_run,
    create_snapshot_payload,
    create_receipt_payload,
    create_transfer_payload,
    current_position_version,
    line_for_store,
    lock_program,
    make_store_operator_headers,
    propose_transfer,
    refresh_item,
    refresh_position,
    refresh_receipt,
    run_detection,
    set_store_status,
    setup_network_with_staged_receipt,
    setup_rebalance_network,
    setup_receipt_network,
    size_units,
    units_by_size,
    validate_error,
    validate_success,
)

RECEIPT_SIZES_44 = [
    {"size_code": "S", "units": 8},
    {"size_code": "M", "units": 16},
    {"size_code": "L", "units": 14},
    {"size_code": "XL", "units": 6},
]


def _network_units(scenario):
    """Units the network holds for the SKU: on hand plus in transit, over every door."""
    total = 0
    for code in scenario["positions"]:
        position = refresh_position(scenario, code)
        total += position["on_hand_units"] + position["in_transit_units"]
    return total


def _committed_spread_inside_a_locked_program():
    """A 44-unit receipt spread DEMAND_DRIVEN / FORWARD_LOOKING and COMMITTED into lines
    of 26, 10 and 8 units, after which the program is LOCKED. The network holds 28 units
    across its four positions before anything ships."""
    scenario = setup_network_with_staged_receipt(
        units_received=44, size_received=RECEIPT_SIZES_44
    )
    scenario["run"] = create_committed_run(scenario["receipt"]["id"])
    scenario["line"] = line_for_store(
        scenario["run"]["id"], scenario["stores"]["0101"]["id"]
    )
    scenario["program"] = lock_program(
        scenario["program"]["id"], "physical inventory count"
    )
    return scenario


def test_a_locked_program_still_lets_a_committed_line_ship_and_land(
    api, allocation_manager_headers
):
    """PRD §2.6: "A lock is deliberately narrower than a freeze." And: "**Physical
    logistics are exempt**: releasing an allocation line from the DC, a store confirming
    physical receipt of a line, and a store receiving a dispatched transfer all remain
    permitted while the program is `LOCKED`, because goods already in motion must be
    allowed to land." PRD §3.7: "Confirmation runs the deepest cascade on the inbound
    side: the line's `units_allocated` are added to the position's `on_hand_units` and
    the line's `size_breakdown` is merged into the position's `size_on_hand`; the same
    quantity is removed from the position's `in_transit_units`; if `on_hand_units`
    becomes greater than zero, the position's `consolidated_out` flag is cleared back to
    false; the position's `broken_size_count`, `stock_status` and `assortment_status` are
    all re-derived; the SKU's `broken_store_count` and `size_out_store_count` are
    recomputed and its `lifecycle_state` is re-derived under the pinned order in §3.3;
    and the line's `version` advances by one."

    The line's own state machine never consults the lock: 26 units leave the DC and land
    at 0101, which ends COMPLETE and IN_STOCK on 32 units.

    Design: Difficulty/cross_entity_state_dependency/locked_program_blocks_decisions_but_not_line_ship_or_confirm_receipt
    """
    scenario = _committed_spread_inside_a_locked_program()
    line_id = scenario["line"]["id"]
    store_id = scenario["stores"]["0101"]["id"]
    assert scenario["program"]["status"] == "LOCKED"
    assert scenario["program"]["lock_reason"] == "physical inventory count"

    shipped = validate_success(api.ship_line(line_id, allocation_manager_headers))
    assert shipped["fulfillment_status"] == "SHIPPED"

    in_flight = refresh_position(scenario, "0101")
    assert in_flight["in_transit_units"] == 26
    assert in_flight["on_hand_units"] == 6

    landed = validate_success(
        api.confirm_line_receipt(line_id, make_store_operator_headers(store_id))
    )
    assert landed["fulfillment_status"] == "RECEIVED"

    arrived = refresh_position(scenario, "0101")
    assert arrived["on_hand_units"] == 32
    assert arrived["in_transit_units"] == 0
    assert size_units(arrived, "size_on_hand") == {"S": 5, "M": 14, "L": 10, "XL": 3}
    assert arrived["broken_size_count"] == 0
    assert arrived["assortment_status"] == "COMPLETE"
    assert arrived["stock_status"] == "IN_STOCK"


def test_the_same_lock_refuses_a_new_receipt_and_a_new_snapshot(
    api, allocator_headers, allocation_manager_headers
):
    """PRD §2.6: "Only an `ACTIVE` program admits **decisions**: booking a receipt,
    correcting a receipt count, opening an allocation run, proposing, revising or
    committing a spread, creating, approving or dispatching a transfer, running the
    assortment detection sweep, executing an assortment remedy, and creating a cluster
    snapshot." And: "Attempting any of those while the program is `PLANNING`, `LOCKED` or
    `CLOSED` is rejected with `ERR_PROGRAM_LOCKED` and HTTP 409."

    While the truck is legally rolling, both of the decisions on either side of it are
    frozen, and the already-committed ledger is left exactly as it stood.

    Design: Difficulty/cross_entity_state_dependency/locked_program_blocks_decisions_but_not_line_ship_or_confirm_receipt
    """
    scenario = _committed_spread_inside_a_locked_program()
    validate_success(api.ship_line(scenario["line"]["id"], allocation_manager_headers))

    validate_error(
        api.create_receipt(
            create_receipt_payload(
                scenario["program"]["id"],
                scenario["item"]["id"],
                reference="ASN-9007",
                units_received=10,
                size_received=[{"size_code": "M", "units": 10}],
            ),
            allocator_headers,
        ),
        ApiErrorId.ERR_PROGRAM_LOCKED.value,
        409,
    )
    validate_error(
        api.create_performance_snapshot(
            create_snapshot_payload(scenario["program"]["id"], "URBAN"),
            allocation_manager_headers,
        ),
        ApiErrorId.ERR_PROGRAM_LOCKED.value,
        409,
    )

    run = validate_success(
        api.get_allocation_run(scenario["run"]["id"], allocation_manager_headers)
    )
    assert run["status"] == "COMMITTED"
    assert run["units_committed"] == 44
    assert refresh_receipt(scenario)["units_committed"] == 44


def test_the_recall_is_refused_for_the_shipment_and_not_for_the_lock(
    api, allocation_manager_headers
):
    """PRD §3.7: "An `AllocationManager` may recall a `COMMITTED` run only while
    **every** one of its lines is still `PENDING`; if even one line has already been
    released from the DC or landed at a store, the recall is refused with
    `ERR_LINE_ALREADY_SHIPPED`."

    Recall is absent from §2.6's list of decisions, so the lock never answers for it;
    the shipment the lock permitted is what closes the compensating path.

    Design: Difficulty/cross_entity_state_dependency/locked_program_blocks_decisions_but_not_line_ship_or_confirm_receipt
    """
    scenario = _committed_spread_inside_a_locked_program()
    run_id = scenario["run"]["id"]
    store_id = scenario["stores"]["0101"]["id"]

    validate_success(api.ship_line(scenario["line"]["id"], allocation_manager_headers))
    validate_success(
        api.confirm_line_receipt(
            scenario["line"]["id"], make_store_operator_headers(store_id)
        )
    )

    validate_error(
        api.recall_run(run_id, allocation_manager_headers),
        ApiErrorId.ERR_LINE_ALREADY_SHIPPED.value,
        409,
    )
    run = validate_success(api.get_allocation_run(run_id, allocation_manager_headers))
    assert run["status"] == "COMMITTED"


def test_the_shipment_is_the_only_step_that_changes_the_network_total(
    api, allocation_manager_headers
):
    """PRD §3.7: "The release adds the line's `units_allocated` to the destination
    position's `in_transit_units` and re-derives that position's `stock_status`; the
    line's `version` advances by one." And: "This is one of the three operations
    explicitly permitted while the program is `LOCKED`, because a lock freezes decisions
    and not trucks."

    The four doors hold 28 units; releasing 26 from the DC takes the network to 54, and
    landing them merely moves those units from in-transit to on-hand, so the total is
    unchanged while one of the three broken doors is repaired.

    Design: Difficulty/cross_entity_state_dependency/locked_program_blocks_decisions_but_not_line_ship_or_confirm_receipt
    """
    scenario = _committed_spread_inside_a_locked_program()
    store_id = scenario["stores"]["0101"]["id"]

    assert _network_units(scenario) == 28
    assert refresh_item(scenario)["broken_store_count"] == 3

    validate_success(api.ship_line(scenario["line"]["id"], allocation_manager_headers))
    assert _network_units(scenario) == 54

    validate_success(
        api.confirm_line_receipt(
            scenario["line"]["id"], make_store_operator_headers(store_id)
        )
    )
    assert _network_units(scenario) == 54

    item = refresh_item(scenario)
    assert item["broken_store_count"] == 2
    assert item["lifecycle_state"] == "BROKEN"


def _approved_rebalance_into_a_store_that_can_be_taken_offline(api, manager_headers):
    """An APPROVED six-unit rebalance 0102 -> 0101 in a program with no ratio floor.
    0103 holds five units in M, L and XL only, so its S size is out."""
    position_specs = {
        code: dict(spec) for code, spec in POSITION_SPECS_REBALANCE.items()
    }
    position_specs["0103"] = dict(
        position_specs["0103"],
        on_hand_units=5,
        size_on_hand=[
            {"size_code": "M", "units": 2},
            {"size_code": "L", "units": 2},
            {"size_code": "XL", "units": 1},
        ],
    )
    scenario = setup_rebalance_network(
        program_overrides={"transfer_min_ratio_bp": 0},
        position_specs=position_specs,
    )
    proposed = propose_transfer(scenario, units=6)
    scenario["transfer"] = validate_success(
        api.approve_transfer(proposed["id"], manager_headers)
    )
    return scenario


def test_a_remodelling_receiver_blocks_a_dispatch_its_own_state_permits(
    api, allocation_manager_headers, planning_admin_headers
):
    """PRD §3.8: "**Dispatch** takes the recommendation `APPROVED → DISPATCHED` and
    requires that the program be `ACTIVE`, or the refusal is `ERR_PROGRAM_LOCKED`, and
    that the receiving store's `status` still be `ACTIVE`, or the refusal is
    `ERR_STORE_NOT_ELIGIBLE`." PRD §3.1: "`ACTIVE → REMODEL` excludes the store from
    every subsequent allocation proration candidate set and from every
    consolidation-target candidate set, and advances `version` by one; allocation lines
    already `PENDING` or `SHIPPED` and transfers already `APPROVED` are untouched,
    because only future decisions change."

    The recommendation is squarely APPROVED and therefore dispatchable, yet a different
    entity — the receiving store — refuses the move, and no stock shifts on either side.

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatch_and_create_gated_by_the_other_stores_status
    """
    scenario = _approved_rebalance_into_a_store_that_can_be_taken_offline(
        api, allocation_manager_headers
    )
    transfer = scenario["transfer"]
    assert transfer["status"] == "APPROVED"

    set_store_status(scenario["stores"]["0101"]["id"], "REMODEL")

    validate_error(
        api.dispatch_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_STORE_NOT_ELIGIBLE.value,
        409,
    )

    still_approved = validate_success(
        api.get_transfer_recommendation(transfer["id"], allocation_manager_headers)
    )
    assert still_approved["status"] == "APPROVED"

    receiver = refresh_position(scenario, "0101")
    assert receiver["in_transit_units"] == 0
    donor = refresh_position(scenario, "0102")
    assert donor["on_hand_units"] == 30
    assert donor["reserved_out_units"] == 6


def test_returning_the_store_to_active_lets_the_identical_dispatch_through(
    api, allocation_manager_headers, planning_admin_headers
):
    """PRD §3.1: "`REMODEL → ACTIVE` returns the store to eligibility and advances
    `version` by one — the cycle may be repeated, so a store may re-enter allocation
    after a remodel." PRD §3.8: "It subtracts the transfer's `units` from the donor
    position's `on_hand_units` and removes the `size_split` quantities from the donor's
    `size_on_hand`, keeping the `reserved_out_units` bookkeeping consistent as the
    reservation converts into an actual departure; it adds the `units` to the receiving
    position's `in_transit_units`; it re-derives `broken_size_count`, `stock_status` and
    `assortment_status` on **both** positions; it recomputes the SKU's
    `broken_store_count` and `size_out_store_count` and re-derives its `lifecycle_state`;
    and it advances the recommendation's `version` by one."

    Nothing about the recommendation changed between the refusal and the success — only
    the other store's status did, twice, each advancing that store's version.

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatch_and_create_gated_by_the_other_stores_status
    """
    scenario = _approved_rebalance_into_a_store_that_can_be_taken_offline(
        api, allocation_manager_headers
    )
    store = scenario["stores"]["0101"]
    opening_version = store["version"]

    set_store_status(store["id"], "REMODEL")
    validate_error(
        api.dispatch_transfer(scenario["transfer"]["id"], allocation_manager_headers),
        ApiErrorId.ERR_STORE_NOT_ELIGIBLE.value,
        409,
    )
    set_store_status(store["id"], "ACTIVE")

    dispatched = validate_success(
        api.dispatch_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )
    assert dispatched["status"] == "DISPATCHED"

    reopened = validate_success(api.get_store(store["id"], planning_admin_headers))
    assert reopened["status"] == "ACTIVE"
    assert reopened["version"] == opening_version + 2

    receiver = refresh_position(scenario, "0101")
    assert receiver["in_transit_units"] == 6
    donor = refresh_position(scenario, "0102")
    assert donor["on_hand_units"] == 24
    assert size_units(donor, "size_on_hand") == {"S": 4, "M": 10, "L": 8, "XL": 2}


def test_a_closing_store_may_not_be_named_as_the_receiver_of_a_new_transfer(
    api, allocator_headers, allocation_manager_headers
):
    """PRD §3.8: "The receiver must be an `ACTIVE` store at creation time — a `REMODEL`,
    `CLOSING` or `CLOSED` store may not receive — and the refusal is
    `ERR_STORE_NOT_ELIGIBLE`; a `CLOSING` store may still donate." PRD §2.10 rung 26:
    "Store status eligibility for transfers and allocation — `ERR_STORE_NOT_ELIGIBLE`,
    409."

    The eligibility rule guards creation as well as dispatch, so a door on its way out
    of the estate cannot be sent more stock.

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatch_and_create_gated_by_the_other_stores_status
    """
    scenario = _approved_rebalance_into_a_store_that_can_be_taken_offline(
        api, allocation_manager_headers
    )
    set_store_status(scenario["stores"]["0103"]["id"], "CLOSING")

    payload = create_transfer_payload(
        scenario["program"]["id"],
        scenario["stores"]["0102"]["id"],
        scenario["stores"]["0103"]["id"],
        scenario["item"]["id"],
        4,
        current_position_version(scenario["positions"]["0102"]["id"]),
    )
    validate_error(
        api.create_transfer_recommendation(payload, allocator_headers),
        ApiErrorId.ERR_STORE_NOT_ELIGIBLE.value,
        409,
    )


def test_the_same_closing_store_may_still_donate_its_remaining_stock(
    api, allocator_headers, allocation_manager_headers
):
    """PRD §3.1: "`ACTIVE → CLOSING` excludes the store from allocation proration and
    bars it from being a transfer **receiver**, while leaving it fully eligible as a
    transfer **donor**, and advances `version` by one; that asymmetry exists so that a
    closing door's stock can be swept back into the chain." PRD §3.8: "Step one is
    freight: the donor store's `freight_flat_usd` plus 85 cents per unit moved, that sum
    rounded half up to two decimals, and the result taken as the greater of itself and a
    floor of 45 dollars — so a tiny transfer from a cheap donor still costs 45.00 — and
    stored as `freight_cost_usd`."

    One unit out of the closing door is accepted, and because XL is the only CORE size
    0101 lacks that 0103 still holds, the whole move is a single XL priced against the
    45.00 freight floor.

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatch_and_create_gated_by_the_other_stores_status
    """
    scenario = _approved_rebalance_into_a_store_that_can_be_taken_offline(
        api, allocation_manager_headers
    )
    set_store_status(scenario["stores"]["0103"]["id"], "CLOSING")

    payload = create_transfer_payload(
        scenario["program"]["id"],
        scenario["stores"]["0103"]["id"],
        scenario["stores"]["0101"]["id"],
        scenario["item"]["id"],
        1,
        current_position_version(scenario["positions"]["0103"]["id"]),
    )
    donated = validate_success(
        api.create_transfer_recommendation(payload, allocator_headers), 201
    )
    assert donated["status"] == "PROPOSED"
    assert donated["units"] == 1
    assert units_by_size(donated["size_split"]) == {"XL": 1}
    assert float(donated["freight_cost_usd"]) == 45.00
    assert float(donated["landed_cost_usd"]) == 50.40
    assert float(donated["benefit_usd"]) == 13.05
    assert donated["benefit_ratio_bp"] == 2589


def _three_pending_actions_on_one_sku():
    """One detection sweep over the four-store network. 0101 (S and XL out, available 6),
    0103 (S and XL out, available 2) and 0104 (completely empty, available 0) are
    degraded; 0102 is COMPLETE and raises nothing."""
    scenario = setup_receipt_network()
    scenario["raised"] = run_detection(scenario["program"]["id"])
    scenario["actions"] = {}
    for code in ("0101", "0103", "0104"):
        matches = actions_for(
            scenario["program"]["id"],
            item_id=scenario["item"]["id"],
            store_id=scenario["stores"][code]["id"],
        )
        assert matches, f"Setup failed: no action raised for store {code}"
        scenario["actions"][code] = matches[0]
    return scenario


def test_the_sweep_raises_one_action_per_degraded_door_in_store_code_order(
    api, allocation_manager_headers
):
    """PRD §3.9: "The sweep scans every store position of the program looking for
    degraded assortment health and raises exactly one `PENDING` **assortment action** per
    newly degraded position." And: "The actions the sweep returns are ordered by the
    store's `store_code` ascending and then by the SKU's `sku_code` ascending — this is
    one of the few places a list is not ordered by `created_at`."

    Three of the four doors are degraded and the COMPLETE one is passed over, so the
    three actions that share this SKU arrive in 0101, 0103, 0104 order.

    Design: Difficulty/cross_entity_state_dependency/assortment_action_execute_gated_by_the_shared_items_lifecycle_state
    """
    scenario = _three_pending_actions_on_one_sku()
    raised = scenario["raised"]

    assert len(raised) == 3
    assert [action["store_id"] for action in raised] == [
        scenario["stores"]["0101"]["id"],
        scenario["stores"]["0103"]["id"],
        scenario["stores"]["0104"]["id"],
    ]
    assert all(action["status"] == "PENDING" for action in raised)
    assert not actions_for(
        scenario["program"]["id"],
        item_id=scenario["item"]["id"],
        store_id=scenario["stores"]["0102"]["id"],
    )


def test_the_only_complete_peer_absorbs_one_door_and_fails_the_other_two(
    api, allocation_manager_headers
):
    """PRD §3.9: "Given the degraded position, the candidate consolidation targets are
    the other positions of the **same SKU** that satisfy all of the following: they belong
    to a different store; their own `assortment_status` is `COMPLETE`; their store's
    `status` is `ACTIVE`; and their headroom — the greater of zero and their in-effect
    shelf plan's `capacity_units` less their `available_units` less their `in_transit_units`
    — is greater than or equal to the degraded position's `available_units`, so the target
    can physically absorb the whole move." And: "Because the eligibility filter runs
    before the ranking, the highest sell-through store in the network can still lose to a
    lower one simply for having no fixture headroom."

    0102 has headroom of only 4 units, which covers 0103's two units but not 0101's six,
    and 0104's empty shelf short-circuits the search entirely — so one CONSOLIDATION and
    two MARKDOWNs at different depths.

    Design: Difficulty/cross_entity_state_dependency/assortment_action_execute_gated_by_the_shared_items_lifecycle_state
    """
    scenario = _three_pending_actions_on_one_sku()

    peer = refresh_position(scenario, "0102")
    assert peer["assortment_status"] == "COMPLETE"
    assert scenario["fixture_plans"]["0102"]["capacity_units"] - peer["available_units"] == 4

    too_big = scenario["actions"]["0101"]
    assert too_big["units_at_detection"] == 6
    assert too_big["action_type"] == "MARKDOWN"
    assert too_big["consolidation_target_store_id"] is None
    assert too_big["markdown_pct_bp"] == 3000

    absorbed = scenario["actions"]["0103"]
    assert absorbed["units_at_detection"] == 2
    assert absorbed["action_type"] == "CONSOLIDATION"
    assert absorbed["consolidation_target_store_id"] == scenario["stores"]["0102"]["id"]
    assert absorbed["markdown_pct_bp"] is None

    empty = scenario["actions"]["0104"]
    assert empty["units_at_detection"] == 0
    assert empty["action_type"] == "MARKDOWN"
    assert empty["consolidation_target_store_id"] is None
    assert empty["markdown_pct_bp"] == 4500


def test_executing_one_remedy_blocks_every_other_action_on_the_same_sku(
    api, allocation_manager_headers
):
    """PRD §3.9: "A `CONSOLIDATION` action creates a transfer recommendation with
    `source_reason` of `CONSOLIDATION`, `from_store_id` set to the action's own
    `store_id`, `to_store_id` set to the action's `consolidation_target_store_id`, `units`
    set to `units_at_detection`, `assortment_action_id` set to the action's identifier,
    and `proposed_by_user_id` set to the literal string `system`; that recommendation's
    `size_split`, `freight_cost_usd`, `handling_fee_usd`, `landed_cost_usd`, `benefit_usd`,
    `benefit_ratio_bp` and `expires_at` are all computed exactly as described in §3.8,
    using the consolidation branch of the size split, and if that split finds no candidate
    size the execution is refused with `ERR_TRANSFER_SIZE_INFEASIBLE`." And: "The SKU's
    `lifecycle_state` must be either `SIZE_OUT_WATCH` or `BROKEN`, or the refusal is
    `ERR_ITEM_LIFECYCLE_BLOCKED` — an `ACTIVE` SKU has nothing wrong with it, a
    `CONSOLIDATION_PENDING` SKU already has a remedy in flight, and a `MARKDOWN` SKU is
    frozen."

    The first execute puts the shared SKU into CONSOLIDATION_PENDING, and from there the
    two untouched actions in other stores are refused on the SKU's state, never their own.

    Design: Difficulty/cross_entity_state_dependency/assortment_action_execute_gated_by_the_shared_items_lifecycle_state
    """
    scenario = _three_pending_actions_on_one_sku()
    assert refresh_item(scenario)["lifecycle_state"] == "BROKEN"

    executed = validate_success(
        api.execute_assortment_action(
            scenario["actions"]["0103"]["id"], allocation_manager_headers
        )
    )
    assert executed["status"] == "EXECUTED"
    assert refresh_item(scenario)["lifecycle_state"] == "CONSOLIDATION_PENDING"

    created = api.list_transfer_recommendations(
        allocation_manager_headers,
        params={"assortment_action_id": scenario["actions"]["0103"]["id"], "limit": 100},
    ).json()["data"]
    assert len(created) == 1
    sweep_up = created[0]
    assert sweep_up["source_reason"] == "CONSOLIDATION"
    assert sweep_up["units"] == 2
    assert sweep_up["proposed_by_user_id"] == "system"
    assert sweep_up["from_store_id"] == scenario["stores"]["0103"]["id"]
    assert sweep_up["to_store_id"] == scenario["stores"]["0102"]["id"]
    assert units_by_size(sweep_up["size_split"]) == {"M": 1, "L": 1}

    for code in ("0101", "0104"):
        validate_error(
            api.execute_assortment_action(
                scenario["actions"][code]["id"], allocation_manager_headers
            ),
            ApiErrorId.ERR_ITEM_LIFECYCLE_BLOCKED.value,
            409,
        )
        blocked = validate_success(
            api.get_assortment_action(
                scenario["actions"][code]["id"], allocation_manager_headers
            )
        )
        assert blocked["status"] == "PENDING"


def test_cancelling_a_blocked_action_still_works_because_waiving_has_no_lifecycle_gate(
    api, allocation_manager_headers
):
    """PRD §3.9: "An `AllocationManager` may instead waive the remedy, taking the action
    `PENDING → CANCELLED`, which is terminal and advances `version` by one." PRD §3.3:
    "Second, if the SKU is `CONSOLIDATION_PENDING`, it returns to `ACTIVE` only when
    `broken_store_count` has reached 0, and otherwise stays where it is."

    Waiving the very action that execute refused proves the block lives on the SKU and
    not on the action: the cancel goes through while the SKU stays in
    CONSOLIDATION_PENDING with all three doors still broken.

    Design: Difficulty/cross_entity_state_dependency/assortment_action_execute_gated_by_the_shared_items_lifecycle_state
    """
    scenario = _three_pending_actions_on_one_sku()
    validate_success(
        api.execute_assortment_action(
            scenario["actions"]["0103"]["id"], allocation_manager_headers
        )
    )
    validate_error(
        api.execute_assortment_action(
            scenario["actions"]["0104"]["id"], allocation_manager_headers
        ),
        ApiErrorId.ERR_ITEM_LIFECYCLE_BLOCKED.value,
        409,
    )

    waived = validate_success(
        api.cancel_assortment_action(
            scenario["actions"]["0104"]["id"], allocation_manager_headers
        )
    )
    assert waived["status"] == "CANCELLED"

    item = refresh_item(scenario)
    assert item["lifecycle_state"] == "CONSOLIDATION_PENDING"
    assert item["broken_store_count"] == 3
