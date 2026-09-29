"""Reopening a resolved fault sends the outage back and unwinds the station ledger."""
from test_helpers import (
    OPERATOR_HEADERS,
    api_client,
    assert_instant_equals,
    read_charging_port,
    read_dispatch,
    read_outage_event,
    read_station,
    resolution_review_payload,
    run_repair_cycle,
    setup_station,
    validate_success,
)


def test_reopening_a_resolved_outage_clears_it_and_reverses_the_station_ledger():
    """A ledger that only ever accumulates leaves 720 minutes behind.

    PRD §3.4: "An `outcome` of `REOPEN`, available to a `NetworkOperator`, sends
    it `RESOLVED → CLASSIFIED`, clears `cleared_at` back to null, reverses the
    station's gross and billable downtime figures".  PRD §3.4 also fixes what the
    reopen must not disturb: "`MINOR` and `INFORMATIONAL` faults deliberately
    leave the dispenser in service".  PRD §3.5 lists cancellation as the only
    other exit from a live dispatch and makes `COMPLETED` terminal.

    Design: Corner/state_machines/resolution_review_reopen_returns_resolved_outage_to_classified_and_reverses_the_ledger
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    cycle = run_repair_cycle(
        port_id,
        detected_at="2026-08-01T00:00:00Z",
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T23:00:00Z",
        completed_at="2026-08-01T12:00:00Z",
        fault_class="MINOR",
        fault_code="OCPP-MIN-01",
    )
    outage_id = cycle["outage"]["id"]
    dispatch_id = cycle["dispatch"]["id"]

    resolved = read_outage_event(outage_id)
    assert resolved["state"] == "RESOLVED"
    assert_instant_equals(resolved["cleared_at"], "2026-08-01T12:00:00Z", "cleared_at")

    before = read_station(station_id)
    assert before["gross_downtime_minutes_lifetime"] == 720, (
        "midnight to noon is 720 whole minutes of closed downtime"
    )
    assert before["billable_downtime_minutes_lifetime"] == 720

    response = api_client.submit_resolution_review(
        outage_id, resolution_review_payload("REOPEN"), OPERATOR_HEADERS
    )
    data = validate_success(response, 200)

    assert data["state"] == "CLASSIFIED"
    assert data["cleared_at"] is None

    after = read_station(station_id)
    assert after["gross_downtime_minutes_lifetime"] == 0, (
        "the reopened outage has no cleared_at, so it contributes nothing"
    )
    assert after["excluded_downtime_minutes_lifetime"] == 0
    assert after["billable_downtime_minutes_lifetime"] == 0

    assert read_dispatch(dispatch_id)["state"] == "COMPLETED", (
        "the completed dispatch is not un-completed by the reopen"
    )
    assert read_charging_port(port_id)["service_state"] == "IN_SERVICE", (
        "a MINOR fault never took the dispenser out of service"
    )
