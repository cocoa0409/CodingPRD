"""Domain assertion helpers built on the framework validators."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ALERT_REVIEW_MINUTES,
    ALERT_REQUIRED_VOTES,
    BURDEN_INDEX_CAP,
    HIGH_VALUE_INDEX_CEILING,
    LOW_VALUE_INDEX_FLOOR,
    REVIEW_INTERVAL_DAYS,
    REVIEW_MINUTES,
)


# --------------------------------------------------------------------------
# Common properties
# --------------------------------------------------------------------------


def assert_common_fields(record: Dict[str, Any]) -> None:
    """A governed artifact carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert_timestamp_format(record["created_at"])
    assert_timestamp_format(record["updated_at"])
    assert record["version"] == int(record["version"])
    assert record["version"] >= 1


def assert_append_only_fields(record: Dict[str, Any]) -> None:
    """An append-only observation carries only id and created_at of the four."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert_timestamp_format(record["created_at"])
    assert "updated_at" not in record, "append-only records have no updated_at"
    assert "version" not in record, "append-only records have no version"


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_limit: int,
    expected_offset: int,
    expected_total: int,
    expected_has_more: bool,
) -> None:
    """A list envelope carries limit, offset, total_count and has_more."""
    assert meta["limit"] == expected_limit
    assert meta["offset"] == expected_offset
    assert meta["total_count"] == expected_total
    assert meta["has_more"] is expected_has_more


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def assert_sorted_ascending(values: List[Any]) -> None:
    assert values == sorted(values), f"not ascending: {values}"


def assert_sorted_descending(values: List[Any]) -> None:
    assert values == sorted(values, reverse=True), f"not descending: {values}"


def assert_ids_in_order(records: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert [record["id"] for record in records] == expected_ids


# --------------------------------------------------------------------------
# Rounding discipline
# --------------------------------------------------------------------------


def assert_two_decimal_places(value: Optional[float]) -> None:
    """A stored two-decimal quantity must round-trip at two decimal places."""
    assert value is not None
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    assert round(float(value), 2) == float(value), f"{value} is not at 2dp"


def assert_four_decimal_places(value: Optional[float]) -> None:
    """A stored four-decimal quantity must round-trip at four decimal places."""
    assert value is not None
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    assert round(float(value), 4) == float(value), f"{value} is not at 4dp"


def assert_numeric_equals(actual: Any, expected: float, places: int = 2) -> None:
    """Compare a JSON number against an expected decimal value."""
    assert isinstance(actual, (int, float)) and not isinstance(
        actual, bool
    ), f"expected a JSON number, got {type(actual).__name__}"
    assert round(float(actual), places) == round(
        float(expected), places
    ), f"expected {expected}, got {actual}"


def assert_whole_integer(value: Any) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), f"{value} is not an integer"


# --------------------------------------------------------------------------
# Two-dimensional governance state
# --------------------------------------------------------------------------


def assert_order_set_states(
    order_set: Dict[str, Any], review_state: str, publication_state: str
) -> None:
    """Both order set dimensions are asserted together and never collapsed."""
    assert order_set["review_state"] == review_state, (
        f"review_state {order_set['review_state']} != {review_state}"
    )
    assert order_set["publication_state"] == publication_state, (
        f"publication_state {order_set['publication_state']} != {publication_state}"
    )


def assert_alert_states(
    alert: Dict[str, Any], review_state: str, lifecycle_state: str
) -> None:
    """Both alert dimensions are asserted together and never collapsed."""
    assert alert["review_state"] == review_state, (
        f"review_state {alert['review_state']} != {review_state}"
    )
    assert alert["lifecycle_state"] == lifecycle_state, (
        f"lifecycle_state {alert['lifecycle_state']} != {lifecycle_state}"
    )


# --------------------------------------------------------------------------
# Ledgers and conservation invariants
# --------------------------------------------------------------------------


def assert_workload_ledger(
    clinician: Dict[str, Any],
    assigned_minutes: int,
    remaining_minutes: int,
    open_assignment_count: int,
) -> None:
    """Assert the three workload counters and the capacity identity."""
    assert clinician["review_workload_assigned_minutes"] == assigned_minutes
    assert clinician["review_workload_remaining_minutes"] == remaining_minutes
    assert clinician["open_assignment_count"] == open_assignment_count
    assert_workload_identity(clinician)


def assert_workload_identity(clinician: Dict[str, Any]) -> None:
    """capacity == assigned + remaining, on every read."""
    assert (
        clinician["review_workload_capacity_minutes"]
        == clinician["review_workload_assigned_minutes"]
        + clinician["review_workload_remaining_minutes"]
    ), "capacity is not the sum of assigned and remaining minutes"


def assert_workload_matches_assignments(
    clinician: Dict[str, Any], assignments: List[Dict[str, Any]]
) -> None:
    """assigned_minutes equals the sum over ASSIGNED and CAST assignments."""
    expected = sum(
        assignment["estimated_minutes"]
        for assignment in assignments
        if assignment["reviewer_id"] == clinician["id"]
        and assignment["state"] in ("ASSIGNED", "CAST")
    )
    assert clinician["review_workload_assigned_minutes"] == expected, (
        f"assigned_minutes {clinician['review_workload_assigned_minutes']} != {expected}"
    )


def assert_firing_ledger(
    alert: Dict[str, Any], lifetime: int, windowed: int, unwindowed: int
) -> None:
    """Assert the three firing counters and the subtraction identity."""
    assert alert["lifetime_fire_count"] == lifetime
    assert alert["windowed_fire_count"] == windowed
    assert alert["unwindowed_fire_count"] == unwindowed
    assert_firing_ledger_identity(alert)


def assert_firing_ledger_identity(alert: Dict[str, Any]) -> None:
    """unwindowed is always lifetime minus windowed."""
    assert (
        alert["unwindowed_fire_count"]
        == alert["lifetime_fire_count"] - alert["windowed_fire_count"]
    ), "unwindowed_fire_count is not lifetime minus windowed"


def assert_windowed_matches_closed_windows(
    alert: Dict[str, Any], windows: List[Dict[str, Any]]
) -> None:
    """windowed_fire_count is the sum over CLOSED and FINALIZED windows."""
    expected = sum(
        window["fire_count"] for window in windows if window["state"] in ("CLOSED", "FINALIZED")
    )
    assert alert["windowed_fire_count"] == expected, (
        f"windowed_fire_count {alert['windowed_fire_count']} != {expected}"
    )


# --------------------------------------------------------------------------
# Burden window computation
# --------------------------------------------------------------------------


def assert_burden_window_counts(
    window: Dict[str, Any],
    fire_count: int,
    override_count: int,
    accept_count: int,
    distinct_fired: int,
    distinct_overriding: int,
) -> None:
    assert window["fire_count"] == fire_count
    assert window["override_count"] == override_count
    assert window["accept_count"] == accept_count
    assert window["distinct_fired_clinician_count"] == distinct_fired
    assert window["distinct_overriding_clinician_count"] == distinct_overriding


def assert_burden_computation(
    window: Dict[str, Any],
    override_rate: float,
    volume_factor: float,
    burden_index: float,
    clinician_weighted_index: float,
    classification: str,
) -> None:
    """Assert the fire-weighted rate/factor at 4dp and both indices at 2dp."""
    assert_numeric_equals(window["override_rate"], override_rate, 4)
    assert_four_decimal_places(window["override_rate"])
    assert_numeric_equals(window["volume_factor"], volume_factor, 4)
    assert_four_decimal_places(window["volume_factor"])
    assert_numeric_equals(window["burden_index"], burden_index, 2)
    assert_two_decimal_places(window["burden_index"])
    assert_numeric_equals(
        window["burden_index_clinician_weighted"], clinician_weighted_index, 2
    )
    assert_two_decimal_places(window["burden_index_clinician_weighted"])
    assert window["burden_classification"] == classification
    assert float(window["burden_index"]) <= BURDEN_INDEX_CAP


def assert_classification_from_index(window: Dict[str, Any]) -> None:
    """Re-derive the classification from fire_count and the fire-weighted index."""
    if window["fire_count"] == 0:
        expected = "NO_SIGNAL"
    elif float(window["burden_index"]) >= LOW_VALUE_INDEX_FLOOR:
        expected = "LOW_VALUE"
    elif float(window["burden_index"]) <= HIGH_VALUE_INDEX_CEILING:
        expected = "HIGH_VALUE"
    else:
        expected = "MONITOR"
    assert window["burden_classification"] == expected


def assert_window_reset(window: Dict[str, Any], reopen_count: int) -> None:
    """A reopened window is OPEN with every count zeroed and every derived null."""
    assert window["state"] == "OPEN"
    assert window["fire_count"] == 0
    assert window["override_count"] == 0
    assert window["accept_count"] == 0
    assert window["distinct_fired_clinician_count"] == 0
    assert window["distinct_overriding_clinician_count"] == 0
    assert window["override_rate"] is None
    assert window["volume_factor"] is None
    assert window["burden_index"] is None
    assert window["burden_index_clinician_weighted"] is None
    assert window["burden_classification"] is None
    assert window["closure_reason"] is None
    assert window["closed_at"] is None
    assert window["reopen_count"] == reopen_count


# --------------------------------------------------------------------------
# Review pricing and quorum
# --------------------------------------------------------------------------


def assert_order_set_review_minutes(
    assignment: Dict[str, Any], review_kind: str, risk_class: str
) -> None:
    """An order-set assignment is priced from review_kind and the risk snapshot."""
    assert assignment["risk_class_snapshot"] == risk_class
    assert assignment["estimated_minutes"] == REVIEW_MINUTES[review_kind][risk_class]


def assert_alert_review_minutes(assignment: Dict[str, Any], severity_tier: str) -> None:
    """An alert assignment is priced by tier."""
    assert assignment["estimated_minutes"] == ALERT_REVIEW_MINUTES[severity_tier]


def assert_alert_required_votes(alert: Dict[str, Any]) -> None:
    """required_approval_votes comes from the severity tier table."""
    assert alert["required_approval_votes"] == ALERT_REQUIRED_VOTES[alert["severity_tier"]]


def assert_peer_stage_counters(
    order_set: Dict[str, Any],
    required_votes: Optional[int],
    cast_count: int,
    approve_ratio: Optional[float],
) -> None:
    assert order_set["peer_required_votes"] == required_votes
    assert order_set["peer_cast_count"] == cast_count
    if approve_ratio is None:
        assert order_set["peer_approve_ratio"] is None
    else:
        assert_numeric_equals(order_set["peer_approve_ratio"], approve_ratio, 4)
        assert_four_decimal_places(order_set["peer_approve_ratio"])


def assert_specialty_stage_counters(
    order_set: Dict[str, Any],
    required_votes: Optional[int],
    cast_count: int,
    approve_ratio: Optional[float],
) -> None:
    assert order_set["specialty_required_votes"] == required_votes
    assert order_set["specialty_cast_count"] == cast_count
    if approve_ratio is None:
        assert order_set["specialty_approve_ratio"] is None
    else:
        assert_numeric_equals(order_set["specialty_approve_ratio"], approve_ratio, 4)
        assert_four_decimal_places(order_set["specialty_approve_ratio"])


def assert_vote_preserved_on_void(assignment: Dict[str, Any], vote: str) -> None:
    """A voided assignment keeps the vote it recorded, for audit."""
    assert assignment["state"] == "VOIDED"
    assert assignment["vote"] == vote


# --------------------------------------------------------------------------
# Review schedule dates
# --------------------------------------------------------------------------


def assert_review_schedule(
    record: Dict[str, Any],
    review_due_date: str,
    expiration_at: str,
    archive_eligible_at: Optional[str] = None,
) -> None:
    """The three schedule dates as computed from the anchor instant."""
    assert record["review_due_date"] == review_due_date
    assert record["expiration_at"] == expiration_at
    if archive_eligible_at is not None:
        assert record["archive_eligible_at"] == archive_eligible_at


def assert_review_interval_days(risk_class: str, expected_days: int) -> None:
    assert REVIEW_INTERVAL_DAYS[risk_class] == expected_days


# --------------------------------------------------------------------------
# Sweep response
# --------------------------------------------------------------------------


SWEEP_COUNT_KEYS = (
    "tasks_marked_overdue",
    "tasks_expired",
    "order_sets_marked_expiring",
    "order_sets_expired",
    "order_sets_archived",
    "alerts_suspended",
    "alerts_retired",
    "burden_windows_closed",
    "downtime_events_closed",
)


def assert_sweep_counts(result: Dict[str, Any], **expected: int) -> None:
    """Assert the named sweep counts; unnamed counts are not constrained."""
    assert is_iso8601_timestamp(result["swept_at"])
    for key, value in expected.items():
        assert key in SWEEP_COUNT_KEYS, f"{key} is not a sweep count"
        assert result[key] == value, f"{key} {result[key]} != {value}"


def assert_all_sweep_counts_zero(result: Dict[str, Any]) -> None:
    for key in SWEEP_COUNT_KEYS:
        assert result[key] == 0, f"{key} should be 0, got {result[key]}"
