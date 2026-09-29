"""Domain assertions expressed in the vocabulary of the PRD."""

from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MONEY_TOLERANCE = 0
PCT_TOLERANCE = 0.005
FLOW_TOLERANCE = 0.0005


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """Every versioned resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id is not a uuid: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int) and row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_fields(row: Dict[str, Any]):
    """A consumable draw carries id and created_at but no updated_at and no version."""
    assert is_valid_uuid(row["id"]), f"id is not a uuid: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "updated_at" not in row, "consumable draw must not expose updated_at"
    assert "version" not in row, "consumable draw must not expose version"


def assert_money(actual: Any, expected: int, label: str = "amount"):
    """Money is an integer count of cents, compared exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer cent count, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_pct(actual: Any, expected: float, label: str = "percentage"):
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_flow(actual: Any, expected: float, label: str = "design_flow_mgd"):
    assert actual == pytest.approx(expected, abs=FLOW_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_project_state(
    project: Dict[str, Any],
    status: Optional[str] = None,
    delivery_posture: Optional[str] = None,
    guarantee_status: Optional[str] = None,
):
    if status is not None:
        assert project["status"] == status, (
            f"project status: expected {status}, got {project['status']}"
        )
    if delivery_posture is not None:
        assert project["delivery_posture"] == delivery_posture, (
            f"delivery_posture: expected {delivery_posture}, "
            f"got {project['delivery_posture']}"
        )
    if guarantee_status is not None:
        assert project["guarantee_status"] == guarantee_status, (
            f"guarantee_status: expected {guarantee_status}, "
            f"got {project['guarantee_status']}"
        )


def assert_skid_state(
    skid: Dict[str, Any],
    mechanical_status: Optional[str] = None,
    controls_status: Optional[str] = None,
    fat_readiness: Optional[str] = None,
    rework_count: Optional[int] = None,
):
    if mechanical_status is not None:
        assert skid["mechanical_status"] == mechanical_status, skid["mechanical_status"]
    if controls_status is not None:
        assert skid["controls_status"] == controls_status, skid["controls_status"]
    if fat_readiness is not None:
        assert skid["fat_readiness"] == fat_readiness, skid["fat_readiness"]
    if rework_count is not None:
        assert skid["rework_count"] == rework_count, skid["rework_count"]


def assert_reserve_conserved(agreement: Dict[str, Any]):
    """The PRD invariant: committed accrual plus available always equals funded."""
    total = (
        agreement["reserve_committed_accrual_cents"]
        + agreement["reserve_available_cents"]
    )
    assert total == agreement["reserve_funded_cents"], (
        "reserve_committed_accrual_cents + reserve_available_cents must equal "
        f"reserve_funded_cents, got {total} vs {agreement['reserve_funded_cents']}"
    )


def assert_settlement_variance(agreement: Dict[str, Any]):
    """settlement_variance_cents is settled minus accrual."""
    expected = (
        agreement["reserve_committed_settled_cents"]
        - agreement["reserve_committed_accrual_cents"]
    )
    assert agreement["settlement_variance_cents"] == expected, (
        f"settlement_variance_cents: expected {expected}, "
        f"got {agreement['settlement_variance_cents']}"
    )


def assert_bay_ledger(bay: Dict[str, Any], expected_footprint_minutes: float):
    assert bay["reserved_footprint_minutes"] == pytest.approx(
        expected_footprint_minutes, abs=0.01
    ), (
        f"reserved_footprint_minutes: expected {expected_footprint_minutes}, "
        f"got {bay['reserved_footprint_minutes']}"
    )


def assert_row_ids(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]):
    assert [row["id"] for row in rows] == list(expected_ids)


def find_row(rows: Iterable[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError(f"row {row_id} not present in listing")
