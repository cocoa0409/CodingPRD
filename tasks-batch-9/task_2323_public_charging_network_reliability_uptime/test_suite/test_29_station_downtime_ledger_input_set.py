"""The lifetime ledger keeps retired history and ignores everything still open."""
from test_helpers import (
    OPERATOR_HEADERS,
    api_client,
    ingest_outage,
    read_charging_port,
    read_outage_event,
    read_station,
    run_repair_cycle,
    set_clock,
    setup_station,
    validate_success,
)


def test_retiring_the_only_dispenser_leaves_its_closed_downtime_on_the_station_ledger():
    """Dropping retired dispensers from the ledger would erase 390 real minutes.

    PRD §3.4: "The ledger set is every outage on every dispenser of the station —
    including dispensers that have since been retired — restricted to outages that
    actually have a `cleared_at`; an outage still open contributes nothing to any of
    the three figures.  Each member of that set contributes its closed duration, the
    elapsed time from `detected_at` to `cleared_at` in whole minutes with any
    partial minute discarded."  PRD §3.2 makes retirement recompute the rest:
    retirement "recomputes the station's non-retired port count,
    `installed_power_kw` and `payment_interop_score`", and "If the station has no
    scored dispensers at all, the score is `0.00`".

    Design: Corner/calculations/station_downtime_ledger_counts_retired_port_history_and_ignores_open_outages
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

    run_repair_cycle(
        port_id,
        detected_at="2026-08-01T00:00:00Z",
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T23:00:00Z",
        completed_at="2026-08-01T06:30:00Z",
        fault_class="MINOR",
        fault_code="OCPP-MIN-01",
    )

    set_clock("2026-08-01T07:00:00Z")
    still_open = ingest_outage(
        port_id, "2026-08-01T07:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-02"
    )

    before = read_station(station_id)
    assert before["gross_downtime_minutes_lifetime"] == 390, (
        "midnight to 06:30 is 390 whole minutes, and 390 is not a whole number of hours"
    )
    assert before["excluded_downtime_minutes_lifetime"] == 0
    assert before["billable_downtime_minutes_lifetime"] == 390

    data = validate_success(api_client.retire_charging_port(port_id, OPERATOR_HEADERS))
    assert data["service_state"] == "RETIRED"
    assert read_charging_port(port_id)["service_state"] == "RETIRED"

    after = read_station(station_id)
    assert after["gross_downtime_minutes_lifetime"] == 390, (
        "the retired dispenser's history stays in the ledger set"
    )
    assert after["excluded_downtime_minutes_lifetime"] == 0
    assert after["billable_downtime_minutes_lifetime"] == 390

    assert read_outage_event(still_open["id"])["cleared_at"] is None, (
        "the open outage contributed nothing before or after the retirement"
    )

    assert after["commissioned_port_count"] == 0
    assert float(after["payment_interop_score"]) == 0.00, "no scored dispensers remain"
