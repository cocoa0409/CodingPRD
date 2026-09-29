"""Domain assertions built on the framework's generic helpers."""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON_FIELDS = ("id", "created_at")


def assert_versioned_record(record: Dict[str, Any]) -> None:
    """A resource that carries all four common properties (PRD 2.4)."""
    for field in VERSIONED_COMMON_FIELDS:
        assert field in record, f"missing common field '{field}'"
    assert is_valid_uuid(record["id"]), f"id must be a bare UUID, got {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"])
    assert is_iso8601_timestamp(record["updated_at"])
    assert isinstance(record["version"], int)
    assert record["version"] >= 1


def assert_immutable_record(record: Dict[str, Any]) -> None:
    """A resource that carries only `id` and `created_at` (PRD 2.4)."""
    for field in IMMUTABLE_COMMON_FIELDS:
        assert field in record, f"missing common field '{field}'"
    assert is_valid_uuid(record["id"]), f"id must be a bare UUID, got {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"])
    assert "updated_at" not in record, "immutable resources carry no updated_at"
    assert "version" not in record, "immutable resources carry no version"


def assert_millisecond_timestamp(value: str) -> None:
    """An ISO 8601 UTC timestamp with three fractional digits (PRD 2.4)."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert "." in value, f"expected three fractional digits in {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits in {value!r}"


def assert_pct(actual: Any, expected: float) -> None:
    """A percentage rounded to one decimal place (PRD 2.8)."""
    assert actual == pytest.approx(expected, abs=0.01), f"expected {expected}, got {actual}"


def assert_ratio_4dp(actual: Any, expected: float) -> None:
    """A coverage ratio rounded to four decimal places (PRD 2.8)."""
    assert actual == pytest.approx(expected, abs=0.00001), f"expected {expected}, got {actual}"


def assert_hour_budget_conserved(batch: Dict[str, Any]) -> None:
    """PRD 2.9's conservation law for a quarter's hour budget."""
    total = (
        batch["valid_hour_count"]
        + batch["invalidated_hour_count"]
        + batch["excused_hour_count"]
        + batch["event_excluded_hour_count"]
    )
    assert batch["scheduled_hour_count"] == total, (
        f"scheduled_hour_count {batch['scheduled_hour_count']} != "
        f"valid {batch['valid_hour_count']} + invalidated {batch['invalidated_hour_count']} + "
        f"excused {batch['excused_hour_count']} + event-excluded "
        f"{batch['event_excluded_hour_count']}"
    )


def assert_site_census_partitioned(network: Dict[str, Any]) -> None:
    """PRD 2.9's site census invariant: the per-status buckets sum to the total."""
    buckets = (
        network["proposed_site_count"]
        + network["approved_site_count"]
        + network["operating_site_count"]
        + network["suspended_site_count"]
        + network["shutdown_site_count"]
        + network["relocated_site_count"]
    )
    assert network["total_site_count"] == buckets, (
        f"total_site_count {network['total_site_count']} != bucket sum {buckets}"
    )


def assert_annual_statistics(actual: List[Any], expected: List[float]) -> None:
    """Compare an `annual_statistics` array element-wise, earliest year first."""
    assert isinstance(actual, list), f"annual_statistics must be a list, got {actual!r}"
    assert len(actual) == len(expected), f"expected {expected}, got {actual}"
    for got, want in zip(actual, expected):
        assert got == pytest.approx(want, abs=0.001), f"expected {expected}, got {actual}"


def assert_batch_dimensions(
    batch: Dict[str, Any], validation_status: str, submission_status: str
) -> None:
    """Assert both independent dimensions of a quarter at once (PRD 3.4)."""
    assert batch["validation_status"] == validation_status, (
        f"expected validation_status {validation_status}, got {batch['validation_status']}"
    )
    assert batch["submission_status"] == submission_status, (
        f"expected submission_status {submission_status}, got {batch['submission_status']}"
    )


def assert_siting_codes(site: Dict[str, Any], expected: List[str]) -> None:
    """Violation codes are stored sorted ascending alphabetically (PRD 3.2)."""
    codes = site["siting_violation_codes"]
    assert codes == sorted(codes), f"codes must be sorted ascending, got {codes}"
    assert codes == expected, f"expected {expected}, got {codes}"
    assert site["siting_waiver_required"] is (len(expected) > 0)


def assert_no_version_field(record: Dict[str, Any]) -> None:
    assert "version" not in record, f"unexpected version field on {record!r}"


def assert_field_absent_or_null(record: Dict[str, Any], field: str) -> None:
    assert record.get(field) is None, f"expected {field} to be null, got {record.get(field)!r}"


def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """The error envelope's `meta` carries only the two request fields (PRD 2.2)."""
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, got {sorted(meta)}"
    )
    assert meta["api_request_id"].startswith("req_")


def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
