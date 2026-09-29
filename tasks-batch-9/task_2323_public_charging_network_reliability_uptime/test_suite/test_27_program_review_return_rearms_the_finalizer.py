"""Returning a submitted report rolls back the workflow but keeps the arithmetic."""
from test_helpers import (
    AUDITOR_1,
    PROGRAM_ADMIN_HEADERS,
    api_client,
    read_uptime_report,
    set_clock,
    setup_operational_station,
    setup_submitted_report,
    validate_success,
)


def test_returning_a_submitted_report_clears_the_finalizer_and_counts_the_round_trip():
    """Leaving the old finalizer id behind would silently keep barring that auditor.

    PRD §3.7: "`RETURN` sends it `SUBMITTED → PROVISIONAL`, raises
    `returned_count` by one, and clears `finalized_by_user_id` back to null —
    which both records the round trip and releases the SoD-2 bar until a new
    auditor finalises."  PRD §3.7 also fixes what a return does not touch: only
    an exclusion approval or revocation resets the computed figures, "resetting
    `methodology`, `eligible_port_count`, `total_port_minutes`,
    `excluded_minutes`, `billable_downtime_minutes` and `uptime_pct` to null".

    Design: Corner/state_machines/program_review_return_resets_finalization_and_increments_returned_count
    """
    scenario = setup_operational_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        power_class="DCFC_150",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )

    set_clock("2026-07-15T00:00:00Z")
    submitted = setup_submitted_report(
        scenario["station"]["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )

    assert submitted["state"] == "SUBMITTED"
    assert submitted["finalized_by_user_id"] == AUDITOR_1
    assert submitted["returned_count"] == 0

    data = validate_success(
        api_client.program_review_uptime_report(
            submitted["id"], "RETURN", PROGRAM_ADMIN_HEADERS
        )
    )

    assert data["state"] == "PROVISIONAL"
    assert data["returned_count"] == 1
    assert data["finalized_by_user_id"] is None, "SoD-2 is re-armed for whoever finalises next"

    after = read_uptime_report(submitted["id"])
    assert after["methodology"] == "FINAL", (
        "only the workflow state and the finalizer identity are rolled back"
    )
    assert float(after["uptime_pct"]) == 100.00
    assert after["eligible_port_count"] == 1
    assert after["total_port_minutes"] == 43200, (
        "one eligible dispenser across the 30 days of June is 43200 port-minutes"
    )
    assert after["excluded_minutes"] == 0
    assert after["billable_downtime_minutes"] == 0
