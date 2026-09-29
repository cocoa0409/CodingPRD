"""Dispatch windows collide under the half-open convention, so they may touch."""
from test_helpers import (
    OPERATOR_HEADERS,
    TECHNICIAN_2,
    TECHNICIAN_3,
    ApiErrorId,
    api_client,
    create_dispatch,
    create_maintenance_dispatch_payload,
    ingest_and_classify_outage,
    read_charging_port,
    read_outage_event,
    set_clock,
    setup_station,
    validate_error,
    validate_paginated,
    validate_success,
)


def _one_dispenser_carrying_three_classified_minor_faults():
    """One contested dispenser.  MINOR faults do not take it out of service, so
    the station stays OPERATIONAL while three dispatches compete for the day."""
    scenario = setup_station(
        clock="2026-06-10T07:00:00Z",
        site_code="HS-OV-1",
        station_code="ST-OV-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    set_clock("2026-06-10T09:00:00Z")
    port_id = scenario["ports"][0]["id"]
    outages = [
        ingest_and_classify_outage(
            port_id,
            "2026-06-10T08:00:00Z",
            fault_class="MINOR",
            fault_code=fault_code,
        )
        for fault_code in ("OCPP-MIN-A1", "OCPP-MIN-A2", "OCPP-MIN-A3")
    ]
    return port_id, outages


def _dispatch_ten_to_twelve(port_id, outages):
    return create_dispatch(
        outages[0]["id"],
        port_id,
        window_start_at="2026-06-10T10:00:00Z",
        window_end_at="2026-06-10T12:00:00Z",
    )


def _dispatch_twelve_to_fourteen_response(port_id, outages):
    """Starts at the exact instant the first window ends."""
    return api_client.create_maintenance_dispatch(
        create_maintenance_dispatch_payload(
            outages[1]["id"],
            port_id,
            TECHNICIAN_2,
            "2026-06-10T12:00:00Z",
            "2026-06-10T14:00:00Z",
        ),
        OPERATOR_HEADERS,
    )


def _dispatch_eleven_to_thirteen_response(port_id, outages):
    """Straddles the shared endpoint, so it genuinely intersects both windows."""
    return api_client.create_maintenance_dispatch(
        create_maintenance_dispatch_payload(
            outages[2]["id"],
            port_id,
            TECHNICIAN_3,
            "2026-06-10T11:00:00Z",
            "2026-06-10T13:00:00Z",
        ),
        OPERATOR_HEADERS,
    )


def test_a_window_starting_where_another_ends_is_accepted():
    """The upper endpoint is exclusive, so adjacency is not collision.

    PRD §3.5: "the window must not collide, under the half-open convention of
    §2.10, with the window of any other dispatch on the same dispenser that is
    still live ... while windows that merely touch at an endpoint are accepted."

    Design: Difficulty/resource_temporal_overlap/dispatch_windows_are_half_open_per_port_so_touching_endpoints_are_allowed
    """
    port_id, outages = _one_dispenser_carrying_three_classified_minor_faults()

    first = _dispatch_ten_to_twelve(port_id, outages)
    assert first["state"] == "CREATED"

    second = validate_success(
        _dispatch_twelve_to_fourteen_response(port_id, outages), 201
    )
    assert second["state"] == "CREATED", (
        "12:00 is the first window's exclusive end, so the second window is free"
    )


def test_a_window_straddling_the_shared_endpoint_is_rejected():
    """A genuine intersection is still a collision, and it transitions nothing.

    PRD §3.5: "a genuine intersection is rejected with
    `ERR_DISPATCH_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/dispatch_windows_are_half_open_per_port_so_touching_endpoints_are_allowed
    """
    port_id, outages = _one_dispenser_carrying_three_classified_minor_faults()

    _dispatch_ten_to_twelve(port_id, outages)
    _dispatch_twelve_to_fourteen_response(port_id, outages)

    response = _dispatch_eleven_to_thirteen_response(port_id, outages)

    validate_error(response, ApiErrorId.ERR_DISPATCH_WINDOW_OVERLAP, 409)
    assert read_outage_event(outages[2]["id"])["state"] == "CLASSIFIED", (
        "the rejected dispatch must produce no transition on its outage"
    )


def test_only_the_two_accepted_windows_survive_on_the_dispenser():
    """The dispenser ends the day with two live dispatches and one repair posture.

    PRD §3.5: dispatch creation moves "the dispenser's repair posture ... `NONE →
    DISPATCH_PENDING` under the aggregate rule of §3.2".  PRD §3.2: "When a
    *further* dispatch is created for a dispenser already at `DISPATCH_PENDING`
    ... the dimension is left exactly where it is", because "Multiple live
    dispatches on one dispenser are therefore legitimate".

    Design: Difficulty/resource_temporal_overlap/dispatch_windows_are_half_open_per_port_so_touching_endpoints_are_allowed
    """
    port_id, outages = _one_dispenser_carrying_three_classified_minor_faults()

    _dispatch_ten_to_twelve(port_id, outages)
    _dispatch_twelve_to_fourteen_response(port_id, outages)
    _dispatch_eleven_to_thirteen_response(port_id, outages)

    rows, _meta = validate_paginated(
        api_client.list_maintenance_dispatches(OPERATOR_HEADERS, params={"port_id": port_id})
    )
    assert len(rows) == 2, f"exactly the two accepted dispatches should exist, got {len(rows)}"

    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING"
