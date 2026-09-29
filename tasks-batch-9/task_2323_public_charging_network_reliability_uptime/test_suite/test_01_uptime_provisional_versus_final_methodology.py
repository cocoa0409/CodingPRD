"""The two uptime methodologies over one identical set of outage rows."""
from test_helpers import (
    AUDITOR_1,
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    api_client,
    approve_exclusion,
    assert_station_ledger_consistent,
    assert_two_decimals,
    declare_reporting_period,
    make_compliance_auditor_headers,
    read_station,
    run_repair_cycle,
    set_clock,
    setup_station,
    validate_success,
)


def _station_with_one_excluded_and_one_billable_outage():
    """Two eligible dispensers over a 30-day period, one approved-excluded
    outage of 1440 minutes and one billable outage of 720 minutes."""
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-UP-1",
        station_code="ST-UP-1",
        committed_service_capacity_kw=800.00,
        power_class="DCFC_150",
        declared_port_count=2,
        ports=[
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-UP-1", connector_type="CCS1"),
            dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-UP-2", connector_type="NACS"),
        ],
    )
    port_id = scenario["ports"][0]["id"]

    # A utility outage: one full day of downtime, later approved as excluded.
    set_clock("2026-06-05T02:00:00Z")
    excluded_cycle = run_repair_cycle(
        port_id,
        detected_at="2026-06-05T00:00:00Z",
        window_start_at="2026-06-05T01:00:00Z",
        window_end_at="2026-06-05T23:00:00Z",
        completed_at="2026-06-06T00:00:00Z",
        fault_class="MINOR",
        fault_code="OCPP-UTIL-01",
        excluded_cause_claim="UTILITY_OUTAGE",
    )
    approve_exclusion(excluded_cycle["outage"]["id"], excluded_cause_claim="UTILITY_OUTAGE")

    # A communications outage: twelve hours of downtime, left billable.
    set_clock("2026-06-10T02:00:00Z")
    run_repair_cycle(
        port_id,
        detected_at="2026-06-10T00:00:00Z",
        window_start_at="2026-06-10T01:00:00Z",
        window_end_at="2026-06-10T11:00:00Z",
        completed_at="2026-06-10T12:00:00Z",
        fault_class="MINOR",
        fault_code="OCPP-COMM-07",
    )

    set_clock("2026-07-15T00:00:00Z")
    report = declare_reporting_period(
        scenario["station"]["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    return scenario, report


def test_provisional_uptime_credits_excluded_minutes_in_the_numerator_only():
    """The provisional variant keeps the full exposure in the denominator.

    PRD §3.7: "Under the provisional methodology, excluded minutes are credited
    in the **numerator only**: the figure is one hundred multiplied by the total
    exposure less the excluded minutes less the billable downtime minutes, all
    divided by the total exposure, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/uptime_provisional_and_final_variants_diverge_on_identical_outage_rows
    """
    _, report = _station_with_one_excluded_and_one_billable_outage()

    data = validate_success(api_client.compute_provisional_uptime(report["id"], OPERATOR_HEADERS))

    assert data["state"] == "PROVISIONAL", f"expected PROVISIONAL, got {data['state']}"
    assert data["methodology"] == "PROVISIONAL"
    assert data["eligible_port_count"] == 2, "both dispensers predate period_start"
    assert data["total_port_minutes"] == 86400, "two dispensers over 43200 minutes"
    assert data["excluded_minutes"] == 1440
    assert data["billable_downtime_minutes"] == 720
    assert_two_decimals(data["uptime_pct"], "uptime_pct")
    assert float(data["uptime_pct"]) == 97.50, (
        "100 * (86400 - 1440 - 720) / 86400 must round to 97.50, got "
        f"{data['uptime_pct']}"
    )


def test_final_uptime_drops_excluded_minutes_from_both_numerator_and_denominator():
    """The federal variant reports a strictly higher figure over the same rows.

    PRD §3.7: "Under the final federal methodology, excluded minutes leave
    **both** numerator and denominator" and "Whenever there is at least one
    excluded minute and at least one billable downtime minute, the final figure
    over identical rows is strictly greater than the provisional figure."

    Design: Difficulty/dual_variant_calc/uptime_provisional_and_final_variants_diverge_on_identical_outage_rows
    """
    scenario, report = _station_with_one_excluded_and_one_billable_outage()

    provisional = validate_success(
        api_client.compute_provisional_uptime(report["id"], OPERATOR_HEADERS)
    )
    final = validate_success(
        api_client.finalize_uptime_report(
            report["id"], make_compliance_auditor_headers(AUDITOR_1)
        )
    )

    assert final["state"] == "FINAL"
    assert final["methodology"] == "FINAL"
    assert float(final["uptime_pct"]) == 99.15, (
        "100 * (86400 - 1440 - 720) / (86400 - 1440) must round to 99.15, got "
        f"{final['uptime_pct']}"
    )
    assert float(final["uptime_pct"]) > float(provisional["uptime_pct"]), (
        "the federal figure must be strictly greater than the provisional figure "
        "over identical rows"
    )
    assert final["excluded_minutes"] == 1440, "the excluded bucket itself did not move"
    assert final["total_port_minutes"] == 86400, "the exposure figure itself did not move"
    assert final["finalized_by_user_id"] == AUDITOR_1, (
        "finalisation stores the acting auditor's X-User-ID for SoD-2, got "
        f"{final['finalized_by_user_id']}"
    )

    station = read_station(scenario["station"]["id"])
    assert station["gross_downtime_minutes_lifetime"] == 2160
    assert station["excluded_downtime_minutes_lifetime"] == 1440
    assert station["billable_downtime_minutes_lifetime"] == 720
    assert_station_ledger_consistent(station)
