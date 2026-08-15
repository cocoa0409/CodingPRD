"""Telemetry supersede semantics, outage overlap/lifecycle, availability cascade."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_trader_headers,
)
from test_helpers.fixtures import (
    ISO, create_participant, create_generator, create_operating_day,
    create_outage, setup_participant_generator, set_clock,
    run_da_market, close_real_time, submit_telemetry, get_generator_version,
)


class TestTelemetrySupersede:
    def test_telemetry_resubmission_supersedes_prior_row(self, api):
        """PRD §3.3: "Each batch writes new `RECORDED` rows, and any prior
        `RECORDED` row for the same generator, day, and interval moves to
        `SUPERSEDED` — superseded rows are ignored by settlement."

        Design: Corner/entities/telemetry_resubmission_supersedes_prior_row
        """
        p_id, g_id, g_v = setup_participant_generator(company="Tel Co")
        _, d_id, _ = create_operating_day()
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 5}], g_v, p_id)
        g_v2 = get_generator_version(g_id)
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 7}], g_v2, p_id)
        rows, _ = validate_paginated(api.list_telemetry(ISO, params={
            "generator_asset_id": g_id, "operating_day_id": d_id, "interval_index": 1}))
        assert len(rows) == 2
        # created_at ASC: oldest first
        assert rows[0]["status"] == "SUPERSEDED"
        assert rows[1]["status"] == "RECORDED"
        assert rows[1]["actual_mw"] == 7


class TestTelemetryOcc:
    def test_occ_telemetry_stale_asset_version_rejected(self, api):
        """PRD §2.7: "A mismatch with the generator's current `version` is
        rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_telemetry_stale_asset_version_rejected
        """
        p_id, g_id, g_v = setup_participant_generator(company="Occ2 Co")
        _, d_id, _ = create_operating_day()
        run_da_market(d_id, [])
        submit_telemetry(g_id, d_id, [{"interval_index": 1, "actual_mw": 5}], g_v, p_id)
        # stale
        resp = api.submit_telemetry(g_id, {
            "operating_day_id": d_id, "expected_generator_asset_version": g_v,
            "readings": [{"interval_index": 1, "actual_mw": 7}],
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_STALE_ASSET_VERSION)
        # refreshed
        g_v2 = get_generator_version(g_id)
        ok = api.submit_telemetry(g_id, {
            "operating_day_id": d_id, "expected_generator_asset_version": g_v2,
            "readings": [{"interval_index": 1, "actual_mw": 7}],
        }, make_trader_headers(p_id))
        data = validate_success(ok, expected_status=201)
        assert data["recorded_count"] == 1


class TestTelemetryWindow:
    def test_telemetry_after_rt_close_rejected(self, api):
        """PRD §3.3: "Batches are accepted only while the day is `DA_GATED`; at
        any other epoch the submission is rejected with
        `ERR_TELEMETRY_WINDOW_CLOSED`."

        Design: Corner/validations/telemetry_after_rt_close_rejected
        """
        p_id, g_id, g_v = setup_participant_generator(company="Tw Co")
        _, d_id, _ = create_operating_day()
        run_da_market(d_id, [])
        close_real_time(d_id, [])
        resp = api.submit_telemetry(g_id, {
            "operating_day_id": d_id, "expected_generator_asset_version": g_v,
            "readings": [{"interval_index": 1, "actual_mw": 5}],
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_TELEMETRY_WINDOW_CLOSED)


class TestTelemetryIntervalRange:
    def test_telemetry_interval_out_of_range_rejected(self, api):
        """PRD §2.11 item 3: "interval indices within one through twenty-four"
        under `ERR_INVALID_REQUEST`.

        Design: Corner/validations/telemetry_interval_out_of_range_rejected
        """
        p_id, g_id, g_v = setup_participant_generator(company="Iv Co")
        _, d_id, _ = create_operating_day()
        resp = api.submit_telemetry(g_id, {
            "operating_day_id": d_id, "expected_generator_asset_version": g_v,
            "readings": [{"interval_index": 25, "actual_mw": 5}],
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestOutageOverlapHalfOpen:
    def test_outage_half_open_interval_adjacency(self, api):
        """PRD §2.9: "Outage windows are half-open: a report covers every
        instant at or after its `start_at` and strictly before its `end_at`, so
        a report that begins exactly when another ends does not overlap it."
        PRD §3.4: "any true intersection is rejected with `ERR_OUTAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_half_open_interval_adjacency
        """
        p_id, g_id, _ = setup_participant_generator(company="Ovl Co")
        _, out1 = create_outage(g_id, p_id, derate_pct=50,
                                start_at="2026-08-05T10:00:00Z", end_at="2026-08-05T12:00:00Z",
                                reason="first")
        # overlapping
        resp = api.create_outage(g_id, {
            "outage_type": "PARTIAL", "derate_pct": 30,
            "start_at": "2026-08-05T11:00:00Z", "end_at": "2026-08-05T13:00:00Z",
            "reason": "overlapping",
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_OUTAGE_OVERLAP)
        # adjacent at the exclusive end
        resp2 = api.create_outage(g_id, {
            "outage_type": "PARTIAL", "derate_pct": 30,
            "start_at": "2026-08-05T12:00:00Z", "end_at": "2026-08-05T14:00:00Z",
            "reason": "adjacent",
        }, make_trader_headers(p_id))
        out3 = validate_success(resp2, expected_status=201)
        assert out3["status"] == "SUBMITTED"
        rows, _ = validate_paginated(api.list_outages(ISO, params={"generator_asset_id": g_id}))
        assert len(rows) == 2
        assert rows[0]["id"] == out1
        assert rows[1]["id"] == out3["id"]


class TestOutageDeniedResubmitCycle:
    def test_outage_denied_resubmission_cycle(self, api):
        """PRD §3.4: "a `Trader` may resubmit the report, optionally correcting
        `derate_pct`, `start_at`, `end_at`, or `reason`, which cycles it
        `DENIED` → `SUBMITTED`. ... the denial-and-resubmission cycle may
        repeat any number of times."

        Design: Difficulty/non_linear_state_machine/outage_denied_resubmission_cycle
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Out Co")
        _, out_id = create_outage(g_id, p_id, derate_pct=40,
                                  start_at="2026-08-05T00:00:00Z", end_at="2026-08-06T00:00:00Z",
                                  reason="boiler tube leak")
        api.acknowledge_outage(out_id, ISO)
        api.deny_outage(out_id, {"denial_reason": "insufficient notice"}, ISO)
        mid = get_success_data(api.get_outage(out_id, ISO))
        assert mid["status"] == "DENIED"
        assert mid["denial_reason"] == "insufficient notice"

        resp = api.resubmit_outage(out_id, {"derate_pct": 30,
                                            "reason": "boiler tube leak — revised scope"},
                                   make_trader_headers(p_id))
        re = validate_success(resp)
        assert re["status"] == "SUBMITTED"
        assert re["derate_pct"] == 30

        api.acknowledge_outage(out_id, ISO)
        api.approve_outage(out_id, ISO)
        final = get_success_data(api.get_outage(out_id, ISO))
        assert final["status"] == "APPROVED"
        # logical clock 2026-08-01 outside the window -> no immediate derate
        gen = get_success_data(api.get_generator(g_id, ISO))
        assert gen["status"] == "AVAILABLE"
        assert gen["availability_mw"] == 10


class TestOutageCancelTerminalLockdown:
    def test_outage_cancel_terminal_lockdown(self, api):
        """PRD §3.4: "Cancellation by a `Trader` moves a report from
        `SUBMITTED`, `ACKNOWLEDGED`, or `APPROVED` to `CANCELLED`, which is
        terminal."

        Design: Corner/state_machines/outage_cancel_terminal_lockdown
        """
        p_id, g_id, _ = setup_participant_generator(company="Term Co")
        _, out_id = create_outage(g_id, p_id, derate_pct=25)
        api.cancel_outage(out_id, make_trader_headers(p_id))
        resp = api.approve_outage(out_id, ISO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        out = get_success_data(api.get_outage(out_id, ISO))
        assert out["status"] == "CANCELLED"


class TestOutageSchema:
    def test_outage_full_with_partial_derate_rejected(self, api):
        """PRD §3.4: "a `derate_pct` (exactly one hundred for `FULL`, between
        one and ninety-nine for `PARTIAL`)".

        Design: Corner/validations/outage_full_with_partial_derate_rejected
        """
        p_id, g_id, _ = setup_participant_generator(company="Xf Co")
        resp = api.create_outage(g_id, {
            "outage_type": "FULL", "derate_pct": 50,
            "start_at": "2026-08-05T00:00:00Z", "end_at": "2026-08-06T00:00:00Z",
            "reason": "bad",
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestEpochOrdering:
    def test_ops_run_checkpoint_epoch_order_enforced(self, api):
        """PRD §2.11 item 7: "day-epoch ordering" under
        `ERR_INVALID_STATE_TRANSITION`. PRD §3.3 close-real-time advances
        "the day `DA_GATED` → `RT_COMPLETE`".

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_epoch_order_enforced
        """
        _, d_id, _ = create_operating_day()
        resp = api.close_real_time(d_id, {"rt_node_prices_prelim": []}, ISO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        day = get_success_data(api.get_operating_day(d_id, ISO))
        assert day["status"] == "DA_OPEN"
