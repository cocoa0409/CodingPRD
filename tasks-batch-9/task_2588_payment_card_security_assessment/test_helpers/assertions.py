"""Domain assertions layered over the framework validators."""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

MONEY_TOLERANCE = 0.01
RATIO_TOLERANCE = 0.00005
PERCENTAGE_TOLERANCE = 0.01

_ISO_UTC_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_UUID_NO_PREFIX = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# ---------------------------------------------------------------------------
# Identity and timestamps
# ---------------------------------------------------------------------------
def assert_bare_uuid(value: Any) -> None:
    """Identifiers are bare UUIDs with no prefix and no decoration."""
    assert isinstance(value, str), "identifier must be a string, got %r" % (value,)
    assert _UUID_NO_PREFIX.match(value), "identifier is not a bare UUID: %r" % (value,)
    assert is_valid_uuid(value), "identifier is not a valid UUID: %r" % (value,)


def assert_utc_millis_timestamp(value: Any) -> None:
    """Timestamps are ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), "timestamp must be a string, got %r" % (value,)
    assert _ISO_UTC_MILLIS.match(value), (
        "timestamp %r is not ISO 8601 UTC with three fractional digits" % (value,)
    )


def assert_same_instant(actual: Any, expected_iso: str) -> None:
    """Compare a returned timestamp with an instant written without fractions."""
    assert isinstance(actual, str), "timestamp must be a string, got %r" % (actual,)
    normalised_actual = actual.replace("Z", "").split(".")[0]
    normalised_expected = expected_iso.replace("Z", "").split(".")[0]
    assert normalised_actual == normalised_expected, (
        "expected instant %s but the row carries %s" % (expected_iso, actual)
    )


def assert_common_fields(row: Dict[str, Any]) -> None:
    """A mutable row carries id, created_at, updated_at and version."""
    assert_bare_uuid(row["id"])
    assert_utc_millis_timestamp(row["created_at"])
    assert_utc_millis_timestamp(row["updated_at"])
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1"


def assert_historical_fields(row: Dict[str, Any]) -> None:
    """A historical row carries only id and created_at - never updated_at or version."""
    assert_bare_uuid(row["id"])
    assert_utc_millis_timestamp(row["created_at"])
    assert "updated_at" not in row, "a historical record must not expose updated_at"
    assert "version" not in row, "a historical record must not expose version"


def assert_version_bumped_by(before: int, after: int, expected: int = 1) -> None:
    assert after == before + expected, (
        "expected the version to advance by %d, from %d to %d, but it is %d"
        % (expected, before, before + expected, after)
    )


def assert_version_unchanged(before: int, after: int) -> None:
    assert after == before, (
        "expected the version to stay at %d but it moved to %d" % (before, after)
    )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def assert_object_envelope(response) -> Dict[str, Any]:
    """A single-resource response carries response_type 'object'."""
    body = response.json()
    assert body["response_type"] == "object", (
        "expected response_type 'object', got %r" % (body.get("response_type"),)
    )
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith(
        "req_"
    ), "api_request_id must be a req_-prefixed string, got %r" % (
        meta.get("api_request_id"),
    )
    assert_utc_millis_timestamp(meta["api_request_timestamp"])
    return body["data"]


def assert_error_envelope(response, expected_error_id: str) -> Dict[str, Any]:
    """An error response carries response_type 'error' and a readable message."""
    body = response.json()
    assert body["response_type"] == "error", (
        "expected response_type 'error', got %r" % (body.get("response_type"),)
    )
    payload = validate_error(response, expected_error_id)
    assert isinstance(payload.get("message"), str) and payload["message"].strip(), (
        "an error payload must carry a human-readable message"
    )
    return payload


def assert_pagination_meta(
    response,
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Check the four list-only meta fields the PRD pins on collection reads."""
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            "expected total_count %d, got %s" % (expected_total, meta.get("total_count"))
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            "expected limit %d, got %s" % (expected_limit, meta.get("limit"))
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            "expected offset %d, got %s" % (expected_offset, meta.get("offset"))
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            "expected has_more %r, got %r" % (expected_has_more, meta.get("has_more"))
        )
    return rows


def assert_total_count(response, expected_total: int) -> List[Dict[str, Any]]:
    return assert_pagination_meta(response, expected_total=expected_total)


def assert_created(response) -> Dict[str, Any]:
    """A creation answers 201 and returns the created resource."""
    return validate_success(response, 201)


def assert_ok(response) -> Dict[str, Any]:
    """Every other success answers 200."""
    return validate_success(response, 200)


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
def assert_money(actual: Any, expected: float) -> None:
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        "expected the amount %.2f, got %r" % (expected, actual)
    )


def assert_percentage(actual: Any, expected: float) -> None:
    assert actual == pytest.approx(expected, abs=PERCENTAGE_TOLERANCE), (
        "expected the percentage %.2f, got %r" % (expected, actual)
    )


def assert_coverage_ratio(actual: Any, expected: float) -> None:
    """coverage_ratio is carried to four decimal places."""
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        "expected the coverage ratio %.4f, got %r" % (expected, actual)
    )


def assert_cvss(actual: Any, expected: float) -> None:
    """cvss_score is carried to one decimal place."""
    assert actual == pytest.approx(expected, abs=0.05), (
        "expected the CVSS score %.1f, got %r" % (expected, actual)
    )


def assert_fee_breakdown(
    engagement: Dict[str, Any],
    estimated_hours: int,
    assessment_fee_total: float,
) -> None:
    """Check the outcome of the fee's seven ordered steps on the engagement.

    The PRD names exactly two fee fields — `estimated_hours` and
    `assessment_fee_total` — and it names them on the engagement, whose plans
    re-price it. The base, surcharge, subtotal and discount are intermediate
    money values of the derivation and are never named as response fields, so
    only the two published figures are asserted here.
    """
    assert engagement["estimated_hours"] == estimated_hours, (
        "expected %d estimated hours, got %s"
        % (estimated_hours, engagement.get("estimated_hours"))
    )
    assert_money(engagement["assessment_fee_total"], assessment_fee_total)


# ---------------------------------------------------------------------------
# Domain-shaped checks
# ---------------------------------------------------------------------------
def assert_partition_conserved(engagement: Dict[str, Any], total: int) -> None:
    """The three scope classes are disjoint and conserve the inventory."""
    cde = engagement["cde_component_count"]
    connected = engagement["connected_component_count"]
    out_of_scope = engagement["out_of_scope_component_count"]
    assert cde + connected + out_of_scope == total, (
        "the partition must conserve %d components but sums to %d"
        % (total, cde + connected + out_of_scope)
    )
    # `total_component_count` is a field the PRD attaches to the consolidated
    # summary read, not to the engagement read; conservation itself is checked by
    # the sum above against the total the caller knows it inventoried.
    assert engagement["in_scope_component_count"] == cde + connected, (
        "in_scope_component_count must equal the cardholder and connected counts"
    )


def assert_partition_counts(
    engagement: Dict[str, Any], cde: int, connected: int, out_of_scope: int
) -> None:
    assert engagement["cde_component_count"] == cde, (
        "expected cde_component_count %d, got %s" % (cde, engagement.get("cde_component_count"))
    )
    assert engagement["connected_component_count"] == connected, (
        "expected connected_component_count %d, got %s"
        % (connected, engagement.get("connected_component_count"))
    )
    assert engagement["out_of_scope_component_count"] == out_of_scope, (
        "expected out_of_scope_component_count %d, got %s"
        % (out_of_scope, engagement.get("out_of_scope_component_count"))
    )
    assert_partition_conserved(engagement, cde + connected + out_of_scope)


def assert_finding_ledger_identity(cycle: Dict[str, Any]) -> None:
    """raw_high_finding_count always equals effective plus accepted."""
    raw = cycle["raw_high_finding_count"]
    accepted = cycle["accepted_false_positive_count"]
    effective = cycle["effective_high_finding_count"]
    assert raw == effective + accepted, (
        "the ledger identity is broken: raw %d != effective %d + accepted %d"
        % (raw, effective, accepted)
    )


def assert_segment_state(
    segment: Dict[str, Any],
    segmentation_status: Optional[str] = None,
    effective_class: Optional[str] = None,
    segment_class: Optional[str] = None,
    scope_expanded_by_failure: Optional[bool] = None,
    revalidation_round: Optional[int] = None,
) -> None:
    if segmentation_status is not None:
        assert segment["segmentation_status"] == segmentation_status, (
            "expected segmentation_status %s, got %s"
            % (segmentation_status, segment.get("segmentation_status"))
        )
    if effective_class is not None:
        assert segment["effective_class"] == effective_class, (
            "expected effective_class %s, got %s"
            % (effective_class, segment.get("effective_class"))
        )
    if segment_class is not None:
        assert segment["segment_class"] == segment_class, (
            "expected segment_class %s, got %s"
            % (segment_class, segment.get("segment_class"))
        )
    if scope_expanded_by_failure is not None:
        assert segment["scope_expanded_by_failure"] is scope_expanded_by_failure, (
            "expected scope_expanded_by_failure %r, got %r"
            % (scope_expanded_by_failure, segment.get("scope_expanded_by_failure"))
        )
    if revalidation_round is not None:
        assert segment["revalidation_round"] == revalidation_round, (
            "expected revalidation_round %d, got %s"
            % (revalidation_round, segment.get("revalidation_round"))
        )


def assert_requirement_dimensions(
    requirement: Dict[str, Any],
    test_status: Optional[str] = None,
    remediation_status: Optional[str] = None,
) -> None:
    """The testing and remediation dimensions move independently."""
    if test_status is not None:
        assert requirement["test_status"] == test_status, (
            "expected test_status %s, got %s"
            % (test_status, requirement.get("test_status"))
        )
    if remediation_status is not None:
        assert requirement["remediation_status"] == remediation_status, (
            "expected remediation_status %s, got %s"
            % (remediation_status, requirement.get("remediation_status"))
        )


def assert_stratum_allocations(plan: Dict[str, Any], expected: Dict[str, int]) -> None:
    allocations = plan["stratum_allocations"]
    for stratum, count in expected.items():
        assert allocations.get(stratum) == count, (
            "expected %s to draw %d, got %s" % (stratum, count, allocations.get(stratum))
        )
    assert sum(allocations.values()) == plan["component_sample_size"], (
        "the per-stratum sizes must sum to component_sample_size"
    )


def assert_keys_exactly(payload: Dict[str, Any], expected_keys: Sequence[str]) -> None:
    assert set(payload.keys()) == set(expected_keys), (
        "expected exactly the keys %s, got %s"
        % (sorted(expected_keys), sorted(payload.keys()))
    )


def assert_ascending_by(rows: Iterable[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), "rows are not ascending by %s: %s" % (field, values)


def find_row(rows: Iterable[Dict[str, Any]], **criteria) -> Dict[str, Any]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise AssertionError("no row matched %r" % (criteria,))
