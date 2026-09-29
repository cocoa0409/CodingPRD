"""The two conservation invariants of §2.9 and the compensating operations they rely on.

The receipt unit ledger survives a full commit / recall / re-commit cycle with no drift,
and the network on-hand sum survives approve / cancel and approve / dispatch / receive
without a single unit being created or destroyed.
"""
from test_helpers import (
    create_committed_run,
    lines_for_run,
    line_for_store,
    propose_transfer,
    receive_transfer,
    refresh_position,
    refresh_program,
    refresh_receipt,
    setup_network_with_staged_receipt,
    setup_rebalance_network,
    size_units,
    validate_success,
)


RECEIPT_SIZES_44 = [
    {"size_code": "S", "units": 8},
    {"size_code": "M", "units": 16},
    {"size_code": "L", "units": 14},
    {"size_code": "XL", "units": 6},
]


def _a_committed_forty_four_unit_spread(api, manager_headers):
    """A 44-unit receipt spread DEMAND_DRIVEN / FORWARD_LOOKING and committed across the
    four-store network. Nothing has shipped, so the run is still recallable."""
    scenario = setup_network_with_staged_receipt(
        units_received=44, size_received=RECEIPT_SIZES_44
    )
    scenario["run"] = create_committed_run(scenario["receipt"]["id"])
    return scenario


def _ledger(scenario):
    receipt = refresh_receipt(scenario)
    return (
        receipt["units_received"],
        receipt["units_committed"],
        receipt["units_unallocated"],
        receipt["status"],
    )


def test_the_commit_and_its_recall_move_the_same_forty_four_units(
    api, allocation_manager_headers
):
    """PRD §2.9: "After every run proposal, commit, recall or cancellation, and after every
    receipt closure or recount, `units_received` must equal `units_committed` plus
    `units_unallocated`, and `units_committed` must be at least 0 and at most
    `units_received`." PRD §3.7: "On success the run moves `COMMITTED → RECALLED`, which is
    terminal, and every line has its `units_allocated` reset to 0 and its
    `fulfillment_status` set to `RECALLED`."

    The commit reads 44 = 44 + 0 with the receipt ALLOCATED; the recall reads 44 = 0 + 44
    with the receipt back in ALLOCATING, and the program's roll-up follows both ways.

    Design: Difficulty/compensating_invariant/receipt_unit_ledger_survives_commit_recall_recommit_with_zero_drift
    """
    scenario = _a_committed_forty_four_unit_spread(api, allocation_manager_headers)

    assert _ledger(scenario) == (44, 44, 0, "ALLOCATED")
    opening_program = refresh_program(scenario)
    assert opening_program["total_units_received"] == 44
    assert opening_program["total_units_committed"] == 44
    assert opening_program["open_reserve_units"] == 0

    recalled = validate_success(
        api.recall_run(scenario["run"]["id"], allocation_manager_headers)
    )
    assert recalled["status"] == "RECALLED"

    lines = lines_for_run(scenario["run"]["id"])
    assert len(lines) == 3
    assert all(line["units_allocated"] == 0 for line in lines)
    assert all(line["fulfillment_status"] == "RECALLED" for line in lines)

    assert _ledger(scenario) == (44, 0, 44, "ALLOCATING")
    program = refresh_program(scenario)
    assert program["total_units_received"] == 44
    assert program["total_units_committed"] == 0
    assert program["open_reserve_units"] == 44


def test_a_recalled_run_is_terminal_so_its_replacement_supersedes_nothing(
    api, allocation_manager_headers
):
    """PRD §3.6: "If any sibling run on the same receipt is sitting in `DRAFT` or
    `PROPOSED`, that sibling is driven to `CANCELLED`, the new run's `supersedes_run_id` is
    set to the superseded sibling's identifier, and every allocation line of the superseded
    run is driven to `RECALLED`."

    The recalled run is neither DRAFT nor PROPOSED, so the second run opened against the
    same receipt has nothing to supersede and leaves the first exactly as the recall left it.

    Design: Difficulty/compensating_invariant/receipt_unit_ledger_survives_commit_recall_recommit_with_zero_drift
    """
    scenario = _a_committed_forty_four_unit_spread(api, allocation_manager_headers)
    validate_success(api.recall_run(scenario["run"]["id"], allocation_manager_headers))

    second = create_committed_run(scenario["receipt"]["id"])
    assert second["supersedes_run_id"] is None
    assert second["id"] != scenario["run"]["id"]

    first = validate_success(
        api.get_allocation_run(scenario["run"]["id"], allocation_manager_headers)
    )
    assert first["status"] == "RECALLED"


def test_the_second_spread_reproduces_the_first_because_nothing_moved(
    api, allocation_manager_headers
):
    """PRD §3.7: "Because a recall returns exactly the units its commit booked, repeated
    commit-and-recall cycles leave the receipt's `units_unallocated` where it started with
    zero drift."

    No unit left the DC and no position changed, so the identical inputs produce the
    identical spread: 26 units to 0101, 10 to 0103, 8 to 0104 and nothing to the overstocked
    0102.

    Design: Difficulty/compensating_invariant/receipt_unit_ledger_survives_commit_recall_recommit_with_zero_drift
    """
    scenario = _a_committed_forty_four_unit_spread(api, allocation_manager_headers)
    first_shape = {
        line["store_id"]: line["units_allocated"]
        for line in lines_for_run(scenario["run"]["id"])
    }
    validate_success(api.recall_run(scenario["run"]["id"], allocation_manager_headers))

    second = create_committed_run(scenario["receipt"]["id"])
    second_shape = {
        line["store_id"]: line["units_allocated"] for line in lines_for_run(second["id"])
    }

    assert second_shape == first_shape
    assert second_shape == {
        scenario["stores"]["0101"]["id"]: 26,
        scenario["stores"]["0103"]["id"]: 10,
        scenario["stores"]["0104"]["id"]: 8,
    }
    assert scenario["stores"]["0102"]["id"] not in second_shape


def test_the_ledger_lands_back_on_its_opening_reading_with_zero_drift(
    api, allocation_manager_headers
):
    """PRD §2.9: "A recall returns exactly the units its matching commit booked, so any
    number of commit-and-recall cycles leaves `units_unallocated` at its original value with
    no drift whatsoever." And: "`units_committed` is the sum of `units_allocated` over every
    allocation line whose owning run has reached `COMMITTED` and whose own
    `fulfillment_status` is `PENDING`, `SHIPPED` or `RECEIVED`; `units_unallocated` is
    `units_received` minus that committed total."

    Six lines exist at the end of the cycle but only the three belonging to the COMMITTED run
    count, so the ledger reads 44 = 44 + 0 again and `units_received` was never written by any
    of it.

    Design: Difficulty/compensating_invariant/receipt_unit_ledger_survives_commit_recall_recommit_with_zero_drift
    """
    scenario = _a_committed_forty_four_unit_spread(api, allocation_manager_headers)
    store_0101 = scenario["stores"]["0101"]["id"]
    stale_line_id = line_for_store(scenario["run"]["id"], store_0101)["id"]
    validate_success(api.recall_run(scenario["run"]["id"], allocation_manager_headers))

    second = create_committed_run(scenario["receipt"]["id"])

    assert _ledger(scenario) == (44, 44, 0, "ALLOCATED")
    assert refresh_program(scenario)["open_reserve_units"] == 0

    stale_line = validate_success(
        api.get_allocation_line(stale_line_id, allocation_manager_headers)
    )
    assert stale_line["units_allocated"] == 0
    assert stale_line["fulfillment_status"] == "RECALLED"

    fresh_line = line_for_store(second["id"], store_0101)
    assert fresh_line["units_allocated"] == 26
    assert fresh_line["fulfillment_status"] == "PENDING"

    assert len(lines_for_run(scenario["run"]["id"])) + len(lines_for_run(second["id"])) == 6


def _thirty_nine_units_and_one_proposed_rebalance():
    """Three positions of SKU-1001 holding 4 + 30 + 5 = 39 units with nothing in transit,
    a program whose freight worthiness gate is switched off, and a 6-unit REBALANCE
    proposed from the overstocked 0102 into the broken 0101."""
    scenario = setup_rebalance_network(program_overrides={"transfer_min_ratio_bp": 0})
    scenario["transfer"] = propose_transfer(scenario, units=6)
    return scenario


def _net(scenario):
    """The network on-hand sum of §2.9: on_hand_units plus in_transit_units over every
    position of the SKU."""
    total = 0
    for code in scenario["positions"]:
        position = refresh_position(scenario, code)
        assert sum(size_units(position, "size_on_hand").values()) == position["on_hand_units"]
        total += position["on_hand_units"] + position["in_transit_units"]
    return total


def test_approving_a_transfer_only_moves_units_from_available_into_reserved(
    api, allocation_manager_headers
):
    """PRD §2.9: "For a fixed SKU, take the sum over all of its positions of `on_hand_units`
    plus `in_transit_units`. Approving a transfer moves donor units from available into
    reserved and leaves that sum unchanged."

    The donor still physically holds all 30 units after the approval; only 6 of them stop
    being available.

    Design: Difficulty/compensating_invariant/network_on_hand_is_conserved_across_approve_cancel_and_approve_dispatch_receive
    """
    scenario = _thirty_nine_units_and_one_proposed_rebalance()
    assert _net(scenario) == 39

    validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )

    donor = refresh_position(scenario, "0102")
    assert donor["on_hand_units"] == 30
    assert donor["reserved_out_units"] == 6
    assert donor["available_units"] == 24
    assert _net(scenario) == 39


def test_cancelling_an_approved_transfer_is_the_exact_inverse_of_approving_it(
    api, allocation_manager_headers
):
    """PRD §2.9: "Cancelling an approved transfer releases the reservation and is likewise
    neutral." PRD §4: "APPROVED → CANCELLED (terminal); releases the donor reservation".

    Reservation released, availability restored, the band it lost recovered, and the network
    sum untouched at every step.

    Design: Difficulty/compensating_invariant/network_on_hand_is_conserved_across_approve_cancel_and_approve_dispatch_receive
    """
    scenario = _thirty_nine_units_and_one_proposed_rebalance()
    validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )

    cancelled = validate_success(
        api.cancel_transfer(
            scenario["transfer"]["id"],
            allocation_manager_headers,
            {"reason": "rolled into next weeks shipment"},
        )
    )
    assert cancelled["status"] == "CANCELLED"

    donor = refresh_position(scenario, "0102")
    assert donor["reserved_out_units"] == 0
    assert donor["available_units"] == 30
    assert donor["on_hand_units"] == 30
    assert donor["stock_status"] == "OVERSTOCK"
    assert _net(scenario) == 39


def test_a_replacement_transfer_supersedes_nothing_once_the_peer_is_cancelled(
    api, allocation_manager_headers
):
    """PRD §3.8: "If any recommendation on the identical donor-store, receiving-store and SKU
    triple is already sitting in `PROPOSED`, that peer is driven to `CANCELLED` with its
    `reject_reason` set to the string `superseded`, its `version` advances by one, and the new
    recommendation's `supersedes_recommendation_id` points at it."

    The peer reached CANCELLED through the cancel path rather than the supersede path, so the
    identical replacement — created against the donor position's refreshed version — points at
    nothing and the cancelled peer keeps its own reason.

    Design: Difficulty/compensating_invariant/network_on_hand_is_conserved_across_approve_cancel_and_approve_dispatch_receive
    """
    scenario = _thirty_nine_units_and_one_proposed_rebalance()
    validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )
    validate_success(
        api.cancel_transfer(
            scenario["transfer"]["id"],
            allocation_manager_headers,
            {"reason": "rolled into next weeks shipment"},
        )
    )

    replacement = propose_transfer(scenario, units=6)
    assert replacement["supersedes_recommendation_id"] is None
    assert replacement["status"] == "PROPOSED"

    peer = validate_success(
        api.get_transfer_recommendation(
            scenario["transfer"]["id"], allocation_manager_headers
        )
    )
    assert peer["status"] == "CANCELLED"
    assert peer["reject_reason"] != "superseded"
    assert _net(scenario) == 39


def test_dispatching_relocates_the_units_without_changing_the_network_sum(
    api, allocation_manager_headers
):
    """PRD §2.9: "Dispatching subtracts the units from the donor's `on_hand_units` and adds
    them to the receiver's `in_transit_units`, leaving the sum unchanged." And: "Independently
    of all that, for every position the sum of the `units` entries in `size_on_hand` must equal
    `on_hand_units` after every mutation."

    The 6 units leave the donor as 4 S and 2 XL — the sizes the receiver is out of — so the
    donor drops to 24 on hand while the receiver's on-hand count has not moved at all.

    Design: Difficulty/compensating_invariant/network_on_hand_is_conserved_across_approve_cancel_and_approve_dispatch_receive
    """
    scenario = _thirty_nine_units_and_one_proposed_rebalance()
    validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )

    dispatched = validate_success(
        api.dispatch_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )
    assert dispatched["status"] == "DISPATCHED"

    donor = refresh_position(scenario, "0102")
    assert donor["on_hand_units"] == 24
    assert size_units(donor, "size_on_hand") == {"S": 4, "M": 10, "L": 8, "XL": 2}

    receiver = refresh_position(scenario, "0101")
    assert receiver["on_hand_units"] == 4
    assert receiver["in_transit_units"] == 6

    assert _net(scenario) == 39


def test_receiving_converts_in_transit_into_on_hand_and_changes_nothing_else(
    api, allocation_manager_headers
):
    """PRD §2.9: "Receiving moves them from the receiver's `in_transit_units` into its
    `on_hand_units`, again unchanged." PRD §3.8: "The transfer's `units` move out of the
    receiving position's `in_transit_units` and into its `on_hand_units`, and the `size_split`
    entries are merged into its `size_on_hand`."

    The receiver ends on 10 units carrying the two sizes it was out of, in transit is back to
    zero, the third store was never touched, and the sum has been 39 after all seven calls.

    Design: Difficulty/compensating_invariant/network_on_hand_is_conserved_across_approve_cancel_and_approve_dispatch_receive
    """
    scenario = _thirty_nine_units_and_one_proposed_rebalance()
    validate_success(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )
    validate_success(
        api.dispatch_transfer(scenario["transfer"]["id"], allocation_manager_headers)
    )

    landed = receive_transfer(scenario, to_code="0101")
    assert landed["status"] == "RECEIVED"

    receiver = refresh_position(scenario, "0101")
    assert receiver["on_hand_units"] == 10
    assert receiver["in_transit_units"] == 0
    assert size_units(receiver, "size_on_hand") == {"S": 4, "M": 3, "L": 1, "XL": 2}

    untouched = refresh_position(scenario, "0103")
    assert untouched["on_hand_units"] == 5
    assert untouched["in_transit_units"] == 0
    assert untouched["reserved_out_units"] == 0

    assert refresh_position(scenario, "0102")["on_hand_units"] == 24
    assert _net(scenario) == 39
