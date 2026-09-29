"""Domain assertion helpers.

These wrap the shared structural helpers with the vocabulary of this service so
that a test body reads as a claim about deployments, ledgers and scores rather
than as a pile of dictionary lookups.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    HEALTH_STATES,
    ROLLOUT_STATES,
)

# Tolerance for a value the PRD pins to two decimals.
TWO_DP = 0.005
# Tolerance for a value the PRD pins to four decimals.
FOUR_DP = 0.00005


# ─── System-field shapes ───


def assert_common_fields(data: Dict[str, Any]) -> None:
    """Assert the id / created_at / updated_at / version quartet (PRD §2.4)."""
    assert is_valid_uuid(data.get("id")), f"id is not a bare UUID: {data.get('id')!r}"
    assert not str(data["id"]).lower().startswith(
        ("mv_", "ds_", "dep_", "se_", "mw_")
    ), "identifier must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"created_at is not ISO 8601 UTC: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at")), (
        f"updated_at is not ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Assert an append-only ledger row carries only `id` and `created_at`.

    PRD §2.4 puts the traffic-ramp ledger rows outside the families that carry
    `updated_at` and `version`, so their presence is itself a violation.
    """
    assert is_valid_uuid(data.get("id")), f"id is not a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"created_at is not ISO 8601 UTC: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        "an append-only ledger row must not carry updated_at"
    )
    assert "version" not in data, "an append-only ledger row must not carry version"


def assert_error_meta_is_minimal(body: Dict[str, Any]) -> None:
    """PRD §2.2: an error response's meta carries only the two request fields."""
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """PRD §2.2: api_request_id is prefixed `req_`, timestamp is ISO 8601 UTC."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp is not ISO 8601 UTC: "
        f"{meta['api_request_timestamp']!r}"
    )


# ─── Numeric precision ───


def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    assert actual == pytest.approx(expected, abs=TWO_DP), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_dp(actual: Any, expected: float, label: str = "value") -> None:
    assert actual == pytest.approx(expected, abs=FOUR_DP), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """A percentage the PRD pins to two decimals."""
    assert_two_dp(actual, expected, label)


# ─── Registry, snapshot and version shapes ───


def assert_dataset_state(
    data: Dict[str, Any],
    approval_state: Optional[str] = None,
    dependent_version_count: Optional[int] = None,
    pii_review_passed: Optional[bool] = None,
) -> None:
    if approval_state is not None:
        assert data["approval_state"] == approval_state, (
            f"expected approval_state {approval_state}, got {data['approval_state']}"
        )
    if dependent_version_count is not None:
        assert data["dependent_version_count"] == dependent_version_count, (
            f"expected dependent_version_count {dependent_version_count}, "
            f"got {data['dependent_version_count']}"
        )
    if pii_review_passed is not None:
        assert data["pii_review_passed"] is pii_review_passed


def assert_version_state(
    data: Dict[str, Any],
    approval_state: Optional[str] = None,
    blocked_reason: Optional[Any] = "__unset__",
    revalidation_due_at: Optional[Any] = "__unset__",
    evaluation_sample_budget: Optional[int] = None,
) -> None:
    if approval_state is not None:
        assert data["approval_state"] == approval_state, (
            f"expected approval_state {approval_state}, got {data['approval_state']}"
        )
    if blocked_reason != "__unset__":
        assert data["blocked_reason"] == blocked_reason, (
            f"expected blocked_reason {blocked_reason!r}, "
            f"got {data['blocked_reason']!r}"
        )
    if revalidation_due_at != "__unset__":
        assert data["revalidation_due_at"] == revalidation_due_at, (
            f"expected revalidation_due_at {revalidation_due_at!r}, "
            f"got {data['revalidation_due_at']!r}"
        )
    if evaluation_sample_budget is not None:
        assert data["evaluation_sample_budget"] == evaluation_sample_budget, (
            f"expected evaluation_sample_budget {evaluation_sample_budget}, "
            f"got {data['evaluation_sample_budget']}"
        )


# ─── Deployment and traffic ledger ───


def assert_deployment_state(
    data: Dict[str, Any],
    rollout_state: Optional[str] = None,
    health_state: Optional[str] = None,
    traffic_pct: Optional[float] = None,
    ramp_step_index: Optional[int] = None,
    cumulative_ramp_delta_pct: Optional[float] = None,
    manual_override_active: Optional[bool] = None,
) -> None:
    if rollout_state is not None:
        assert rollout_state in ROLLOUT_STATES, f"unknown rollout state {rollout_state}"
        assert data["rollout_state"] == rollout_state, (
            f"expected rollout_state {rollout_state}, got {data['rollout_state']}"
        )
    if health_state is not None:
        assert health_state in HEALTH_STATES, f"unknown health state {health_state}"
        assert data["health_state"] == health_state, (
            f"expected health_state {health_state}, got {data['health_state']}"
        )
    if traffic_pct is not None:
        assert_pct(data["traffic_pct"], traffic_pct, "traffic_pct")
    if ramp_step_index is not None:
        assert data["ramp_step_index"] == ramp_step_index, (
            f"expected ramp_step_index {ramp_step_index}, "
            f"got {data['ramp_step_index']}"
        )
    if cumulative_ramp_delta_pct is not None:
        assert_pct(
            data["cumulative_ramp_delta_pct"],
            cumulative_ramp_delta_pct,
            "cumulative_ramp_delta_pct",
        )
    if manual_override_active is not None:
        assert data["manual_override_active"] is manual_override_active


def assert_allocated_traffic(data: Dict[str, Any], expected: float) -> None:
    """Assert a serving cluster's recomputed traffic ledger."""
    assert_pct(data["allocated_traffic_pct"], expected, "allocated_traffic_pct")


def assert_ramp_step_row(
    row: Dict[str, Any],
    step_index: Optional[int] = None,
    from_traffic_pct: Optional[float] = None,
    to_traffic_pct: Optional[float] = None,
    delta_pct: Optional[float] = None,
    reason: Optional[str] = None,
    health_state_at_step: Optional[str] = None,
) -> None:
    if step_index is not None:
        assert row["step_index"] == step_index, (
            f"expected step_index {step_index}, got {row['step_index']}"
        )
    if from_traffic_pct is not None:
        assert_pct(row["from_traffic_pct"], from_traffic_pct, "from_traffic_pct")
    if to_traffic_pct is not None:
        assert_pct(row["to_traffic_pct"], to_traffic_pct, "to_traffic_pct")
    if delta_pct is not None:
        assert_pct(row["delta_pct"], delta_pct, "delta_pct")
    if reason is not None:
        assert row["reason"] == reason, (
            f"expected reason {reason}, got {row['reason']}"
        )
    if health_state_at_step is not None:
        assert row["health_state_at_step"] == health_state_at_step


def assert_ledger_reasons(rows: Sequence[Dict[str, Any]], reasons: List[str]) -> None:
    """Assert the ledger's reason sequence in ascending created_at order."""
    actual = [row["reason"] for row in rows]
    assert actual == reasons, f"expected ledger reasons {reasons}, got {actual}"


def assert_deltas_sum_to(rows: Sequence[Dict[str, Any]], expected: float) -> None:
    total = sum(row["delta_pct"] for row in rows)
    assert_pct(total, expected, "sum of ledger delta_pct")


# ─── Scores ───


def assert_health_score(
    data: Dict[str, Any],
    health_score: Optional[float] = None,
    variant: Optional[str] = None,
    baseline_delta_pct: Optional[float] = None,
) -> None:
    if health_score is not None:
        assert_two_dp(data["health_score"], health_score, "health_score")
    if variant is not None:
        key = "health_score_variant" if "health_score_variant" in data else "score_variant"
        assert data[key] == variant, f"expected variant {variant}, got {data[key]}"
    if baseline_delta_pct is not None:
        assert_two_dp(
            data["baseline_delta_pct"], baseline_delta_pct, "baseline_delta_pct"
        )


def assert_drift_outcome(
    data: Dict[str, Any],
    drift_index: Optional[float] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    effective_baseline_mode: Optional[str] = None,
    windows_used_count: Optional[int] = None,
    expected_bin_proportions: Optional[List[float]] = None,
) -> None:
    if drift_index is not None:
        assert_four_dp(data["drift_index"], drift_index, "drift_index")
    if severity is not None:
        assert data["severity"] == severity, (
            f"expected severity {severity}, got {data['severity']}"
        )
    if status is not None:
        assert data["status"] == status, (
            f"expected status {status}, got {data['status']}"
        )
    if effective_baseline_mode is not None:
        assert data["effective_baseline_mode"] == effective_baseline_mode
    if windows_used_count is not None:
        assert data["windows_used_count"] == windows_used_count, (
            f"expected windows_used_count {windows_used_count}, "
            f"got {data['windows_used_count']}"
        )
    if expected_bin_proportions is not None:
        actual = data["expected_bin_proportions"]
        assert len(actual) == len(expected_bin_proportions), (
            f"expected {len(expected_bin_proportions)} expected bins, "
            f"got {len(actual)}"
        )
        for index, want in enumerate(expected_bin_proportions):
            assert_four_dp(actual[index], want, f"expected_bin_proportions[{index}]")


def assert_skew_outcome(
    data: Dict[str, Any],
    max_skew_ratio: Optional[float] = None,
    max_skew_feature: Optional[Any] = "__unset__",
    status: Optional[str] = None,
    missing_features: Optional[List[str]] = None,
) -> None:
    if max_skew_ratio is not None:
        assert_four_dp(data["max_skew_ratio"], max_skew_ratio, "max_skew_ratio")
    if max_skew_feature != "__unset__":
        assert data["max_skew_feature"] == max_skew_feature, (
            f"expected max_skew_feature {max_skew_feature!r}, "
            f"got {data['max_skew_feature']!r}"
        )
    if status is not None:
        assert data["status"] == status, (
            f"expected status {status}, got {data['status']}"
        )
    if missing_features is not None:
        assert data["missing_features"] == missing_features, (
            f"expected missing_features {missing_features}, "
            f"got {data['missing_features']}"
        )


def assert_urgency_snapshot(
    data: Dict[str, Any],
    base_urgency: Optional[float] = None,
    escalation_tier_bonus_pct: Optional[int] = None,
    total_urgency: Optional[float] = None,
    priority_band: Optional[str] = None,
    retrain_required: Optional[bool] = None,
    stale_after: Optional[str] = None,
) -> None:
    if base_urgency is not None:
        assert_two_dp(data["base_urgency"], base_urgency, "base_urgency")
    if escalation_tier_bonus_pct is not None:
        assert data["escalation_tier_bonus_pct"] == escalation_tier_bonus_pct, (
            f"expected escalation_tier_bonus_pct {escalation_tier_bonus_pct}, "
            f"got {data['escalation_tier_bonus_pct']}"
        )
    if total_urgency is not None:
        assert_two_dp(data["total_urgency"], total_urgency, "total_urgency")
    if priority_band is not None:
        assert data["priority_band"] == priority_band, (
            f"expected priority_band {priority_band}, got {data['priority_band']}"
        )
    if retrain_required is not None:
        assert data["retrain_required"] is retrain_required
    if stale_after is not None:
        assert data["stale_after"] == stale_after, (
            f"expected stale_after {stale_after}, got {data['stale_after']}"
        )


def assert_promotion_outcome(
    data: Dict[str, Any],
    status: Optional[str] = None,
    promotion_score: Optional[float] = None,
    criteria_failures: Optional[List[str]] = None,
    metric_lines: Optional[Dict[str, float]] = None,
) -> None:
    if status is not None:
        assert data["status"] == status, (
            f"expected status {status}, got {data['status']}"
        )
    if promotion_score is not None:
        assert_four_dp(data["promotion_score"], promotion_score, "promotion_score")
    if criteria_failures is not None:
        assert data["criteria_failures"] == criteria_failures, (
            f"expected criteria_failures {criteria_failures}, "
            f"got {data['criteria_failures']}"
        )
    if metric_lines is not None:
        actual = data["metric_lines"]
        assert set(actual.keys()) == set(metric_lines.keys()), (
            f"expected metric_lines keys {sorted(metric_lines)}, "
            f"got {sorted(actual)}"
        )
        for key, want in metric_lines.items():
            assert_four_dp(actual[key], want, f"metric_lines[{key}]")


def assert_sweep_counters(
    data: Dict[str, Any],
    evaluated_count: Optional[int] = None,
    created_count: Optional[int] = None,
    skipped_existing_count: Optional[int] = None,
    staled_trigger_count: Optional[int] = None,
) -> None:
    for name, want in (
        ("evaluated_count", evaluated_count),
        ("created_count", created_count),
        ("skipped_existing_count", skipped_existing_count),
        ("staled_trigger_count", staled_trigger_count),
    ):
        if want is not None:
            assert data[name] == want, f"expected {name} {want}, got {data[name]}"


# ─── Ordering ───


def assert_descending(values: Sequence[Any], label: str = "values") -> None:
    assert list(values) == sorted(values, reverse=True), (
        f"{label} are not in descending order: {list(values)}"
    )


def assert_ascending(values: Sequence[Any], label: str = "values") -> None:
    assert list(values) == sorted(values), (
        f"{label} are not in ascending order: {list(values)}"
    )


def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]
