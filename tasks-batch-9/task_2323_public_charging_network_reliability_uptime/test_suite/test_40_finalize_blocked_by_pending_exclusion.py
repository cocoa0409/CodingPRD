"""An undecided exclusion makes the federal denominator ambiguous."""
from test_helpers import (
    AUDITOR_HEADERS,
    ApiErrorId,
    adjudicate_exclusion,
    api_client,
    assert_station_ledger_consistent,
    assert_uptime_report_draft_fields_null,
    compute_provisional,
    declare_reporting_period,
    finalize_report,
    ingest_and_classify_outage,
    read_outage_event,
    read_station,
    read_uptime_report,
    request_exclusion,
    set_clock,
    setup_station,
    validate_error,
)


def test_deciding_the_pending_exclusion_unlocks_finalisation_and_rewrites_the_figure():
    """The refusal, the invalidation and the two methodologies chain in one line.

    PRD §3.7: "No outage attributed to the period may still be sitting in
    `EXCLUSION_REVIEW`, or the request fails with `ERR_EXCLUSION_REVIEW_PENDING` —
    a pending exclusion adjudication would make the number provisional in fact
    even if the state said otherwise."  PRD §3.7 on invalidation: "an outage on the
    station being approved for exclusion — or having an approved exclusion revoked
    — sends every `PROVISIONAL` report on that station back `PROVISIONAL → DRAFT`,
    resetting `methodology`, `eligible_port_count`, `total_port_minutes`,
    `excluded_minutes`, `billable_downtime_minutes` and `uptime_pct` to null ...
    The operator must recompute before the report can be finalised again."  PRD
    §3.7 on the two figures: provisional credits excluded minutes "in the
    **numerator only**", while under the final methodology "excluded minutes leave
    **both** numerator and denominator".  PRD §3.7 on an open fault: "An uncleared
    outage is therefore charged right through to the end of the period."

    Design: Corner/validations/finalize_is_blocked_while_an_overlapping_exclusion_review_is_still_pending
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

    set_clock("2026-06-10T00:00:00Z")
    outage = ingest_and_classify_outage(
        port_id, "2026-06-10T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )
    pending = request_exclusion(outage["id"], "UTILITY_OUTAGE")
    assert pending["state"] == "EXCLUSION_REVIEW"

    set_clock("2026-07-15T00:00:00Z")
    report = declare_reporting_period(
        station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    provisional = compute_provisional(report["id"])

    assert provisional["state"] == "PROVISIONAL"
    assert provisional["eligible_port_count"] == 1
    assert provisional["total_port_minutes"] == 43200, "one dispenser over thirty days"
    assert provisional["excluded_minutes"] == 0, "the review has not been decided"
    assert provisional["billable_downtime_minutes"] == 30240, "21 open days, charged to the end"
    assert float(provisional["uptime_pct"]) == 30.00

    blocked = api_client.finalize_uptime_report(report["id"], AUDITOR_HEADERS)

    validate_error(blocked, ApiErrorId.ERR_EXCLUSION_REVIEW_PENDING, 409)

    still_provisional = read_uptime_report(report["id"])
    assert still_provisional["state"] == "PROVISIONAL"
    assert still_provisional["methodology"] == "PROVISIONAL"
    assert still_provisional["finalized_by_user_id"] is None

    excluded = adjudicate_exclusion(outage["id"], "APPROVE")
    assert excluded["state"] == "EXCLUDED"
    assert excluded["cleared_at"] is None, "approval excludes the minutes, it does not repair"

    invalidated = read_uptime_report(report["id"])
    assert invalidated["state"] == "DRAFT", "the computed figures no longer stand"
    assert_uptime_report_draft_fields_null(invalidated)

    recomputed = compute_provisional(report["id"])
    assert recomputed["state"] == "PROVISIONAL"
    assert recomputed["total_port_minutes"] == 43200
    assert recomputed["excluded_minutes"] == 30240, "the same minutes changed bucket"
    assert recomputed["billable_downtime_minutes"] == 0
    assert float(recomputed["uptime_pct"]) == 30.00, "the provisional denominator is unmoved"

    final = finalize_report(report["id"])

    assert final["state"] == "FINAL"
    assert final["methodology"] == "FINAL"
    assert final["excluded_minutes"] == 30240
    assert final["billable_downtime_minutes"] == 0
    assert float(final["uptime_pct"]) == 100.00, "12960 of 12960 reportable minutes"

    station = read_station(station_id)
    assert station["gross_downtime_minutes_lifetime"] == 0, (
        "the fault is still open, so it contributes nothing to the lifetime ledger"
    )
    assert station["excluded_downtime_minutes_lifetime"] == 0
    assert station["billable_downtime_minutes_lifetime"] == 0
    assert_station_ledger_consistent(station)
    assert read_outage_event(outage["id"])["state"] == "EXCLUDED"
