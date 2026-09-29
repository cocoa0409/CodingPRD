"""Domain-specific assertion helpers layered on the framework's generics."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """Assert the common-field contract of PRD 2.4.

    "Every resource exposes an `id` ... Every resource exposes a `created_at` ...
    Most resources additionally carry `updated_at` ... and `version`, an integer
    that starts at 1 on creation and advances by exactly 1 on every mutation".
    """
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(
        row["created_at"]
    ), f"created_at is not ISO-8601: {row['created_at']!r}"
    assert is_iso8601_timestamp(
        row["updated_at"]
    ), f"updated_at is not ISO-8601: {row['updated_at']!r}"
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_created_defaults(row: Dict[str, Any]):
    """A freshly created row is at version 1."""
    assert_common_fields(row, expected_version=1)


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any], by: int = 1):
    """PRD 2.4: version "advances by exactly 1 on every mutation"."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version']} + {by}, got {after['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]):
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on an operation that must not mutate"
    )


def assert_test_result_shape(row: Dict[str, Any]):
    """PRD 2.4: "a TestResult row carries only `id` and `created_at`. It has
    neither `updated_at` nor `version`"."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), "created_at is not ISO-8601"
    assert "updated_at" not in row, "a TestResult must not carry updated_at"
    assert "version" not in row, "a TestResult must not carry version"


def assert_whole_cents(value: Any, field: str = "amount"):
    """Money is carried as integer cents (PRD 2.6)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )


def assert_two_decimal_quantity(value: Any, field: str = "quantity"):
    """Areas and dosages are carried at two decimal places (PRD 2.6)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} carries more than two decimal places: {value!r}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
):
    """PRD 2.3: list meta carries `limit`, `offset`, `total_count`, `has_more`."""
    assert isinstance(meta["total_count"], int), "total_count must be an integer"
    assert isinstance(meta["has_more"], bool), "has_more must be a boolean"
    assert isinstance(meta["limit"], int), "limit must be an integer"
    assert isinstance(meta["offset"], int), "offset must be an integer"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more


def assert_created_at_ascending(rows: List[Dict[str, Any]]):
    """PRD 2.3: "Every collection is ordered by `created_at` ascending"."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"collection is not created_at ascending: {stamps}"


def assert_blend_metrics(
    formulation: Dict[str, Any],
    total_phr: float,
    blended_cost_per_kg_cents: int,
    performance_score: float,
    indentation_resistance_class: str,
):
    """Assert the four externally visible blend figures of PRD 3.1 together."""
    assert formulation["total_phr"] == total_phr, (
        f"total_phr {formulation['total_phr']} != {total_phr}"
    )
    assert formulation["blended_cost_per_kg_cents"] == blended_cost_per_kg_cents, (
        f"blended_cost_per_kg_cents {formulation['blended_cost_per_kg_cents']} "
        f"!= {blended_cost_per_kg_cents}"
    )
    assert formulation["performance_score"] == performance_score, (
        f"performance_score {formulation['performance_score']} != {performance_score}"
    )
    assert (
        formulation["indentation_resistance_class"] == indentation_resistance_class
    ), (
        f"indentation_resistance_class {formulation['indentation_resistance_class']} "
        f"!= {indentation_resistance_class}"
    )


def assert_warranty_terms(sku: Dict[str, Any], residential: int, light_commercial: int):
    """PRD 3.3 warranty tiers, caps and the waterproof click-lock bonus."""
    assert sku["warranty_years"] == residential, (
        f"warranty_years {sku['warranty_years']} != {residential}"
    )
    assert sku["light_commercial_warranty_years"] == light_commercial, (
        f"light_commercial_warranty_years {sku['light_commercial_warranty_years']} "
        f"!= {light_commercial}"
    )


def assert_qc_gates(run: Dict[str, Any], expected: bool):
    """The four QC gates of PRD 3.6 read together."""
    for gate in (
        "registration_within_tolerance",
        "emboss_within_tolerance",
        "curl_within_tolerance",
        "tongue_within_tolerance",
    ):
        assert run[gate] is expected, f"{gate} is {run[gate]!r}, expected {expected!r}"


def assert_traceability_snapshot(snapshot: Dict[str, Any], expected: Dict[str, Any]):
    """PRD 3.7: the batch's immutable traceability snapshot."""
    assert isinstance(snapshot, dict), "traceability_snapshot must be an object"
    for key, value in expected.items():
        assert key in snapshot, f"traceability_snapshot is missing {key}"
        assert snapshot[key] == value, (
            f"traceability_snapshot.{key} is {snapshot[key]!r}, expected {value!r}"
        )


def assert_license_ledger(
    license_row: Dict[str, Any],
    reserved: Optional[float] = None,
    consumed: Optional[float] = None,
    accrued_cents: Optional[int] = None,
):
    """The three licensed-volume ledger figures of PRD 3.2."""
    if reserved is not None:
        assert license_row["reserved_volume_sqm"] == reserved, (
            f"reserved_volume_sqm {license_row['reserved_volume_sqm']} != {reserved}"
        )
    if consumed is not None:
        assert license_row["consumed_volume_sqm"] == consumed, (
            f"consumed_volume_sqm {license_row['consumed_volume_sqm']} != {consumed}"
        )
    if accrued_cents is not None:
        assert license_row["accrued_royalty_cents"] == accrued_cents, (
            f"accrued_royalty_cents {license_row['accrued_royalty_cents']} "
            f"!= {accrued_cents}"
        )
