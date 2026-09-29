"""The provisional computation guards its denominator before dividing."""
from test_helpers import (
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    declare_reporting_period,
    read_uptime_report,
    set_clock,
    setup_station,
    validate_error,
)


def _report_whose_only_dispenser_postdates_the_period_start():
    """The station's single dispenser is installed on 2026-06-15, two weeks after
    the reporting period opens, so no dispenser is eligible for the period."""
    scenario = setup_station(
        clock="2026-06-15T00:00:00Z",
        site_code="HS-BD-2",
        station_code="ST-BD-2",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    set_clock("2026-07-15T00:00:00Z")
    return declare_reporting_period(
        scenario["station"]["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )


def test_provisional_computation_rejects_a_zero_total_exposure():
    """A denominator of zero is refused with a declared error, not a crash.

    PRD §3.7: "the total exposure must be greater than zero, or the request fails
    with `ERR_NO_REPORTABLE_PORT_MINUTES`."  PRD §3.7 also fixes the eligibility
    filter that empties the set: "A dispenser is *eligible* for the report when it
    belongs to the report's station, its own `created_at` is at or before
    `period_start`" and "A dispenser installed after `period_start` ... contributes
    no port-minutes at all".

    Design: Difficulty/boundary_precision_check/compute_provisional_rejects_empty_eligible_port_minutes_denominator
    """
    report = _report_whose_only_dispenser_postdates_the_period_start()

    response = api_client.compute_provisional_uptime(report["id"], OPERATOR_HEADERS)

    validate_error(response, ApiErrorId.ERR_NO_REPORTABLE_PORT_MINUTES, 422)
    assert response.status_code != 500, (
        "the zero denominator must be checked before the division is attempted"
    )


def test_the_rejected_computation_leaves_the_report_in_draft_with_null_figures():
    """No partial figure may be written by a refused computation.

    PRD §3.7: "A fresh report opens in `DRAFT` with `methodology`,
    `eligible_port_count`, `total_port_minutes`, `excluded_minutes`,
    `billable_downtime_minutes` and `uptime_pct` all null", and only a successful
    computation "writes `eligible_port_count`, `total_port_minutes`,
    `excluded_minutes`, `billable_downtime_minutes` and `uptime_pct`, sets
    `methodology` to `PROVISIONAL`".

    Design: Difficulty/boundary_precision_check/compute_provisional_rejects_empty_eligible_port_minutes_denominator
    """
    report = _report_whose_only_dispenser_postdates_the_period_start()

    api_client.compute_provisional_uptime(report["id"], OPERATOR_HEADERS)

    after = read_uptime_report(report["id"])
    assert after["state"] == "DRAFT", "the refused computation must not advance the report"
    assert after["uptime_pct"] is None
    assert after["methodology"] is None
