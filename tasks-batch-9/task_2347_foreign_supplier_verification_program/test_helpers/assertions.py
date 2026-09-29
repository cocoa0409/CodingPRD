"""Domain assertion helpers built on the generic framework assertions."""

from typing import Any, Dict, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import DECIMAL_TOLERANCE
from .types import IMMUTABLE_ENTITY_KEYS, VERSIONED_ENTITY_KEYS


def assert_money(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a 2-decimal numeric field equals the expected amount."""
    assert actual is not None, f"{label} is missing"
    assert float(actual) == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_decimals(actual: Any, label: str = "value") -> None:
    """Assert a numeric field carries at most two decimal places."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), 2) == pytest.approx(float(actual), abs=1e-9), (
        f"{label}: {actual} carries more than two decimal places"
    )


def assert_versioned_row(row: Dict[str, Any], label: str = "row") -> None:
    """Assert the four common fields of a versioned row are present and well formed."""
    for key in VERSIONED_ENTITY_KEYS:
        assert key in row, f"{label} is missing the common field {key!r}"
    assert is_valid_uuid(row["id"]), f"{label}.id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"{label}.created_at is not ISO 8601: {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"{label}.updated_at is not ISO 8601: {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), f"{label}.version must be an integer"
    assert row["version"] >= 1, f"{label}.version must start at 1"


def assert_immutable_row(row: Dict[str, Any], label: str = "row") -> None:
    """Assert an immutable row carries only ``id`` and ``created_at``."""
    for key in IMMUTABLE_ENTITY_KEYS:
        assert key in row, f"{label} is missing the common field {key!r}"
    assert is_valid_uuid(row["id"]), f"{label}.id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"{label}.created_at is not ISO 8601: {row['created_at']!r}"
    )
    assert "updated_at" not in row, f"{label} must not expose updated_at"
    assert "version" not in row, f"{label} must not expose version"


def assert_pair_dimensions(
    pair: Dict[str, Any],
    verification_status: Optional[str] = None,
    entry_eligibility_status: Optional[str] = None,
    exemption_status: Optional[str] = None,
) -> None:
    """Assert any subset of the pair's three independent status dimensions."""
    if verification_status is not None:
        assert pair["verification_status"] == verification_status, (
            f"verification_status: expected {verification_status}, "
            f"got {pair['verification_status']}"
        )
    if entry_eligibility_status is not None:
        assert pair["entry_eligibility_status"] == entry_eligibility_status, (
            f"entry_eligibility_status: expected {entry_eligibility_status}, "
            f"got {pair['entry_eligibility_status']}"
        )
    if exemption_status is not None:
        assert pair["exemption_status"] == exemption_status, (
            f"exemption_status: expected {exemption_status}, got {pair['exemption_status']}"
        )


def assert_importer_rollup(
    importer: Dict[str, Any],
    blocked_pair_count: Optional[int] = None,
    open_corrective_action_count: Optional[int] = None,
    qualified_individual_designated: Optional[bool] = None,
    program_status: Optional[str] = None,
) -> None:
    """Assert any subset of the importer's program roll-up fields."""
    if blocked_pair_count is not None:
        assert importer["blocked_pair_count"] == blocked_pair_count, (
            f"blocked_pair_count: expected {blocked_pair_count}, "
            f"got {importer['blocked_pair_count']}"
        )
    if open_corrective_action_count is not None:
        assert importer["open_corrective_action_count"] == open_corrective_action_count, (
            f"open_corrective_action_count: expected {open_corrective_action_count}, "
            f"got {importer['open_corrective_action_count']}"
        )
    if qualified_individual_designated is not None:
        assert importer["qualified_individual_designated"] is qualified_individual_designated, (
            f"qualified_individual_designated: expected {qualified_individual_designated}, "
            f"got {importer['qualified_individual_designated']}"
        )
    if program_status is not None:
        assert importer["program_status"] == program_status, (
            f"program_status: expected {program_status}, got {importer['program_status']}"
        )


def assert_hazard_scores(
    hazard: Dict[str, Any], risk_score: float, requires_control: bool
) -> None:
    assert_money(hazard["risk_score"], risk_score, "hazard.risk_score")
    assert hazard["requires_control"] is requires_control, (
        f"hazard.requires_control: expected {requires_control}, "
        f"got {hazard['requires_control']}"
    )


def assert_supplier_performance(
    supplier: Dict[str, Any],
    provisional: Optional[float] = None,
    final: Optional[float] = None,
    weight_total: Optional[float] = None,
    status: Optional[str] = None,
) -> None:
    if provisional is not None:
        assert_money(
            supplier["performance_score_provisional"],
            provisional,
            "performance_score_provisional",
        )
    if final is not None:
        assert_money(supplier["performance_score_final"], final, "performance_score_final")
    if weight_total is not None:
        assert_money(
            supplier["performance_sample_weight_total"],
            weight_total,
            "performance_sample_weight_total",
        )
    if status is not None:
        assert supplier["status"] == status, (
            f"supplier.status: expected {status}, got {supplier['status']}"
        )


def assert_ids(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Assert a listing contains exactly the expected ids, order-insensitively."""
    assert sorted(row["id"] for row in rows) == sorted(expected_ids), (
        f"expected ids {sorted(expected_ids)}, got {sorted(row['id'] for row in rows)}"
    )
