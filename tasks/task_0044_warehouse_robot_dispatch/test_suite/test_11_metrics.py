"""Throughput, utilisation, fault-rate, and bottleneck-zone metrics.

PRD section 3.11 governs the metrics report. Section 2.9 governs
precision (ratios to 4dp, durations to 2dp).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_ratio_4dp,
    create_fleet,
    setup_empty_fleet_for_metrics,
    validate_success,
)


class TestMetricsEmptySet:
    def test_empty_fleet_metrics_returns_zero_completion_rate(
        self, operator_headers
    ):
        """PRD section 3.11: 'The task completion rate is the count of
        tasks whose status is COMPLETED and whose completed_at falls in
        window, divided by the maximum of one and the count of tasks
        whose queued_at falls in window across all statuses...; the
        result is rounded half up to four decimal places.'

        Claim: with zero tasks, task_completion_rate == 0.0000 (no
        division by zero because the denominator is max(1, 0) == 1).
        """
        fleet = setup_empty_fleet_for_metrics()
        resp = api_client.get_metrics(
            fleet["id"], operator_headers, params={"window_seconds": 3600}
        )
        data = validate_success(resp, expected_status=200)
        assert "task_completion_rate" in data
        assert data["task_completion_rate"] == 0.0 or (
            float(data["task_completion_rate"]) == 0.0
        )
        assert_ratio_4dp(
            data["task_completion_rate"], label="task_completion_rate"
        )

    def test_empty_fleet_metrics_returns_zero_fault_rate(
        self, operator_headers
    ):
        """PRD section 3.11: 'The fault rate is the count of
        FaultIncident rows whose detected_at falls in window, divided
        by the maximum of one and the count of robots in the fleet,
        rounded half up to four decimal places.'

        Claim: with zero robots and zero faults, fault_rate == 0.0000.
        """
        fleet = setup_empty_fleet_for_metrics()
        resp = api_client.get_metrics(
            fleet["id"], operator_headers, params={"window_seconds": 3600}
        )
        data = validate_success(resp, expected_status=200)
        assert float(data["fault_rate"]) == 0.0
        assert_ratio_4dp(data["fault_rate"], label="fault_rate")

    def test_empty_fleet_metrics_returns_empty_bottleneck_list(
        self, operator_headers
    ):
        """PRD section 3.11: 'The bottleneck-zone analysis identifies
        congestion at choke points. For every MapNode whose kind is
        INTERSECTION or LIFT_POINT, the system counts SlotReservation
        rows ... then returns the top five by count, with ties broken
        by MapNode.code ascending.'

        Claim: with no intersection nodes and no reservations,
        bottleneck_zones is an empty list (not null).
        """
        fleet = setup_empty_fleet_for_metrics()
        resp = api_client.get_metrics(
            fleet["id"], operator_headers, params={"window_seconds": 3600}
        )
        data = validate_success(resp, expected_status=200)
        assert isinstance(data.get("bottleneck_zones"), list)
        assert data["bottleneck_zones"] == []
