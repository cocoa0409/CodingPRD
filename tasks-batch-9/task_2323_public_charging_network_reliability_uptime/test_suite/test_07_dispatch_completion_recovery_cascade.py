"""Dispatch completion runs the recovery cascade four levels upward."""
from test_helpers import (
    assert_instant_equals,
    assert_station_ledger_consistent,
    complete_dispatch,
    create_dispatch,
    drive_dispatch_to_on_site,
    ingest_and_classify_outage,
    read_charging_port,
    read_outage_event,
    read_station,
    set_clock,
    setup_station,
)


def _dispatch_on_site_awaiting_completion():
    scenario = setup_station(
        clock="2026-06-12T08:00:00Z",
        site_code="HS-C4-1",
        station_code="ST-C4-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    port_id = scenario["ports"][0]["id"]

    outage = ingest_and_classify_outage(
        port_id, "2026-06-12T08:00:00Z", fault_class="CRITICAL", fault_code="EVSE-CRIT-02"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-06-12T09:00:00Z",
        window_end_at="2026-06-12T15:00:00Z",
    )
    drive_dispatch_to_on_site(dispatch["id"])
    set_clock("2026-06-12T14:00:00Z")
    return {
        "station_id": scenario["station"]["id"],
        "port_id": port_id,
        "outage_id": outage["id"],
        "dispatch_id": dispatch["id"],
    }


def test_completion_cascades_through_outage_dispenser_and_station():
    """Each link is caused strictly by the one above it.

    PRD §2.6: "Completing a repair closes its outage; closing the last unresolved
    outage on a dispenser returns that dispenser to service; returning the last
    out-of-service dispenser to service lifts an automatic station suspension."

    Design: Difficulty/transitive_cascade/dispatch_completion_cascades_four_levels_dispatch_outage_port_station
    """
    scenario = _dispatch_on_site_awaiting_completion()

    completed = complete_dispatch(scenario["dispatch_id"])

    assert completed["state"] == "COMPLETED"

    outage = read_outage_event(scenario["outage_id"])
    assert outage["state"] == "RESOLVED"
    assert_instant_equals(outage["cleared_at"], "2026-06-12T14:00:00Z", "cleared_at")

    port = read_charging_port(scenario["port_id"])
    assert port["service_state"] == "IN_SERVICE"
    assert port["maintenance_state"] == "NONE"

    station = read_station(scenario["station_id"])
    assert station["out_of_service_port_count"] == 0
    assert station["status"] == "OPERATIONAL"
    assert station["suspension_source"] == "NONE"


def test_completion_settles_the_response_outcome_and_the_downtime_ledger():
    """The arrival verdict and the ledger both close out with the repair.

    PRD §3.5: "`ARRIVE` ... settles `response_met` once and for all: it is true
    when `arrived_at` is at or before `response_deadline_at` and false otherwise".
    Completion then means "the station's gross and billable lifetime downtime
    figures are recomputed."

    Design: Difficulty/transitive_cascade/dispatch_completion_cascades_four_levels_dispatch_outage_port_station
    """
    scenario = _dispatch_on_site_awaiting_completion()

    completed = complete_dispatch(scenario["dispatch_id"])

    assert_instant_equals(
        completed["response_deadline_at"],
        "2026-06-12T11:00:00Z",
        "response_deadline_at (240 CRITICAL minutes at three quarters for DCFC_150)",
    )
    assert completed["response_met"] is True, (
        "arrival at 2026-06-12T08:00:00Z precedes the 11:00 deadline"
    )

    station = read_station(scenario["station_id"])
    assert station["gross_downtime_minutes_lifetime"] == 360
    assert station["excluded_downtime_minutes_lifetime"] == 0
    assert station["billable_downtime_minutes_lifetime"] == 360
    assert_station_ledger_consistent(station)
