"""Releasing a reservation restores the depot's unit conservation exactly."""
from test_helpers import (
    OPERATOR_HEADERS,
    api_client,
    assert_spare_part_unit_conservation,
    create_dispatch,
    ingest_and_classify_outage,
    read_part_reservation,
    read_spare_part,
    reserve_parts,
    setup_spare_part_with_stock,
    setup_station,
    validate_success,
)


def _dispatch_and_a_fully_stocked_dispenser_part():
    scenario = setup_station(
        clock="2026-06-16T08:00:00Z",
        site_code="HS-INV-1",
        station_code="ST-INV-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    port_id = scenario["ports"][0]["id"]
    outage = ingest_and_classify_outage(
        port_id, "2026-06-16T08:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-06-16T09:00:00Z",
        window_end_at="2026-06-16T19:00:00Z",
    )
    part = setup_spare_part_with_stock(
        part_number="SP-INV-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=10
    )
    return dispatch, part


def test_reserving_encumbers_stock_and_releasing_hands_it_back_exactly():
    """Ten units are ten units before, during and after the earmark.

    PRD §3.6: "`RELEASE` is the operator's compensating action and is permitted
    from either `RESERVED` or `BACKORDERED`.  From `RESERVED` it moves the
    reservation `RESERVED → RELEASED` and lowers `reserved_qty` by the quantity,
    restoring the unencumbered figure to its pre-reservation value".

    Design: Difficulty/compensating_invariant/part_reservation_release_restores_spare_part_unit_conservation
    """
    dispatch, part = _dispatch_and_a_fully_stocked_dispenser_part()

    assert part["on_hand_qty"] == 10
    assert part["reserved_qty"] == 0
    assert part["unencumbered_qty"] == 10
    assert_spare_part_unit_conservation(part)

    reservation = reserve_parts(dispatch["id"], part["id"], 4, part["version"])
    assert reservation["state"] == "RESERVED"
    assert reservation["qty"] == 4

    encumbered = read_spare_part(part["id"])
    assert encumbered["on_hand_qty"] == 10
    assert encumbered["reserved_qty"] == 4
    assert encumbered["unencumbered_qty"] == 6
    assert encumbered["backordered_qty"] == 0
    assert_spare_part_unit_conservation(encumbered)

    released = validate_success(
        api_client.dispose_part_reservation(reservation["id"], "RELEASE", OPERATOR_HEADERS)
    )
    assert released["state"] == "RELEASED"

    restored = read_spare_part(part["id"])
    assert restored["on_hand_qty"] == 10
    assert restored["reserved_qty"] == 0
    assert restored["unencumbered_qty"] == 10, (
        "the unencumbered figure must return to its exact pre-reservation value"
    )
    assert restored["backordered_qty"] == 0
    assert_spare_part_unit_conservation(restored)


def test_a_release_is_not_a_consumption_and_leaves_no_residue():
    """The lifetime consumption counter is the discriminator against CONSUME.

    PRD §3.6: `CONSUME` "lowers the part's `on_hand_qty` and `reserved_qty` each by
    the reservation's quantity, and raises `consumed_qty_lifetime` by the same
    quantity", whereas a `RELEASE` from `RESERVED` only "lowers `reserved_qty` by
    the quantity".

    Design: Difficulty/compensating_invariant/part_reservation_release_restores_spare_part_unit_conservation
    """
    dispatch, part = _dispatch_and_a_fully_stocked_dispenser_part()

    reservation = reserve_parts(dispatch["id"], part["id"], 4, part["version"])
    api_client.dispose_part_reservation(reservation["id"], "RELEASE", OPERATOR_HEADERS)

    assert read_part_reservation(reservation["id"])["state"] == "RELEASED"

    after = read_spare_part(part["id"])
    assert after["consumed_qty_lifetime"] == 0, (
        "a release must not count as a consumption"
    )
    assert after["on_hand_qty"] == 10, "no unit left the shelf"
