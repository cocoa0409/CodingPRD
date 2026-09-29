"""Domain assertion helpers.

Each helper checks one PRD invariant so the tests can state the *business*
expectation once instead of repeating field-by-field comparisons.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BREACH_SEGMENTS
from .types import COMMON_FIELD_NAMES

TOLERANCE = 0.01


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """Every entity carries id, created_at, updated_at and version (PRD §2.5)."""
    for field in COMMON_FIELD_NAMES:
        assert field in entity, f"missing common field {field}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_created_unmodified(entity: Dict[str, Any]):
    """A never-mutated entity has version 1 and created_at == updated_at."""
    assert entity["version"] == 1, entity["version"]
    assert entity["created_at"] == entity["updated_at"], entity


def assert_meta_envelope(meta: Dict[str, Any]):
    """Envelope meta always carries a request id and an ISO-8601 timestamp."""
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta


def assert_pagination_meta(
    meta: Dict[str, Any], total_count: int, has_more: bool, limit: int, offset: int
):
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta
    assert meta["limit"] == limit, meta
    assert meta["offset"] == offset, meta


# --- Timer loop ---------------------------------------------------------------
def assert_pinned_targets(
    loop: Dict[str, Any],
    greet: int,
    order: int,
    pull_forward: int,
    window: int,
    total: Optional[int] = None,
):
    """The four pinned segment targets, and their sum, frozen at creation."""
    assert loop["greet_target_pinned"] == greet, loop
    assert loop["order_target_pinned"] == order, loop
    assert loop["pull_forward_target_pinned"] == pull_forward, loop
    assert loop["window_target_pinned"] == window, loop
    expected_total = total if total is not None else greet + order + pull_forward + window
    assert loop["target_total_seconds_pinned"] == expected_total, loop


def assert_loop_segments(
    loop: Dict[str, Any],
    greet_seconds: Optional[int] = None,
    order_seconds: Optional[int] = None,
    pull_forward_seconds: Optional[int] = None,
    window_seconds: Optional[int] = None,
    total_seconds: Optional[int] = None,
    adjusted_total_seconds: Optional[int] = None,
    merge_wait_seconds: Optional[int] = ...,  # type: ignore[assignment]
):
    """Measured segment durations. Pass a value to assert it, omit to skip.

    `merge_wait_seconds` accepts `None` explicitly, so its sentinel is `...`.
    """
    if greet_seconds is not None:
        assert loop["greet_seconds"] == greet_seconds, loop
    if order_seconds is not None:
        assert loop["order_seconds"] == order_seconds, loop
    if pull_forward_seconds is not None:
        assert loop["pull_forward_seconds"] == pull_forward_seconds, loop
    if window_seconds is not None:
        assert loop["window_seconds"] == window_seconds, loop
    if total_seconds is not None:
        assert loop["total_seconds"] == total_seconds, loop
    if adjusted_total_seconds is not None:
        assert loop["adjusted_total_seconds"] == adjusted_total_seconds, loop
    if merge_wait_seconds is not ...:
        assert loop["merge_wait_seconds"] == merge_wait_seconds, loop


def assert_breach_flags(loop: Dict[str, Any], expected: Sequence[str]):
    """breach_flags is the segment subset that exceeded its pinned target.

    The comparison is order-sensitive because the PRD fixes the segment order
    GREET, ORDER, PULL_FORWARD, WINDOW.
    """
    flags = loop["breach_flags"]
    assert isinstance(flags, list), flags
    for flag in flags:
        assert flag in BREACH_SEGMENTS, flag
    assert flags == list(expected), f"expected {list(expected)}, got {flags}"


def assert_loop_states(
    loop: Dict[str, Any],
    timing_state: Optional[str] = None,
    accuracy_state: Optional[str] = None,
):
    """The two loop dimensions advance independently, so they are checked apart."""
    if timing_state is not None:
        assert loop["timing_state"] == timing_state, loop
    if accuracy_state is not None:
        assert loop["accuracy_state"] == accuracy_state, loop


# --- Restaurant rollup --------------------------------------------------------
def assert_rollup(
    restaurant: Dict[str, Any],
    cars_closed_trailing: Optional[int] = None,
    cars_per_hour_observed: Optional[float] = None,
    cars_per_hour_effective: Optional[float] = None,
    volume_tier: Optional[str] = None,
    required_oot_count: Optional[int] = None,
    deployed_oot_count: Optional[int] = None,
    open_remake_count: Optional[int] = None,
    remake_cost_accrued_cents: Optional[int] = None,
    service_posture: Optional[str] = None,
    merge_slots_free: Optional[int] = None,
):
    """Checks any subset of the store rollup fields."""
    if cars_closed_trailing is not None:
        assert restaurant["cars_closed_trailing"] == cars_closed_trailing, restaurant
    if cars_per_hour_observed is not None:
        assert restaurant["cars_per_hour_observed"] == pytest.approx(
            cars_per_hour_observed, abs=TOLERANCE
        ), restaurant
    if cars_per_hour_effective is not None:
        assert restaurant["cars_per_hour_effective"] == pytest.approx(
            cars_per_hour_effective, abs=TOLERANCE
        ), restaurant
    if volume_tier is not None:
        assert restaurant["volume_tier"] == volume_tier, restaurant
    if required_oot_count is not None:
        assert restaurant["required_oot_count"] == required_oot_count, restaurant
    if deployed_oot_count is not None:
        assert restaurant["deployed_oot_count"] == deployed_oot_count, restaurant
    if open_remake_count is not None:
        assert restaurant["open_remake_count"] == open_remake_count, restaurant
    if remake_cost_accrued_cents is not None:
        assert (
            restaurant["remake_cost_accrued_cents"] == remake_cost_accrued_cents
        ), restaurant
    if service_posture is not None:
        assert restaurant["service_posture"] == service_posture, restaurant
    if merge_slots_free is not None:
        assert restaurant["merge_slots_free"] == merge_slots_free, restaurant


def assert_labor_ledger(
    restaurant: Dict[str, Any],
    committed: Optional[int] = None,
    available: Optional[int] = None,
):
    """The labor ledger identity: budget == committed + available (PRD §3.4)."""
    assert (
        restaurant["labor_minutes_budget"]
        == restaurant["labor_minutes_committed"] + restaurant["labor_minutes_available"]
    ), restaurant
    if committed is not None:
        assert restaurant["labor_minutes_committed"] == committed, restaurant
    if available is not None:
        assert restaurant["labor_minutes_available"] == available, restaurant


def assert_merge_capacity(restaurant: Dict[str, Any], free: int):
    """merge_slots_free never exceeds capacity and never goes negative."""
    assert restaurant["merge_slots_free"] == free, restaurant
    assert 0 <= restaurant["merge_slots_free"] <= restaurant["merge_slots_capacity"]


# --- Throughput report --------------------------------------------------------
def assert_report_metrics(
    report: Dict[str, Any],
    metric_basis: Optional[str] = None,
    cars_served: Optional[int] = None,
    cars_per_hour: Optional[float] = None,
    window_tier: Optional[str] = None,
    avg_metric_seconds: Optional[float] = ...,  # type: ignore[assignment]
    mean_pinned_target_seconds: Optional[float] = ...,  # type: ignore[assignment]
    target_total_seconds_effective: Optional[int] = ...,  # type: ignore[assignment]
    attainment_pct: Optional[float] = ...,  # type: ignore[assignment]
    attainment_band: Optional[str] = ...,  # type: ignore[assignment]
    open_remake_incident_count: Optional[int] = None,
    coaching_pool_points: Optional[int] = None,
):
    """Checks the report metric chain. Nullable fields use `...` as "skip"."""
    if metric_basis is not None:
        assert report["metric_basis"] == metric_basis, report
    if cars_served is not None:
        assert report["cars_served"] == cars_served, report
    if cars_per_hour is not None:
        assert report["cars_per_hour"] == pytest.approx(
            cars_per_hour, abs=TOLERANCE
        ), report
    if window_tier is not None:
        assert report["window_tier"] == window_tier, report
    if avg_metric_seconds is not ...:
        if avg_metric_seconds is None:
            assert report["avg_metric_seconds"] is None, report
        else:
            assert report["avg_metric_seconds"] == pytest.approx(
                avg_metric_seconds, abs=TOLERANCE
            ), report
    if mean_pinned_target_seconds is not ...:
        if mean_pinned_target_seconds is None:
            assert report["mean_pinned_target_seconds"] is None, report
        else:
            assert report["mean_pinned_target_seconds"] == pytest.approx(
                mean_pinned_target_seconds, abs=TOLERANCE
            ), report
    if target_total_seconds_effective is not ...:
        assert (
            report["target_total_seconds_effective"] == target_total_seconds_effective
        ), report
    if attainment_pct is not ...:
        if attainment_pct is None:
            assert report["attainment_pct"] is None, report
        else:
            assert report["attainment_pct"] == pytest.approx(
                attainment_pct, abs=TOLERANCE
            ), report
    if attainment_band is not ...:
        assert report["attainment_band"] == attainment_band, report
    if open_remake_incident_count is not None:
        assert (
            report["open_remake_incident_count"] == open_remake_incident_count
        ), report
    if coaching_pool_points is not None:
        assert report["coaching_pool_points"] == coaching_pool_points, report


def assert_empty_window_report(report: Dict[str, Any]):
    """A window with no qualifying cars: every derived metric is null."""
    assert report["cars_served"] == 0, report
    assert report["cars_per_hour"] == pytest.approx(0.0, abs=TOLERANCE), report
    assert report["avg_metric_seconds"] is None, report
    assert report["mean_pinned_target_seconds"] is None, report
    assert report["target_total_seconds_effective"] is None, report
    assert report["attainment_pct"] is None, report
    assert report["attainment_band"] is None, report
    assert report["coaching_pool_points"] == 0, report


# --- Coaching intervention ----------------------------------------------------
def assert_coaching_scoring(
    coaching: Dict[str, Any],
    segment_gap_seconds: Optional[float] = None,
    priority_score: Optional[float] = None,
    tier: Optional[str] = None,
):
    if segment_gap_seconds is not None:
        assert coaching["segment_gap_seconds"] == pytest.approx(
            segment_gap_seconds, abs=TOLERANCE
        ), coaching
    if priority_score is not None:
        assert coaching["priority_score"] == pytest.approx(
            priority_score, abs=TOLERANCE
        ), coaching
    if tier is not None:
        assert coaching["tier"] == tier, coaching


# --- Deployment ---------------------------------------------------------------
def assert_deployment_charge(
    deployment: Dict[str, Any],
    planned_minutes: Optional[int] = None,
    labor_minutes_charged: Optional[int] = None,
    released_at_is_null: Optional[bool] = None,
):
    if planned_minutes is not None:
        assert deployment["planned_minutes"] == planned_minutes, deployment
    if labor_minutes_charged is not None:
        assert deployment["labor_minutes_charged"] == labor_minutes_charged, deployment
    if released_at_is_null is not None:
        if released_at_is_null:
            assert deployment["released_at"] is None, deployment
        else:
            assert deployment["released_at"] is not None, deployment


# --- Generic helpers ----------------------------------------------------------
def assert_all_null(entity: Dict[str, Any], field_names: Iterable[str]):
    for field in field_names:
        assert entity[field] is None, f"{field} should be null: {entity}"


def assert_ids_are(items: List[Dict[str, Any]], expected_ids: Sequence[str]):
    """Listing order check by id, in the order the PRD declares."""
    assert [item["id"] for item in items] == list(expected_ids), items


def assert_distinct(values: Sequence[Any]):
    assert len(set(values)) == len(values), f"expected all distinct, got {values}"
