"""Reporting periods collide under the closed convention, so adjacency is fatal."""
from test_helpers import (
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_uptime_report_payload,
    declare_reporting_period,
    read_uptime_report,
    set_clock,
    setup_station,
    validate_error,
    validate_paginated,
    validate_success,
)


def _station_with_one_declared_may_period():
    """One station, one existing report covering 2026-05-01 through 2026-06-01."""
    scenario = setup_station(
        clock="2026-04-01T00:00:00Z",
        site_code="HS-OV-2",
        station_code="ST-OV-2",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    set_clock("2026-07-15T00:00:00Z")
    station_id = scenario["station"]["id"]
    first = declare_reporting_period(
        station_id, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"
    )
    return station_id, first


def _declare(station_id, period_start, period_end):
    return api_client.create_uptime_report(
        create_uptime_report_payload(station_id, period_start, period_end), OPERATOR_HEADERS
    )


def test_a_period_starting_exactly_at_an_existing_period_end_is_rejected():
    """Both endpoints are inclusive, so touching periods share a minute.

    PRD §3.7: a new period "must also not collide with any existing report period
    on the same station, in any state, under the closed-interval convention of
    §2.10 — a genuine intersection *or* a merely adjacent period is rejected with
    `ERR_REPORTING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/uptime_report_periods_are_closed_per_station_so_adjacent_periods_collide
    """
    station_id, _first = _station_with_one_declared_may_period()

    response = _declare(station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    validate_error(response, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP, 409)


def test_one_minute_of_separation_is_enough():
    """The smallest legal separation is a single minute.

    PRD §3.7: "The period must be well-formed and elapsed: `period_end` strictly
    after `period_start` and spanning at least seven days, or the request fails
    with `ERR_REPORTING_PERIOD_INVALID`."

    Design: Difficulty/resource_temporal_overlap/uptime_report_periods_are_closed_per_station_so_adjacent_periods_collide
    """
    station_id, _first = _station_with_one_declared_may_period()

    _declare(station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    data = validate_success(
        _declare(station_id, "2026-06-01T00:01:00Z", "2026-07-01T00:00:00Z"), 201
    )

    assert data["state"] == "DRAFT"
    assert_instant_equals(data["period_start"], "2026-06-01T00:01:00Z", "period_start")
    assert_instant_equals(data["period_end"], "2026-07-01T00:00:00Z", "period_end")


def test_the_station_keeps_exactly_the_two_accepted_periods_untouched():
    """The rejected declaration leaves no report and disturbs no neighbour.

    PRD §3.7: an uptime report is "a station-scoped reporting period plus the
    figures computed over it", and the existing period is only ever rewritten by
    the operations of §3.7 — never by a rejected declaration.

    Design: Difficulty/resource_temporal_overlap/uptime_report_periods_are_closed_per_station_so_adjacent_periods_collide
    """
    station_id, first = _station_with_one_declared_may_period()

    _declare(station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    _declare(station_id, "2026-06-01T00:01:00Z", "2026-07-01T00:00:00Z")

    rows, _meta = validate_paginated(
        api_client.list_station_uptime_reports(station_id, OPERATOR_HEADERS)
    )
    assert len(rows) == 2, f"only the two accepted periods should exist, got {len(rows)}"

    assert_instant_equals(
        read_uptime_report(first["id"])["period_end"], "2026-06-01T00:00:00Z", "period_end"
    )
