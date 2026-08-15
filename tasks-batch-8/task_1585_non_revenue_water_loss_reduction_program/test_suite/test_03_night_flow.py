"""Night-flow monitoring: signal thresholds, window duration bounds, and the
one-hour buffer rule (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assert_night_flow_assessment,
    create_dma,
    create_night_flow_assessment,
    make_utility_analyst_headers,
    setup_dma_with_finalized_balance,
    validate_error,
    validate_success,
)

UA = TEST_DEFAULTS["UTILITY_ANALYST"]


def _analyze(api, assessment_id, analyst=UA):
    return validate_success(
        api.analyze_night_flow_assessment(
            assessment_id, make_utility_analyst_headers(analyst)
        ),
        200,
    )


class TestSignalThresholdBoundaries:
    def test_net_flow_at_critical_threshold_maps_critical(self, api):
        """PRD §3.3: "`net_night_flow_lps` is the measured minimum night flow
        minus the legitimate-use allowance, floored at zero." and "The
        `leak_signal` then classifies the assessment: `CRITICAL` when the net
        night flow reaches 15.0 litres per second or more, or when a non-null
        `net_night_flow_pct` reaches 20.0 or more; `ELEVATED` when the net night
        flow reaches 5.0 litres per second or more, or a non-null percentage
        reaches 8.0 or more; otherwise `NONE`. All four thresholds are
        inclusive."

        Design: Difficulty/boundary_precision_check/night_flow_signal_exact_threshold_boundaries
        """
        dma, _ = setup_dma_with_finalized_balance(code="DMA-BP1")
        assessment = create_night_flow_assessment(
            dma["id"],
            window_start="2026-08-02T01:00:00Z",
            window_end="2026-08-02T04:00:00Z",
            measured_mnf_lps=18.0,
            expected_legitimate_night_use_lps=3.0,
        )
        analyzed = _analyze(api, assessment["id"])
        assert_night_flow_assessment(analyzed)
        assert analyzed["status"] == "ANALYZED"
        assert analyzed["net_night_flow_lps"] == pytest.approx(15.0, abs=1e-9)
        # avg daily inflow = 1,000,000 m3 * 1000 / (90 days * 86400 s)
        #                  = 128.6008... lps; 15.0 / 128.6008... * 100 = 11.66
        assert analyzed["net_night_flow_pct"] == pytest.approx(11.66, abs=0.01)
        assert analyzed["leak_signal"] == "CRITICAL"

    def test_elevated_boundary_and_just_below_elevated(self, api):
        """PRD §3.3: "`ELEVATED` when the net night flow reaches 5.0 litres per
        second or more, or a non-null percentage reaches 8.0 or more; otherwise
        `NONE`. All four thresholds are inclusive."

        Design: Difficulty/boundary_precision_check/night_flow_signal_exact_threshold_boundaries
        """
        dma, _ = setup_dma_with_finalized_balance(code="DMA-BP1B")
        elevated = create_night_flow_assessment(
            dma["id"],
            window_start="2026-08-02T05:00:00Z",
            window_end="2026-08-02T08:00:00Z",
            measured_mnf_lps=8.0,
            expected_legitimate_night_use_lps=3.0,
        )
        none_assessment = create_night_flow_assessment(
            dma["id"],
            window_start="2026-08-02T09:00:00Z",
            window_end="2026-08-02T12:00:00Z",
            measured_mnf_lps=7.99,
            expected_legitimate_night_use_lps=3.0,
        )

        analyzed_elevated = _analyze(api, elevated["id"])
        assert analyzed_elevated["net_night_flow_lps"] == pytest.approx(5.0, abs=1e-9)
        assert analyzed_elevated["leak_signal"] == "ELEVATED"

        analyzed_none = _analyze(api, none_assessment["id"])
        assert analyzed_none["net_night_flow_lps"] == pytest.approx(4.99, abs=1e-9)
        assert analyzed_none["leak_signal"] == "NONE"


class TestOneHourBuffer:
    def test_fifty_nine_minute_gap_rejected(self, api):
        """PRD §3.3: "A window must last at least 2 hours and at most 6 hours,
        and windows for the same DMA must not overlap and must respect a
        one-hour buffer: a new window's `window_start` must be at least one hour
        after the latest existing window's `window_end`. Breaches are rejected
        with `ERR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/night_flow_one_hour_buffer_semantics
        """
        dma = create_dma(code="DMA-TO2", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        create_night_flow_assessment(
            dma["id"],
            window_start="2026-08-02T01:00:00Z",
            window_end="2026-08-02T04:00:00Z",
            measured_mnf_lps=6.0,
            expected_legitimate_night_use_lps=2.0,
        )
        res = api.create_night_flow_assessment(
            {
                "dma_id": dma["id"],
                "window_start": "2026-08-02T04:59:00Z",
                "window_end": "2026-08-02T07:00:00Z",
                "measured_mnf_lps": 6.0,
                "expected_legitimate_night_use_lps": 2.0,
            },
            make_utility_analyst_headers(UA),
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_CONFLICT, expected_status=409)

    def test_exact_one_hour_gap_accepted(self, api):
        """PRD §3.3: "a new window's `window_start` must be at least one hour
        after the latest existing window's `window_end`."

        Design: Difficulty/resource_temporal_overlap/night_flow_one_hour_buffer_semantics
        """
        dma = create_dma(code="DMA-TO2B", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        create_night_flow_assessment(
            dma["id"],
            window_start="2026-08-02T01:00:00Z",
            window_end="2026-08-02T04:00:00Z",
            measured_mnf_lps=6.0,
            expected_legitimate_night_use_lps=2.0,
        )
        res = api.create_night_flow_assessment(
            {
                "dma_id": dma["id"],
                "window_start": "2026-08-02T05:00:00Z",
                "window_end": "2026-08-02T08:00:00Z",
                "measured_mnf_lps": 6.0,
                "expected_legitimate_night_use_lps": 2.0,
            },
            make_utility_analyst_headers(UA),
        )
        accepted = validate_success(res, 201)
        assert_night_flow_assessment(accepted)
        assert accepted["status"] == "RECORDED"


class TestWindowDurationBounds:
    def test_one_hour_window_rejected_three_hours_accepted(self, api):
        """PRD §3.3: "A window must last at least 2 hours and at most 6 hours,
        and windows for the same DMA must not overlap and must respect a
        one-hour buffer: a new window's `window_start` must be at least one hour
        after the latest existing window's `window_end`. Breaches are rejected
        with `ERR_WINDOW_CONFLICT`."

        Design: Corner/validations/night_flow_window_duration_bounds
        """
        dma = create_dma(code="DMA-VAL3", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        too_short = api.create_night_flow_assessment(
            {
                "dma_id": dma["id"],
                "window_start": "2026-08-02T01:00:00Z",
                "window_end": "2026-08-02T02:00:00Z",
                "measured_mnf_lps": 6.0,
                "expected_legitimate_night_use_lps": 2.0,
            },
            make_utility_analyst_headers(UA),
        )
        validate_error(too_short, ApiErrorId.ERR_WINDOW_CONFLICT, expected_status=409)

        ok = api.create_night_flow_assessment(
            {
                "dma_id": dma["id"],
                "window_start": "2026-08-02T01:00:00Z",
                "window_end": "2026-08-02T04:00:00Z",
                "measured_mnf_lps": 6.0,
                "expected_legitimate_night_use_lps": 2.0,
            },
            make_utility_analyst_headers(UA),
        )
        accepted = validate_success(ok, 201)
        assert accepted["status"] == "RECORDED"
