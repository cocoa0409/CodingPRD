"""Which dispensers and which minutes actually reach an uptime report."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    api_client,
    declare_reporting_period,
    ingest_outage,
    install_charging_port,
    read_outage_event,
    read_station,
    run_repair_cycle,
    set_clock,
    setup_station,
    validate_success,
)


def test_a_retired_and_a_late_installed_dispenser_leave_both_the_denominator_and_the_attribution():
    """Filtering the denominator but attributing every outage on the station is wrong.

    PRD §3.7: "A dispenser is *eligible* for the report when it belongs to the
    report's station, its own `created_at` is at or before `period_start`, and its
    `service_state` is `IN_SERVICE` or `OUT_OF_SERVICE`.  `eligible_port_count` is
    the number of such dispensers, and `total_port_minutes` — the report's total
    exposure — is that count multiplied by the period length.  A dispenser
    installed after `period_start`, or already retired, contributes no port-minutes
    at all, and its outages are dropped from the attribution as well."

    Design: Corner/calculations/uptime_denominator_drops_late_created_and_retired_ports_and_their_outages
    """
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=800.00,
        power_class="DCFC_150",
        declared_port_count=1,
        ports=[
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-1"),
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-2", connector_type="NACS"),
        ],
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    retired_port_id = scenario["ports"][1]["id"]

    retired = validate_success(
        api_client.retire_charging_port(retired_port_id, OPERATOR_HEADERS)
    )
    assert retired["service_state"] == "RETIRED"

    set_clock("2026-06-15T00:00:00Z")
    late_port = install_charging_port(
        station_id,
        "DS-3",
        connector_type="CCS1",
        rated_power_kw=150.00,
        contactless_enabled=True,
        plug_and_charge_enabled=True,
        price_display_verified=True,
        roaming_ocpi_version="V2_2_1",
    )

    set_clock("2026-06-20T00:00:00Z")
    late_outage = ingest_outage(
        late_port["id"],
        "2026-06-20T00:00:00Z",
        fault_class="MINOR",
        fault_code="OCPP-MIN-01",
    )

    set_clock("2026-07-15T00:00:00Z")
    report = declare_reporting_period(
        station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )

    data = validate_success(
        api_client.compute_provisional_uptime(report["id"], OPERATOR_HEADERS)
    )

    assert data["eligible_port_count"] == 1, (
        "the retired dispenser and the one installed mid-period are both out"
    )
    assert data["total_port_minutes"] == 43200, (
        "one eligible dispenser across the 43200 minutes of June"
    )
    assert data["excluded_minutes"] == 0
    assert data["billable_downtime_minutes"] == 0, (
        "the open outage sits on an ineligible dispenser, so it is not attributed"
    )
    assert float(data["uptime_pct"]) == 100.00
    assert data["methodology"] == "PROVISIONAL"

    outage_after = read_outage_event(late_outage["id"])
    assert outage_after["state"] == "DETECTED"
    assert outage_after["cleared_at"] is None, (
        "the outage still exists and is simply not attributable"
    )


def test_a_straddling_outage_and_an_open_one_are_both_clipped_to_the_period():
    """Charging the whole span of each outage understates uptime badly.

    PRD §3.7: "Each attributed outage contributes the portion of its downtime that
    falls inside the period: the overlap starts at the later of `detected_at` and
    `period_start`, ends at the earlier of `period_end` and either `cleared_at` or
    — for an outage still open — `period_end` itself, and the elapsed time between
    those two instants is taken in whole minutes with any partial minute discarded
    and with a negative result treated as zero.  An uncleared outage is therefore
    charged right through to the end of the period."  PRD §3.4 keeps the lifetime
    ledger on a different footing: it is "restricted to outages that actually have
    a `cleared_at`" and each member "contributes its closed duration, the elapsed
    time from `detected_at` to `cleared_at` in whole minutes".

    Design: Corner/calculations/uptime_clips_straddling_and_uncleared_outages_to_the_reporting_period
    """
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    set_clock("2026-05-30T00:00:00Z")
    run_repair_cycle(
        port_id,
        detected_at="2026-05-30T00:00:00Z",
        window_start_at="2026-05-30T01:00:00Z",
        window_end_at="2026-06-03T00:00:00Z",
        completed_at="2026-06-02T00:00:00Z",
        fault_class="MINOR",
        fault_code="OCPP-MIN-01",
    )

    set_clock("2026-06-29T00:00:00Z")
    still_open = ingest_outage(
        port_id, "2026-06-29T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-02"
    )

    set_clock("2026-07-15T00:00:00Z")
    report = declare_reporting_period(
        station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )

    data = validate_success(
        api_client.compute_provisional_uptime(report["id"], OPERATOR_HEADERS)
    )

    assert data["eligible_port_count"] == 1
    assert data["total_port_minutes"] == 43200
    assert data["excluded_minutes"] == 0
    assert data["billable_downtime_minutes"] == 4320, (
        "1440 minutes clipped off the head of the straddling outage plus the 2880 "
        "minutes the open one is charged up to period_end"
    )
    assert float(data["uptime_pct"]) == 90.00

    assert read_outage_event(still_open["id"])["cleared_at"] is None

    station_after = read_station(station_id)
    assert station_after["gross_downtime_minutes_lifetime"] == 4320, (
        "the lifetime ledger keeps the full 4320-minute closed span and adds "
        "nothing for the uncleared outage"
    )
    assert station_after["billable_downtime_minutes_lifetime"] == 4320
