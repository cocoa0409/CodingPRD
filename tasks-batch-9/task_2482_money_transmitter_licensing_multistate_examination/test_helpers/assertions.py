"""Domain assertion helpers built on the shared framework assertions."""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import IMMUTABLE_ROW_ABSENT_FIELDS


def assert_audit_stamps(resource: Dict[str, Any]) -> None:
    """A full-audit resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a bare UUID: {resource['id']}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at is not ISO 8601 UTC: {resource['created_at']}"
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"updated_at is not ISO 8601 UTC: {resource['updated_at']}"
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"


def assert_immutable_config_row(resource: Dict[str, Any]) -> None:
    """A jurisdiction row carries only id and created_at."""
    assert is_valid_uuid(resource["id"]), f"id is not a bare UUID: {resource['id']}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at is not ISO 8601 UTC: {resource['created_at']}"
    for field in IMMUTABLE_ROW_ABSENT_FIELDS:
        assert field not in resource, f"a jurisdiction row must not carry {field}"


def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    """The row's version advanced by exactly ``by``."""
    assert after["version"] == before["version"] + by, (
        f"version moved {before['version']} -> {after['version']}, expected "
        f"{before['version'] + by}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """The row's version did not move at all."""
    assert after["version"] == before["version"], (
        f"version moved {before['version']} -> {after['version']} but should have held"
    )


def assert_integer_cents(value: Any, label: str = "amount") -> None:
    """Money is an integer number of cents and never a decimal fraction."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_license_state(
    license_row: Dict[str, Any],
    license_status: Optional[str] = None,
    reporting_status: Optional[str] = None,
    expansion_gate: Optional[str] = None,
    bond_status: Optional[str] = None,
) -> None:
    """Check the two independent licence dimensions and the derived gate."""
    if license_status is not None:
        assert license_row["license_status"] == license_status, (
            f"license_status is {license_row['license_status']}, expected {license_status}"
        )
    if reporting_status is not None:
        assert license_row["reporting_status"] == reporting_status, (
            f"reporting_status is {license_row['reporting_status']}, expected {reporting_status}"
        )
    if expansion_gate is not None:
        assert license_row["expansion_gate"] == expansion_gate, (
            f"expansion_gate is {license_row['expansion_gate']}, expected {expansion_gate}"
        )
    if bond_status is not None:
        assert license_row["bond_status"] == bond_status, (
            f"bond_status is {license_row['bond_status']}, expected {bond_status}"
        )


def assert_coverage(
    licensee: Dict[str, Any],
    coverage_ratio_bps: Optional[int] = None,
    coverage_posture: Optional[str] = None,
    aggregate_outstanding_obligations_cents: Optional[int] = None,
) -> None:
    """Check the licensee-level coverage figures and posture."""
    if aggregate_outstanding_obligations_cents is not None:
        assert (
            licensee["aggregate_outstanding_obligations_cents"]
            == aggregate_outstanding_obligations_cents
        ), (
            "aggregate_outstanding_obligations_cents is "
            f"{licensee['aggregate_outstanding_obligations_cents']}, expected "
            f"{aggregate_outstanding_obligations_cents}"
        )
    if coverage_ratio_bps is not None:
        assert licensee["coverage_ratio_bps"] == coverage_ratio_bps, (
            f"coverage_ratio_bps is {licensee['coverage_ratio_bps']}, "
            f"expected {coverage_ratio_bps}"
        )
    if coverage_posture is not None:
        assert licensee["coverage_posture"] == coverage_posture, (
            f"coverage_posture is {licensee['coverage_posture']}, expected {coverage_posture}"
        )


def assert_fields_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], fields: Iterable[str]
) -> None:
    """None of the named fields moved between the two observations."""
    for field in fields:
        assert after[field] == before[field], (
            f"{field} moved {before[field]!r} -> {after[field]!r} but should have held"
        )
