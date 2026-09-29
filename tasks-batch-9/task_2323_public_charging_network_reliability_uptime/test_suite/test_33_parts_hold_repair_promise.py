"""The parts-hold promise: expedite decided once, on the pre-discount total."""
from test_helpers import (
    TECHNICIAN_HEADERS,
    api_client,
    assert_instant_equals,
    create_dispatch,
    drive_dispatch_to_on_site,
    ingest_and_classify_outage,
    read_charging_port,
    read_spare_part,
    reserve_parts,
    set_clock,
    setup_operational_station,
    setup_spare_part_with_stock,
    validate_success,
)


def test_a_backordered_dispenser_line_halves_only_its_wait_and_keeps_the_expedite():
    """Re-testing eligibility after the discount would restore the full 4800 minutes.

    PRD §3.6: "a backordered reservation contributes its part's `lead_time_days`
    converted to minutes at one thousand four hundred and forty minutes per day";
    "The labour allowance is keyed on the most labour-intensive part class among the
    considered reservations: eight hours for `DISPENSER`"; "The pre-expedite total is
    the raw parts wait plus the labour allowance."; "Expedite eligibility is decided
    **once**, on that pre-expedite total, and strictly: the dispatch qualifies for
    expediting only when the pre-expedite total is *greater than* two days.  It is
    deliberately not re-tested after the discount is applied, even though the
    discounted total frequently falls back below that trigger"; "When the dispatch
    qualifies, the raw parts wait — and only the wait component, never the labour —
    is halved, with the halved figure rounded **up** to a whole minute."; and
    "`total_hold_minutes` is the final parts wait plus the labour allowance, and
    `promised_repair_at` is the logical clock's current reading advanced by that many
    minutes."

    Design: Corner/calculations/parts_hold_expedite_eligibility_is_decided_once_on_the_pre_discount_total
    """
    scenario = setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        power_class="DCFC_150",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    port_id = scenario["ports"][0]["id"]

    part = setup_spare_part_with_stock(
        part_number="SP-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=0
    )

    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T23:00:00Z",
    )
    reservation = reserve_parts(dispatch["id"], part["id"], 1, part["version"])
    assert reservation["state"] == "BACKORDERED", "the depot had nothing unencumbered"
    assert read_spare_part(part["id"])["backordered_qty"] == 1

    drive_dispatch_to_on_site(dispatch["id"])
    set_clock("2026-08-01T12:00:00Z")

    data = validate_success(api_client.place_parts_hold(dispatch["id"], TECHNICIAN_HEADERS))

    assert data["state"] == "PARTS_HOLD"
    assert data["total_hold_minutes"] == 2640, (
        "a 4320-minute wait halved to 2160 plus the 480-minute dispenser labour"
    )
    assert_instant_equals(
        data["promised_repair_at"], "2026-08-03T08:00:00Z", "promised_repair_at"
    )

    assert read_charging_port(port_id)["maintenance_state"] == "AWAITING_PARTS"
