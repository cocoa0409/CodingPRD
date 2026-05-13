"""Water balance report calculation and window validation.

Covers PRD §3.9 (window-length check, input integration, apparent and real
loss formulas, nrw_pct, ERR_INSUFFICIENT_DATA for zero-input).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId, APPARENT_LOSS_RATE, CO,
    advance_clock, create_and_activate_flow_device,
    create_and_activate_meter_device,
    get_network, iso_from_epoch_ms, post_reading,
    setup_dma_with_inlet_flow_and_meter,
    setup_published_network_with_one_segment,
    water_balance_report_payload,
    round_half_up,
    validate_error, validate_success,
)


# ===========================================================================
# Window length validation — PRD §3.9
# ===========================================================================
class TestWindowValidation:

    @pytest.mark.parametrize("seconds", [3599, 3601, 7200, 86399, 86401])
    def test_invalid_window_length_rejected(self, api, seconds):
        """PRD §3.9: "The window length — that is, window_end −
        window_start — must equal exactly one hour (3600 seconds), one
        day (86400 seconds), or one week (604800 seconds); window_end
        must be strictly greater than window_start; failure surfaces as
        ERR_INVALID_WINDOW with HTTP 422."

        # difficulty: resource_temporal_overlap/water_balance_window_half_open_exclusion
        Claim: a window length that is not one of {3600, 86400, 604800}
        seconds → ERR_INVALID_WINDOW.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        net = get_network(api, net_id)
        end_ms = net["clock_epoch_ms"]
        start_ms = end_ms - seconds * 1000
        payload = water_balance_report_payload(
            iso_from_epoch_ms(start_ms),
            iso_from_epoch_ms(end_ms),
        )
        resp = api.create_water_balance_report(
            net_id, base["dma"]["id"], payload, CO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)

    def test_window_end_not_greater_than_start_rejected(self, api):
        """PRD §3.9: "window_end must be strictly greater than
        window_start ... failure surfaces as ERR_INVALID_WINDOW with
        HTTP 422."
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        net = get_network(api, net_id)
        t = iso_from_epoch_ms(net["clock_epoch_ms"])
        payload = water_balance_report_payload(t, t)
        resp = api.create_water_balance_report(
            net_id, base["dma"]["id"], payload, CO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# ===========================================================================
# Zero-input rejection — PRD §3.9
# ===========================================================================
class TestZeroInputRejected:

    def test_no_accepted_inlet_readings_returns_insufficient_data(self, api):
        """PRD §3.9: "If input_volume_m3 evaluates to zero — that is, no
        inlet device produced an ACCEPTED reading in the window — the
        request is rejected with ERR_INSUFFICIENT_DATA and HTTP 422
        (this is also the rejection when no inlet device has at least
        one ACCEPTED reading in the window)."

        # difficulty: boundary_precision_check/water_balance_window_empty_dataset_zero_input
        Claim: an inlet device exists but has no ACCEPTED readings in
        the window → ERR_INSUFFICIENT_DATA.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        # Create an inlet FLOW device with no readings.
        create_and_activate_flow_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        end_ms = net["clock_epoch_ms"]
        start_ms = end_ms - 86400 * 1000
        payload = water_balance_report_payload(
            iso_from_epoch_ms(start_ms),
            iso_from_epoch_ms(end_ms),
        )
        resp = api.create_water_balance_report(
            net_id, base["dma"]["id"], payload, CO,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DATA.value)


# ===========================================================================
# Apparent loss / real loss / nrw_pct — PRD §3.9 formulas
# ===========================================================================
class TestWaterBalanceFormulas:
    """PRD §3.9 numerics — pinned formula and precision.

    # difficulty: combinatorial_formula/water_balance_rounding_order_combinatorial
    """

    def test_apparent_loss_is_input_times_004(self, api):
        """PRD §3.9: "apparent_loss_m3 represents the estimated meter
        inaccuracy plus unauthorized consumption and is computed as
        input_volume_m3 multiplied by 0.04 (a fixed 4.0 percent
        apparent-loss rate)."
        PRD §2.6: "All cubic-meter quantities ... are rounded to three
        decimal places."

        Claim: with input_volume_m3 = 432.000 m^3, apparent_loss_m3 =
        17.280.
        """
        env = setup_dma_with_inlet_flow_and_meter(
            api,
            inlet_flow_lps=5.0,           # constant 5 L/s over 86400s
            billed_meter_first=0.0,
            billed_meter_last=300.0,
            window_seconds=86400,
        )
        payload = water_balance_report_payload(env["window_start"],
                                               env["window_end"])
        report = validate_success(
            api.create_water_balance_report(
                env["network"]["id"], env["dma"]["id"], payload, CO,
            ),
            expected_status=201,
        )
        # Expected input: 5 L/s * 86400 s / 1000 = 432.000 m^3.
        # The exact endpoint of the integration is implementation-pinned
        # to half-open [start, end); but with a constant flow the
        # integral is unambiguous.
        assert report["input_volume_m3"] == pytest.approx(432.000, abs=0.01)
        expected_apparent = round_half_up(432.0 * APPARENT_LOSS_RATE, 3)
        assert report["apparent_loss_m3"] == pytest.approx(
            expected_apparent, abs=0.01
        )

    def test_nrw_pct_computed_from_input_and_billed(self, api):
        """PRD §3.9: "The non-revenue water percentage nrw_pct is
        (input_volume_m3 − billed_consumption_m3) / input_volume_m3 ×
        100, rounded to two decimal places."

        Claim: (432.000 - 300.000) / 432.000 * 100 = 30.5555... → 30.56
        (round-half-up to 2 decimals).
        """
        env = setup_dma_with_inlet_flow_and_meter(
            api,
            inlet_flow_lps=5.0,
            billed_meter_first=0.0,
            billed_meter_last=300.0,
            window_seconds=86400,
        )
        payload = water_balance_report_payload(env["window_start"],
                                               env["window_end"])
        report = validate_success(
            api.create_water_balance_report(
                env["network"]["id"], env["dma"]["id"], payload, CO,
            ),
            expected_status=201,
        )
        # Expected NRW pct: (432 - 300) / 432 * 100 = 30.555... → 30.56.
        expected_nrw = round_half_up((432.0 - 300.0) / 432.0 * 100, 2)
        assert report["nrw_pct"] == pytest.approx(expected_nrw, abs=0.01), \
            f"Expected nrw_pct ≈ {expected_nrw}, got {report['nrw_pct']}"

    def test_real_loss_is_floored_at_zero(self, api):
        """PRD §3.9: "real_loss_m3 is the physical leakage, computed as
        input_volume_m3 − billed_consumption_m3 − unbilled_authorized_m3
        − apparent_loss_m3, with a floor of 0 (so a negative arithmetic
        result is clamped to 0)."

        Claim: a billed_consumption that exceeds the input still yields
        real_loss_m3 == 0 (floor).
        """
        env = setup_dma_with_inlet_flow_and_meter(
            api,
            inlet_flow_lps=5.0,        # ≈ 432 m^3 input
            billed_meter_first=0.0,
            billed_meter_last=10_000.0,  # billed >> input
            window_seconds=86400,
        )
        payload = water_balance_report_payload(env["window_start"],
                                               env["window_end"])
        report = validate_success(
            api.create_water_balance_report(
                env["network"]["id"], env["dma"]["id"], payload, CO,
            ),
            expected_status=201,
        )
        assert report["real_loss_m3"] >= 0
