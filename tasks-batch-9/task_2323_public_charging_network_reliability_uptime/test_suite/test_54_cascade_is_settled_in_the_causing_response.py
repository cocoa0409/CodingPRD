"""One call closes four entities, and every derived field is final the instant it
returns."""
from test_helpers import (
    OPERATOR_HEADERS,
    TECHNICIAN_1,
    api_client,
    assert_instant_equals,
    assert_station_ledger_consistent,
    create_dispatch,
    ingest_and_classify_outage,
    make_field_technician_headers,
    post_progress,
    read_dispatch,
    set_clock,
    setup_operational_station,
    validate_success,
)


def test_the_outage_port_and_station_are_already_final_when_completion_returns():
    """A queued or deferred reconciliation would leave a window in which the dispatch
    reads COMPLETED while the outage still reads DISPATCHED.

    PRD §3.5 on the four links of completion: "The dispatch moves `ON_SITE →
    COMPLETED` ...  The outage moves `DISPATCHED → RESOLVED` with `cleared_at` stamped
    from the logical clock, and the station's gross and billable lifetime downtime
    figures are recomputed.  ... Because no unresolved outage remains on the
    dispenser, it returns `OUT_OF_SERVICE → IN_SERVICE` and its repair posture returns
    `UNDER_REPAIR → NONE` ...  Because the station's out-of-service count reached
    zero, a station suspended with `suspension_source` of `AUTOMATIC` returns
    `SUSPENDED → OPERATIONAL` with `suspension_source` cleared to `NONE`."  PRD §3.4 on
    the ledger those minutes land in: "Each member of that set contributes its closed
    duration, the elapsed time from `detected_at` to `cleared_at` in whole minutes with
    any partial minute discarded.  `gross_downtime_minutes_lifetime` is the sum of
    those durations over the whole set; `excluded_downtime_minutes_lifetime` is the sum
    over just those members currently in `EXCLUDED`; and
    `billable_downtime_minutes_lifetime` is the gross figure less the excluded figure."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/every_cascaded_field_is_already_settled_in_the_causing_response
    """
    scenario = setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
        technician_user_id=TECHNICIAN_1,
    )
    assert_instant_equals(
        dispatch["response_deadline_at"], "2026-08-01T09:00:00Z", "response_deadline_at"
    )

    post_progress(dispatch["id"], "EN_ROUTE", TECHNICIAN_1)
    set_clock("2026-08-01T03:00:00Z")
    post_progress(dispatch["id"], "ARRIVE", TECHNICIAN_1)
    set_clock("2026-08-01T05:30:00Z")

    completed = validate_success(
        api_client.complete_dispatch(dispatch["id"], make_field_technician_headers(TECHNICIAN_1))
    )

    assert completed["state"] == "COMPLETED"
    assert_instant_equals(completed["arrived_at"], "2026-08-01T03:00:00Z", "arrived_at")
    assert completed["response_met"] is True

    settled_outage = validate_success(
        api_client.get_outage_event(outage["id"], OPERATOR_HEADERS)
    )
    assert settled_outage["state"] == "RESOLVED"
    assert_instant_equals(settled_outage["cleared_at"], "2026-08-01T05:30:00Z", "cleared_at")

    settled_port = validate_success(api_client.get_charging_port(port_id, OPERATOR_HEADERS))
    assert settled_port["service_state"] == "IN_SERVICE"
    assert settled_port["maintenance_state"] == "NONE"

    settled_station = validate_success(api_client.get_station(station_id, OPERATOR_HEADERS))
    assert settled_station["status"] == "OPERATIONAL"
    assert settled_station["suspension_source"] == "NONE"
    assert settled_station["out_of_service_port_count"] == 0
    assert settled_station["gross_downtime_minutes_lifetime"] == 330, "00:00 to 05:30"
    assert settled_station["excluded_downtime_minutes_lifetime"] == 0
    assert settled_station["billable_downtime_minutes_lifetime"] == 330
    assert_station_ledger_consistent(settled_station)

    assert (
        read_dispatch(dispatch["id"])["version"] == completed["version"]
    ), "the follow-up reads observed the cascade without provoking another write"
