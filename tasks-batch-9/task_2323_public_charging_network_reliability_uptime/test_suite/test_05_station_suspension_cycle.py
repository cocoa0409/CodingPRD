"""Station status cycling through both suspension sources."""
from test_helpers import (
    assert_station_ledger_consistent,
    complete_dispatch,
    create_dispatch,
    drive_dispatch_to_on_site,
    ingest_and_classify_outage,
    move_station_status,
    read_station,
    set_clock,
    setup_station,
)


def _operational_station_at_eight_in_the_morning():
    return setup_station(
        clock="2026-06-12T08:00:00Z",
        site_code="HS-CY-1",
        station_code="ST-CY-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )


def _six_hour_critical_outage(port_id):
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
    complete_dispatch(dispatch["id"])
    return outage


def test_a_critical_fault_suspends_the_station_with_an_automatic_source():
    """The system's own suspension is labelled AUTOMATIC and lifts by itself.

    PRD §3.3: "whenever a dispenser on an operational station enters
    `OUT_OF_SERVICE` and the station's out-of-service count is therefore at least
    one, the station moves `OPERATIONAL → SUSPENDED` with `suspension_source` set
    to `AUTOMATIC`" and "The system performs the same move on its own when the
    *last* out-of-service dispenser returns to service, but only when
    `suspension_source` is `AUTOMATIC` and the count has reached zero."

    Design: Difficulty/non_linear_state_machine/station_status_cycles_operational_suspended_operational_with_distinct_sources
    """
    scenario = _operational_station_at_eight_in_the_morning()
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    ingest_and_classify_outage(
        port_id, "2026-06-12T08:00:00Z", fault_class="CRITICAL", fault_code="EVSE-CRIT-02"
    )
    suspended = read_station(station_id)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_source"] == "AUTOMATIC"
    assert suspended["out_of_service_port_count"] == 1


def test_the_station_cycle_is_re_enterable_with_distinguishable_sources():
    """OPERATIONAL is visited twice, and the manual leg is labelled MANUAL.

    PRD §2.6: "The station records `suspension_source`, and only a suspension
    whose source is `AUTOMATIC` is eligible for automatic resumption."  PRD §3.3:
    "An operator may suspend an operational station directly, taking it
    `OPERATIONAL → SUSPENDED` and setting `suspension_source` to `MANUAL`."

    Design: Difficulty/non_linear_state_machine/station_status_cycles_operational_suspended_operational_with_distinct_sources
    """
    scenario = _operational_station_at_eight_in_the_morning()
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    _six_hour_critical_outage(port_id)

    resumed = read_station(station_id)
    assert resumed["status"] == "OPERATIONAL", "the automatic suspension lifted on repair"
    assert resumed["suspension_source"] == "NONE"
    assert resumed["out_of_service_port_count"] == 0

    manual = move_station_status(station_id, "SUSPENDED")
    assert manual["status"] == "SUSPENDED"
    assert manual["suspension_source"] == "MANUAL", (
        "an operator's deliberate suspension must be distinguishable from an "
        f"automatic one, got {manual['suspension_source']}"
    )
    assert manual["out_of_service_port_count"] == 0, (
        "no dispenser is out of service during the manual leg"
    )

    reopened = move_station_status(station_id, "OPERATIONAL")
    assert reopened["status"] == "OPERATIONAL"
    assert reopened["suspension_source"] == "NONE"


def test_the_closed_outage_lands_in_the_station_downtime_ledger():
    """Six hours of closed downtime, none of it excluded.

    PRD §3.4: "`gross_downtime_minutes_lifetime` is the sum of those durations
    over the whole set; `excluded_downtime_minutes_lifetime` is the sum over just
    those members currently in `EXCLUDED`; and
    `billable_downtime_minutes_lifetime` is the gross figure less the excluded
    figure."

    Design: Difficulty/non_linear_state_machine/station_status_cycles_operational_suspended_operational_with_distinct_sources
    """
    scenario = _operational_station_at_eight_in_the_morning()
    station_id = scenario["station"]["id"]

    _six_hour_critical_outage(scenario["ports"][0]["id"])

    station = read_station(station_id)
    assert station["gross_downtime_minutes_lifetime"] == 360, (
        "08:00 to 14:00 is 360 whole minutes, got "
        f"{station['gross_downtime_minutes_lifetime']}"
    )
    assert station["excluded_downtime_minutes_lifetime"] == 0
    assert station["billable_downtime_minutes_lifetime"] == 360
    assert_station_ledger_consistent(station)
