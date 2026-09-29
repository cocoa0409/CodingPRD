"""One request can move a chain of rows the caller never named.

Rejecting a deviation runs down the physical side of the house — deviation, cycle,
loads, pallets, cold room, room posture — and each link is caused only by the one
before it.  Booking a single load runs down the commercial side instead, ending in
a contract that has exhausted itself.
"""

from test_helpers import (
    adjudicate_deviation,
    book_load,
    list_chargeback_lines,
    read_cold_room,
    read_contract,
    read_cycle,
    read_load,
    read_lot,
    setup_spot_contract_world,
    setup_two_pallet_completed_deviated_cycle,
)


# --------------------------------------------------------------------------- #
# REJECT: deviation -> cycle -> loads -> pallets -> room -> posture
# --------------------------------------------------------------------------- #
def test_the_rejected_deviation_closes_itself_and_leaves_the_cost_with_the_facility():
    """A 170-second hold against a required 180 is a 5.56 percent shortfall and
    therefore CRITICAL, and an `EQUIP_` root cause charges the facility.

    PRD 3.7: "A `REJECT` advances the deviation `OPEN → ADJUDICATED_REJECT` and
    writes off the product."
    PRD 3.7: "That prefix carries commercial weight: a `root_cause_code` beginning
    with `PKG_` sets the deviation's `chargeback_party` to `CUSTOMER`, because the
    customer's package failed, and any other prefix sets it to `FACILITY`."

    Design: Difficulty/transitive_cascade/deviation_reject_cascades_to_cold_room_posture
    """
    world = setup_two_pallet_completed_deviated_cycle(actual_hold_seconds=170)
    assert world["deviation"]["status"] == "OPEN"

    deviation = adjudicate_deviation(
        world["deviation"]["id"], "REJECT", root_cause_code="EQUIP_PUMP_FAULT"
    )

    assert deviation["status"] == "ADJUDICATED_REJECT"
    assert deviation["severity"] == "CRITICAL"
    assert deviation["worst_shortfall_pct"] == 5.56
    assert deviation["chargeback_party"] == "FACILITY"
    assert list_chargeback_lines(customer_id=world["customer"]["id"]) == []


def test_the_rejection_dispositions_the_cycle_at_a_zero_fee_and_zeroes_both_loads():
    """The facility bills nothing for a destroyed run, and the zero overrides the
    allocation the waterfall would otherwise have produced on each load.

    PRD 3.7: "The cycle advances `COMPLETED_DEVIATED → DISPOSITIONED` with
    `actual_tolling_fee_cents` set to 0 and `dispositioned_at` stamped — the
    facility bills nothing for a run whose output it destroyed."
    PRD 3.7: "Every load moves `disposition_state` from `PENDING` to `REJECTED` with
    `allocated_fee_cents` set to 0, which overrides any allocation the normal
    waterfall would have produced."

    Design: Difficulty/transitive_cascade/deviation_reject_cascades_to_cold_room_posture
    """
    world = setup_two_pallet_completed_deviated_cycle(actual_hold_seconds=170)

    adjudicate_deviation(
        world["deviation"]["id"], "REJECT", root_cause_code="EQUIP_PUMP_FAULT"
    )
    cycle = read_cycle(world["cycle"]["id"])

    assert cycle["state"] == "DISPOSITIONED"
    assert cycle["actual_tolling_fee_cents"] == 0
    for load_key in ("load", "load2"):
        load = read_load(world[load_key]["id"])
        assert load["disposition_state"] == "REJECTED"
        assert load["allocated_fee_cents"] == 0


def test_both_pallets_are_written_off_on_both_state_dimensions():
    """Every treated unit moves into the disposed bucket and custody and release
    both advance to their terminal write-off states.

    PRD 3.7: "Every referenced pallet moves its `units_treated` into
    `units_disposed`, advances custody `TREATED → DISPOSED`, and advances its
    release dimension `ON_HOLD_FOR_TEST → REJECTED`."
    PRD 3.6: "Second, every loaded pallet advances `NOT_RELEASED →
    ON_HOLD_FOR_TEST` with `hold_reason` recorded as `CCP deviation`."

    Design: Difficulty/transitive_cascade/deviation_reject_cascades_to_cold_room_posture
    """
    world = setup_two_pallet_completed_deviated_cycle(actual_hold_seconds=170)
    assert world["lot"]["release_state"] == "ON_HOLD_FOR_TEST"

    adjudicate_deviation(
        world["deviation"]["id"], "REJECT", root_cause_code="EQUIP_PUMP_FAULT"
    )
    first = read_lot(world["lot"]["id"])
    second = read_lot(world["lot2"]["id"])

    assert first["custody_state"] == "DISPOSED"
    assert first["release_state"] == "REJECTED"
    assert first["units_disposed"] == 1000
    assert first["units_treated"] == 0
    assert second["custody_state"] == "DISPOSED"
    assert second["units_disposed"] == 800


def test_the_emptied_room_drops_to_zero_occupancy_and_flips_its_posture_back():
    """Losing both pallets takes the full room from AT_CAPACITY back to NORMAL,
    two links further down the chain than the request the client made.

    PRD 3.7: "Each disposed pallet lowers its cold room's `occupied_pallets` by one,
    and each room's `capacity_state` is then recomputed, flipping `AT_CAPACITY →
    NORMAL` once `occupied_pallets` has fallen below `capacity_pallets`."
    PRD 2.9: "A single request routinely mutates a chain of rows — a pallet's
    custody state moves, which changes a cold room's `occupied_pallets`, which flips
    that room's derived `capacity_state`; a load is created, which changes a
    contract's `reserved_slots`, which drops `available_slots`, which flips the
    contract's `status`."

    Design: Difficulty/transitive_cascade/deviation_reject_cascades_to_cold_room_posture
    """
    world = setup_two_pallet_completed_deviated_cycle(actual_hold_seconds=170)
    before = read_cold_room(world["room"]["id"])
    assert before["occupied_pallets"] == 2
    assert before["capacity_state"] == "AT_CAPACITY"

    adjudicate_deviation(
        world["deviation"]["id"], "REJECT", root_cause_code="EQUIP_PUMP_FAULT"
    )
    room = read_cold_room(world["room"]["id"])

    assert room["occupied_pallets"] == 0
    assert room["capacity_state"] == "NORMAL"


# --------------------------------------------------------------------------- #
# booking a load: load -> cycle -> slot ledger -> contract status
# --------------------------------------------------------------------------- #
def test_the_new_load_opens_pending_on_both_of_its_own_dimensions():
    """The first link of the commercial chain is the load's own opening posture.

    PRD 3.5: "A successful booking creates the load with `disposition_state` of
    `PENDING`, `inspection_state` of `PENDING_INSPECTION`, `allocated_fee_cents`
    null, `units_inspected`, `leaker_units`, `leaker_ppm` and `chargeback_party` all
    null, and `chargeback_cents` at 0."

    Design: Difficulty/transitive_cascade/load_create_cascades_contract_to_exhausted
    """
    world = setup_spot_contract_world()

    load = book_load(
        world["cycle"]["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=1000,
        expected_cycle_version=world["cycle"]["version"],
    )

    assert load["disposition_state"] == "PENDING"
    assert load["inspection_state"] == "PENDING_INSPECTION"
    assert load["allocated_fee_cents"] is None
    assert load["chargeback_cents"] == 0


def test_the_booking_moves_the_cycle_to_loaded_and_rewrites_its_estimate():
    """The second link: the cycle leaves SCHEDULED and re-prices itself under the
    ESTIMATED variant at the new half-full utilisation.

    PRD 3.5: "The first booking advances the cycle `SCHEDULED → LOADED`; every later
    booking is a self-loop on `LOADED → LOADED`, so a chamber routinely co-mingles
    loads from several customers unless the family forbids it."
    PRD 3.5: "The cycle's `baskets_used_total`, `utilization_pct`,
    `estimated_cycle_seconds`, `estimated_tolling_fee_cents` and `scheduled_end` are
    all recomputed under the ESTIMATED variant, so each booking tightens the
    estimate as the chamber fills."

    Design: Difficulty/transitive_cascade/load_create_cascades_contract_to_exhausted
    """
    world = setup_spot_contract_world()
    assert world["cycle"]["state"] == "SCHEDULED"

    book_load(
        world["cycle"]["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=1000,
        expected_cycle_version=world["cycle"]["version"],
    )
    cycle = read_cycle(world["cycle"]["id"])

    assert cycle["state"] == "LOADED"
    assert cycle["estimated_tolling_fee_cents"] == 11400


def test_the_single_slot_contract_reserves_its_last_slot_and_exhausts_itself():
    """Links three and four: the ledger moves the only slot into `reserved_slots`,
    which empties `available_slots`, which flips the contract's status.

    PRD 3.5: "On the contract side, `reserved_slots` rises by one, which drops
    `available_slots` by one, and when the recomputed `available_slots` reaches zero
    the contract advances `ACTIVE → EXHAUSTED`."
    PRD 3.3: "Each time a load is booked against it the slot ledger of §2.9 is
    recomputed, and when the recomputed `available_slots` reaches exactly zero the
    contract advances `ACTIVE → EXHAUSTED`, incrementing its `version`."

    Design: Difficulty/transitive_cascade/load_create_cascades_contract_to_exhausted
    """
    world = setup_spot_contract_world()
    assert world["contract"]["status"] == "ACTIVE"
    assert world["contract"]["available_slots"] == 1

    book_load(
        world["cycle"]["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=1000,
        expected_cycle_version=world["cycle"]["version"],
    )
    contract = read_contract(world["contract"]["id"])

    assert contract["reserved_slots"] == 1
    assert contract["consumed_slots"] == 0
    assert contract["available_slots"] == 0
    assert contract["status"] == "EXHAUSTED"
