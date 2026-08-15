"""Cycle-time analytics: cohort scoping, nearest-rank percentiles, empty cohorts."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_redlining_ctx, finalize_redlining, create_packet, sign_packet_ok,
    submit_and_triage, open_negotiation_from_intake, set_logical_clock,
    create_round_payload, setup_user_directory, headers_by_id,
)


def _execute_one_hundred_second_deal(api):
    """Drive one negotiation from creation at the startup instant to execution at
    T+100s. Returns the populated ctx."""
    ctx = setup_redlining_ctx()  # clock pinned at 2026-08-01T00:00:00Z
    finalize_redlining(ctx)
    packet = create_packet(ctx, [ctx.users["sg"]["id"]])
    sign_packet_ok(ctx, packet["id"], ctx.users["sg"]["id"])
    set_logical_clock("2026-08-01T00:01:40Z")
    resp = api.record_execution(
        ctx.negotiation["id"], packet["id"],
        {"execution_timestamp": "2026-08-01T00:01:40Z"},
        ctx.headers[ctx.users["sg"]["id"]])
    validate_success(resp, expected_status=200)
    return ctx


class TestCycleTimeCohorts:
    def test_executed_cohort_reports_nearest_rank_percentiles(self, api):
        """With one EXECUTED negotiation (cycle 100s) and one still in flight, the
        executed cohort contains only the finished deal and every percentile is 100.

        PRD §3.9: "For a single negotiation, cycle time is the execution timestamp
        minus `created_at`, in integer seconds."
        PRD §3.9: "The default cohort is every negotiation whose draft dimension is
        `EXECUTED` and whose execution instant falls inside the window".
        PRD §3.9: "Percentiles use the nearest-rank method: sort the cohort's cycle
        times ascending, take the rank as the ceiling of the percentile divided by 100
        and multiplied by the cohort size, and pick the value at that one-based rank".

        Design: Difficulty/dual_variant_calc/cycle_time_percentile_vs_active_cohort_provisional
        """
        ctx = _execute_one_hundred_second_deal(api)
        hdrs = ctx.headers

        # A second negotiation opens at T+100s and stays in flight.
        intake2 = submit_and_triage(ctx.users, ctx.contract_type, ctx.counterparty, 80_000)
        neg2 = open_negotiation_from_intake(
            intake2, ctx.playbook, ctx.users["ca"]["id"], hdrs[ctx.users["ca"]["id"]])
        get_success_data(api.create_round(
            neg2["id"], create_round_payload(change_summary="kickoff"),
            hdrs[ctx.users["ca"]["id"]]))
        set_logical_clock("2026-08-01T00:03:20Z")

        cc = hdrs[ctx.users["cc"]["id"]]
        resp = api.get_cycle_time_analytics(cc, params={
            "from_iso": "2026-08-01T00:00:00Z", "to_iso": "2026-08-02T00:00:00Z"})
        data = validate_success(resp, expected_status=200)
        assert data["cohort_size"] == 1, (
            "the in-flight negotiation must be excluded from the executed cohort")
        assert data["p50_seconds"] == 100
        assert data["p90_seconds"] == 100
        assert data["p99_seconds"] == 100
        assert data["mean_seconds"] == 100

    def test_empty_cohort_yields_null_percentiles(self, api):
        """A window containing no executions yields an empty cohort with null
        percentiles.

        PRD §3.9: "an empty cohort yields null".
        PRD §3.9: "The cycle-time report takes a required `from_iso` and `to_iso`
        bracketing a half-open window — inclusive of the start instant, exclusive of
        the end".

        Design: Difficulty/dual_variant_calc/cycle_time_percentile_vs_active_cohort_provisional
        """
        ctx = _execute_one_hundred_second_deal(api)
        cc = ctx.headers[ctx.users["cc"]["id"]]
        resp = api.get_cycle_time_analytics(cc, params={
            "from_iso": "2026-09-01T00:00:00Z", "to_iso": "2026-09-02T00:00:00Z"})
        data = validate_success(resp, expected_status=200)
        assert data["cohort_size"] == 0
        assert data["p50_seconds"] is None
        assert data["p90_seconds"] is None
        assert data["p99_seconds"] is None


class TestAnalyticsInputs:
    def test_cycle_time_requires_window_dates(self, api):
        """Omitting the required from_iso/to_iso is a 400.

        PRD §3.9: "The cycle-time report takes a required `from_iso` and `to_iso`
        bracketing a half-open window — inclusive of the start instant, exclusive of
        the end".

        Design: Corner/endpoints/analytics_cycle_time_requires_dates
        """
        users = setup_user_directory()
        hdrs = headers_by_id(users)
        resp = api.get_cycle_time_analytics(hdrs[users["cc"]["id"]])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
