"""Two well-formedness guards that must not be conflated with their neighbours."""
from test_helpers import (
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    assert_uptime_report_draft_fields_null,
    assert_version_unchanged,
    create_host_site_payload,
    create_uptime_report_payload,
    read_host_site,
    setup_station,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_period_of_exactly_seven_days_ending_at_the_clock_is_the_only_one_accepted():
    """A premature period is well-formed, so the two errors must stay apart.

    PRD §3.7: "The period must be well-formed and elapsed: `period_end` strictly
    after `period_start` and spanning at least seven days, or the request fails
    with `ERR_REPORTING_PERIOD_INVALID`; and `period_end` no later than the
    logical clock's current reading, or it fails with
    `ERR_REPORTING_PERIOD_NOT_ELAPSED`."  PRD §3.7 on what a fresh report holds:
    "A fresh report opens in `DRAFT` with `methodology`, `eligible_port_count`,
    `total_port_minutes`, `excluded_minutes`, `billable_downtime_minutes` and
    `uptime_pct` all null, `finalized_by_user_id` null, `claim_count` zero, and
    `returned_count` zero."

    Design: Corner/validations/reporting_period_must_meet_the_minimum_length_and_be_fully_elapsed
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        ports=[{"dispenser_serial": "DS-1", "terminal_model": "PT-4"}],
        stop_at="DRAFT",
    )
    station_id = scenario["station"]["id"]

    def _declare(period_start, period_end):
        return api_client.create_uptime_report(
            create_uptime_report_payload(station_id, period_start, period_end),
            OPERATOR_HEADERS,
        )

    validate_error(
        _declare("2026-07-01T00:00:00Z", "2026-07-05T00:00:00Z"),
        ApiErrorId.ERR_REPORTING_PERIOD_INVALID,
        422,
    )
    validate_error(
        _declare("2026-07-05T00:00:00Z", "2026-07-05T00:00:00Z"),
        ApiErrorId.ERR_REPORTING_PERIOD_INVALID,
        422,
    )
    validate_error(
        _declare("2026-07-25T00:00:00Z", "2026-08-05T00:00:00Z"),
        ApiErrorId.ERR_REPORTING_PERIOD_NOT_ELAPSED,
        422,
    )

    data = validate_success(_declare("2026-07-25T00:00:00Z", "2026-08-01T00:00:00Z"), 201)

    assert data["state"] == "DRAFT"
    assert_uptime_report_draft_fields_null(data)
    assert data["finalized_by_user_id"] is None
    assert data["claim_count"] == 0
    assert data["returned_count"] == 0

    rows, meta = validate_paginated(
        api_client.list_station_uptime_reports(station_id, OPERATOR_HEADERS)
    )
    assert len(rows) == 1, "only the accepted declaration exists"
    assert meta["total_count"] == 1


def test_a_restricted_access_window_of_zero_length_is_refused_on_create_and_on_amend():
    """Equal endpoints are not "strictly earlier", and a refused amendment must
    leave the stored window whole.

    PRD §3.1: "Whenever `access_hours_mode` is `RESTRICTED`, the opening minute
    must be strictly earlier than the closing minute; if it is not, the request
    fails with `ERR_INVALID_ACCESS_WINDOW`.  This rule is checked both when the
    site is registered and every time it is amended."  PRD §3.1 also fixes what a
    rejected amendment must not disturb: "Amending the agreement is the only path
    by which any of these attributes change."

    Design: Corner/validations/restricted_access_window_must_open_before_it_closes
    """
    zero_length = api_client.create_host_site(
        create_host_site_payload(
            "HS-1",
            committed_service_capacity_kw=400.00,
            access_hours_mode="RESTRICTED",
            access_open_minute=600,
            access_close_minute=600,
        ),
        OPERATOR_HEADERS,
    )

    validate_error(zero_length, ApiErrorId.ERR_INVALID_ACCESS_WINDOW, 422)

    _rows, meta = validate_paginated(api_client.list_host_sites(OPERATOR_HEADERS))
    assert meta["total_count"] == 0, "the rejected registration created nothing"

    created = validate_success(
        api_client.create_host_site(
            create_host_site_payload(
                "HS-1",
                committed_service_capacity_kw=400.00,
                access_hours_mode="RESTRICTED",
                access_open_minute=360,
                access_close_minute=1320,
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )
    assert created["access_open_minute"] == 360
    assert created["access_close_minute"] == 1320

    inverted = api_client.update_host_site(
        created["id"], {"access_open_minute": 1320, "access_close_minute": 360}, OPERATOR_HEADERS
    )

    validate_error(inverted, ApiErrorId.ERR_INVALID_ACCESS_WINDOW, 422)

    after = read_host_site(created["id"])
    assert after["access_open_minute"] == 360, "no half-applied window"
    assert after["access_close_minute"] == 1320
    assert after["access_hours_mode"] == "RESTRICTED"
    assert_version_unchanged(after, created["version"], "HostSite")
