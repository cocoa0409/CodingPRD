"""Anomaly detection, severity classification, alert aggregation, and triage.

Covers PRD §3.5 (severity formulas, dedup), §3.6 (acknowledge / resolve /
suppress / investigation flow), and DMA posture cascades (PRD §2.8).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId, CO, CO_ALT,
    advance_clock, create_and_activate_pressure_device,
    get_dma, get_network,
    iso_from_epoch_ms, post_reading_payload,
    get_latest_alert_for_device,
    acknowledge_alert, resolve_alert, suppress_alert,
    setup_published_network_with_one_segment,
    setup_dma_with_n_critical_alerts,
    setup_alert_critical_on_open_dma,
    resolve_alert_payload, suppress_alert_payload,
    validate_error, validate_success,
)


# ===========================================================================
# Severity classification — PRD §3.5
# ===========================================================================
class TestPressureSeverityBoundaries:
    """PRD §3.5 deviation_pct thresholds: WARNING ∈ [15.0, 30.0), CRITICAL ∈ [30.0, ∞)."""

    def test_deviation_29_75_pct_is_warning(self, api):
        """PRD §3.5: "When this percentage is strictly less than 15.0,
        the severity is INFO; from 15.0 (inclusive) to 30.0 (exclusive)
        the severity is WARNING; at 30.0 and above the severity is
        CRITICAL."

        Claim: raw=519 against baseline 400 → 29.75% < 30 → WARNING.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 519.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        assert alert is not None, "Expected Alert from out-of-band reading"
        assert alert["severity"] == "WARNING", \
            f"deviation 29.75% should map to WARNING, got {alert['severity']}"

    def test_deviation_exactly_30_pct_is_critical(self, api):
        """PRD §3.5: "at 30.0 and above the severity is CRITICAL."

        # difficulty: boundary_precision_check/severity_critical_lower_edge_30_pct
        Claim: raw=520 against baseline 400 → exactly 30.0% → CRITICAL
        (lower edge inclusive).
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 520.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        assert alert is not None
        assert alert["severity"] == "CRITICAL", \
            f"deviation 30.0% should map to CRITICAL (>= 30), got {alert['severity']}"


class TestPressureSeverityDualBaseline:
    """PRD §3.5 dual-baseline variant.

    # difficulty: dual_variant_calc/alert_severity_baseline_dual_variant
    With no history, baseline is STATIC = midpoint(valid_range). PRD says
    that with >= 168 hours of bucketed history the baseline becomes
    DYNAMIC. The static-baseline arm is the one a fresh test can verify
    deterministically; the dynamic arm is asserted indirectly by the
    presence of baseline_used.kind on the resulting Alert.
    """

    def test_static_baseline_kind_captured_on_alert(self, api):
        """PRD §3.5: "When fewer than 168 hours of data exist in the
        bucket, the baseline falls back to STATIC and is the midpoint of
        valid_range_min and valid_range_max."
        PRD §3.5: "Every alert captures, at trigger time, the
        baseline_used object — recording whether the baseline was STATIC
        or DYNAMIC."

        Claim: with no historical readings, the resulting Alert has
        baseline_used.kind == 'STATIC' and the baseline threshold equals
        the midpoint of valid_range.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 520.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        assert alert is not None
        baseline = alert.get("baseline_used")
        assert baseline is not None
        assert baseline.get("kind") == "STATIC", \
            f"Expected STATIC baseline, got {baseline}"
        # PRD §3.5: "the midpoint of valid_range_min and valid_range_max."
        assert baseline.get("threshold") == pytest.approx(400.0, abs=0.01)


class TestAlertDedupWindow:
    """PRD §3.5 alert aggregation dedup.

    # difficulty: resource_temporal_overlap/alert_dedup_window_900s_inclusive
    """

    def test_breaches_within_900s_merge_into_one_alert(self, api):
        """PRD §3.5: "the system compares the new reading's ingested_at
        to the alert's last_breach_at. If the difference is at most 900
        seconds (the 15-minute dedup window, with the equality boundary
        inclusive), the new reading is merged: occurrence_count is
        incremented by 1, last_breach_at is advanced to the new reading's
        ingested_at."

        Claim: two CRITICAL readings within the 900s dedup window
        produce one Alert with occurrence_count >= 2.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        t0 = net["clock_epoch_ms"] - 10_000
        ob1 = iso_from_epoch_ms(t0)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(ob1, 520.0),
                             CO),
            expected_status=201,
        )
        # Second reading 60 seconds later — well within 900s.
        ob2 = iso_from_epoch_ms(t0 + 60_000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(ob2, 520.0),
                             CO),
            expected_status=201,
        )

        # Now list alerts for this device — should be exactly one.
        body = api.list_alerts(net_id, CO,
                               params={"dma_id": base["dma"]["id"]}).json()
        same_device = [a for a in body["data"]
                       if a["trigger_device_id"] == dev["id"]]
        assert len(same_device) == 1, \
            f"Within dedup window, expected exactly 1 alert, got {len(same_device)}"
        assert same_device[0]["occurrence_count"] >= 2, \
            f"occurrence_count should advance on merge, got {same_device[0]['occurrence_count']}"


# ===========================================================================
# DMA posture cascade — PRD §2.8 (compensating-invariant)
# ===========================================================================
class TestDMAPostureCascade:
    """PRD §2.8: open_critical_alert_count drives status transitions.

    # difficulty: transitive_cascade/critical_alert_dma_freeze_cascade
    # difficulty: compensating_invariant/dma_critical_alert_counter_invariant_under_resolve_suppress
    """

    def test_one_critical_alert_moves_dma_open_to_restricted(self, api):
        """PRD §2.8: "When open_critical_alert_count crosses from zero to
        one or more, the DMA transitions from OPEN to RESTRICTED."
        """
        env = setup_alert_critical_on_open_dma(api)
        net_id = env["network"]["id"]
        dev = env["device"]

        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 520.0),
                             CO),
            expected_status=201,
        )
        dma = get_dma(api, net_id, env["dma"]["id"])
        assert dma["open_critical_alert_count"] >= 1
        assert dma["status"] == "RESTRICTED", \
            f"DMA should be RESTRICTED after first CRITICAL, got {dma['status']}"

    def test_three_critical_alerts_freeze_dma(self, api):
        """PRD §2.8: "when it reaches three or more, the DMA transitions
        from RESTRICTED to FROZEN."
        """
        env = setup_dma_with_n_critical_alerts(api, n_critical=3)
        dma = env["dma"]
        assert dma["open_critical_alert_count"] >= 3
        assert dma["status"] == "FROZEN", \
            f"DMA should be FROZEN at count>=3, got {dma['status']}"

    def test_resolve_decrements_counter_and_relaxes_dma(self, api):
        """PRD §2.8: "when it drops below three the DMA transitions back
        from FROZEN to RESTRICTED; and when it falls to zero the DMA
        transitions back from RESTRICTED to OPEN."

        Claim: open three CRITICAL alerts → FROZEN; suppress one → count
        decrements; suppress all → count == 0 and DMA back to OPEN.
        """
        env = setup_dma_with_n_critical_alerts(api, n_critical=3)
        net_id = env["network"]["id"]
        alerts = env["critical_alerts"]
        dma_id = env["dma"]["id"]

        # Suppress one — counter must drop.
        suppress_alert(api, net_id, alerts[0]["id"], note="false positive")
        dma = get_dma(api, net_id, dma_id)
        assert dma["open_critical_alert_count"] == 2
        assert dma["status"] == "RESTRICTED"

        # Suppress remainder — counter goes to 0, DMA returns OPEN.
        for a in alerts[1:]:
            suppress_alert(api, net_id, a["id"])
        dma = get_dma(api, net_id, dma_id)
        assert dma["open_critical_alert_count"] == 0
        assert dma["status"] == "OPEN"


# ===========================================================================
# Alert triage workflow — PRD §3.6
# ===========================================================================
class TestAlertTriage:

    def test_acknowledge_open_warning_alert_succeeds(self, api):
        """PRD §3.6: "Acknowledging the alert advances it from OPEN to
        ACKNOWLEDGED."
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        # raw=480 → 20% deviation → WARNING
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 480.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        assert alert["severity"] == "WARNING"
        ack = validate_success(
            api.acknowledge_alert(net_id, alert["id"], CO)
        )
        assert ack["status"] == "ACKNOWLEDGED"

    def test_suppress_open_alert_records_resolution_note(self, api):
        """PRD §3.6: "Suppression takes an alert directly to SUPPRESSED
        from either OPEN or ACKNOWLEDGED. From OPEN, the request body
        must supply a resolution_note."

        Claim: suppressing an OPEN alert with a non-empty resolution_note
        succeeds and the alert transitions to SUPPRESSED.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 480.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        suppressed = validate_success(
            api.suppress_alert(net_id, alert["id"],
                               suppress_alert_payload("false alarm"), CO)
        )
        assert suppressed["status"] == "SUPPRESSED"
