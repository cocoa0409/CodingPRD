"""The dispenser's availability and repair-posture dimensions move apart."""
from test_helpers import (
    TECHNICIAN_1,
    api_client,
    create_dispatch,
    ingest_and_classify_outage,
    make_field_technician_headers,
    post_progress,
    read_charging_port,
    read_part_reservation,
    read_station,
    reserve_parts,
    setup_spare_part_with_stock,
    setup_station,
    validate_success,
)


def _dispatch_with_one_reserved_dispenser_part():
    scenario = setup_station(
        clock="2026-06-14T08:00:00Z",
        site_code="HS-PD-1",
        station_code="ST-PD-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    port_id = scenario["ports"][0]["id"]

    part = setup_spare_part_with_stock(
        part_number="SP-PD-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=5
    )
    outage = ingest_and_classify_outage(
        port_id, "2026-06-14T08:00:00Z", fault_class="CRITICAL", fault_code="EVSE-CRIT-02"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-06-14T09:00:00Z",
        window_end_at="2026-06-14T19:00:00Z",
    )
    reservation = reserve_parts(dispatch["id"], part["id"], 2, part["version"])
    return {
        "station": scenario["station"],
        "port_id": port_id,
        "dispatch": dispatch,
        "reservation": reservation,
    }


def test_service_state_stays_pinned_while_the_repair_posture_advances_four_times():
    """One row, two dimensions, and only one of them moves.

    PRD §3.2: "A dispenser's `maintenance_state` evolves independently of its
    `service_state` and takes the values `NONE`, `DISPATCH_PENDING`,
    `UNDER_REPAIR`, and `AWAITING_PARTS`."  PRD §3.5 adds that arrival "drives the
    dispenser's repair posture `DISPATCH_PENDING → UNDER_REPAIR`" and
    "`RESUME_ONSITE` returns a held dispatch `PARTS_HOLD → ON_SITE` and drives the
    repair posture `AWAITING_PARTS → UNDER_REPAIR`".

    Design: Difficulty/non_linear_state_machine/charging_port_service_and_maintenance_dimensions_advance_independently
    """
    scenario = _dispatch_with_one_reserved_dispenser_part()
    port_id = scenario["port_id"]
    dispatch_id = scenario["dispatch"]["id"]
    technician_headers = make_field_technician_headers(TECHNICIAN_1)

    observations = []

    port = read_charging_port(port_id)
    observations.append(("after dispatch creation", port["service_state"], port["maintenance_state"]))
    assert port["maintenance_state"] == "DISPATCH_PENDING"

    post_progress(dispatch_id, "EN_ROUTE")
    post_progress(dispatch_id, "ARRIVE")
    port = read_charging_port(port_id)
    observations.append(("after ARRIVE", port["service_state"], port["maintenance_state"]))
    assert port["maintenance_state"] == "UNDER_REPAIR"

    validate_success(api_client.place_parts_hold(dispatch_id, technician_headers))
    port = read_charging_port(port_id)
    observations.append(("after parts-hold", port["service_state"], port["maintenance_state"]))
    assert port["maintenance_state"] == "AWAITING_PARTS"

    post_progress(dispatch_id, "RESUME_ONSITE")
    port = read_charging_port(port_id)
    observations.append(("after RESUME_ONSITE", port["service_state"], port["maintenance_state"]))
    assert port["maintenance_state"] == "UNDER_REPAIR"

    assert all(service == "OUT_OF_SERVICE" for _, service, _ in observations), (
        "the availability dimension must not move while the repair posture "
        f"advances four times: {observations}"
    )


def test_the_parts_hold_promise_is_built_from_the_reservations_on_this_dispatch():
    """A reserved dispenser part contributes no wait but eight hours of labour.

    PRD §3.6: "a backordered reservation contributes its part's `lead_time_days`
    converted to minutes at one thousand four hundred and forty minutes per day,
    while a reservation that is merely reserved contributes zero" and "The labour
    allowance is keyed on the most labour-intensive part class among the
    considered reservations: eight hours for `DISPENSER`".

    Design: Difficulty/non_linear_state_machine/charging_port_service_and_maintenance_dimensions_advance_independently
    """
    scenario = _dispatch_with_one_reserved_dispenser_part()
    dispatch_id = scenario["dispatch"]["id"]
    technician_headers = make_field_technician_headers(TECHNICIAN_1)

    post_progress(dispatch_id, "EN_ROUTE")
    post_progress(dispatch_id, "ARRIVE")
    held = validate_success(api_client.place_parts_hold(dispatch_id, technician_headers))

    assert held["total_hold_minutes"] == 480, (
        "a reserved line contributes a zero wait and the DISPENSER class "
        f"contributes 480 minutes of labour, got {held['total_hold_minutes']}"
    )

    resumed = post_progress(dispatch_id, "RESUME_ONSITE")
    assert resumed["state"] == "ON_SITE"
    assert read_part_reservation(scenario["reservation"]["id"])["state"] == "RESERVED", (
        "a parts hold does not dispose of the reservation it waited on"
    )

    station = read_station(scenario["station"]["id"])
    assert station["status"] == "SUSPENDED"
    assert station["suspension_source"] == "AUTOMATIC"
