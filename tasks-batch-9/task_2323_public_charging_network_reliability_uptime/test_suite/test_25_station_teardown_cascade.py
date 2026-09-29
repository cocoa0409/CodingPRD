"""One status transition fans out across dispensers, outages, dispatches and stock."""
from test_helpers import (
    OPERATOR_HEADERS,
    api_client,
    assert_instant_equals,
    assert_spare_part_unit_conservation,
    create_dispatch,
    ingest_and_classify_outage,
    read_charging_port,
    read_dispatch,
    read_host_site,
    read_outage_event,
    read_part_reservation,
    read_spare_part,
    read_station,
    reserve_parts,
    setup_operational_station,
    setup_spare_part_with_stock,
    validate_success,
)


def test_decommissioning_retires_ports_excludes_outages_and_frees_depot_stock():
    """Cancelling the dispatch while leaving stock encumbered is not enough.

    PRD §3.3 teardown: "Every dispenser on the station whose `service_state` is
    `IN_SERVICE` or `OUT_OF_SERVICE` moves to `RETIRED`, with `retired_at` stamped
    from the logical clock and `maintenance_state` forced to `NONE`"; "every
    outage on them sitting in `DETECTED`, `CLASSIFIED`, `DISPATCHED`, or
    `EXCLUSION_REVIEW` moves to `EXCLUDED`.  Its `excluded_cause_claim` is forced
    to `HOST_SITE_CLOSURE`, its `excluded_at` is stamped from the logical clock,
    its `cleared_at` is stamped from the logical clock if and only if it was still
    null, and `pre_exclusion_state` records the state it left ... a state left of
    `DISPATCHED` is recorded as `RESOLVED`"; and "every dispatch on them sitting
    in `CREATED`, `EN_ROUTE`, `ON_SITE`, or `PARTS_HOLD` moves to `CANCELLED`, and
    each of that dispatch's part reservations sitting in `RESERVED` or
    `BACKORDERED` moves to `RELEASED`, restoring the affected spare part's
    reserved and backordered quantities and therefore its unencumbered quantity."
    The teardown then "decrements the host site's station count".

    Design: Corner/state_machines/station_decommission_cascade_retires_ports_excludes_open_outages_and_cancels_dispatches
    """
    scenario = setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        power_class="DCFC_150",
        port_count=2,
        committed_service_capacity_kw=800.00,
    )
    host_site_id = scenario["host_site"]["id"]
    station_id = scenario["station"]["id"]
    first_port_id = scenario["ports"][0]["id"]
    second_port_id = scenario["ports"][1]["id"]

    part = setup_spare_part_with_stock(
        part_number="SP-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=10
    )

    outage = ingest_and_classify_outage(
        first_port_id, "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        first_port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
    )
    reservation = reserve_parts(dispatch["id"], part["id"], 3, part["version"])
    assert reservation["state"] == "RESERVED"
    assert read_spare_part(part["id"])["unencumbered_qty"] == 7

    before = read_station(station_id)
    assert before["status"] == "SUSPENDED"
    assert before["suspension_source"] == "AUTOMATIC"
    assert read_host_site(host_site_id)["station_count"] == 1

    data = validate_success(
        api_client.transition_station_status(station_id, "DECOMMISSIONED", OPERATOR_HEADERS)
    )
    assert data["status"] == "DECOMMISSIONED"

    for port_id in (first_port_id, second_port_id):
        port_after = read_charging_port(port_id)
        assert port_after["service_state"] == "RETIRED", f"{port_id} should have retired"
        assert_instant_equals(port_after["retired_at"], "2026-08-01T00:00:00Z", "retired_at")
    assert read_charging_port(first_port_id)["maintenance_state"] == "NONE", (
        "the DISPATCH_PENDING posture cleared with the cancelled dispatch"
    )

    outage_after = read_outage_event(outage["id"])
    assert outage_after["state"] == "EXCLUDED"
    assert outage_after["excluded_cause_claim"] == "HOST_SITE_CLOSURE"
    assert_instant_equals(outage_after["excluded_at"], "2026-08-01T00:00:00Z", "excluded_at")
    assert_instant_equals(outage_after["cleared_at"], "2026-08-01T00:00:00Z", "cleared_at")
    assert outage_after["pre_exclusion_state"] == "RESOLVED", (
        "a state left of DISPATCHED is normalised to RESOLVED"
    )

    assert read_dispatch(dispatch["id"])["state"] == "CANCELLED"
    assert read_part_reservation(reservation["id"])["state"] == "RELEASED"

    part_after = read_spare_part(part["id"])
    assert part_after["on_hand_qty"] == 10
    assert part_after["reserved_qty"] == 0
    assert part_after["unencumbered_qty"] == 10
    assert part_after["consumed_qty_lifetime"] == 0, "a teardown release is not a consumption"
    assert_spare_part_unit_conservation(part_after)

    assert read_host_site(host_site_id)["station_count"] == 0

    station_after = read_station(station_id)
    assert station_after["commissioned_port_count"] == 0
    assert station_after["out_of_service_port_count"] == 0
    assert float(station_after["installed_power_kw"]) == 0.00
    assert station_after["suspension_source"] == "NONE"
