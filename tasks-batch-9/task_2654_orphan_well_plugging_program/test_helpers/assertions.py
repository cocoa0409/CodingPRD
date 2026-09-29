"""Domain assertion helpers shared by the whole suite."""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .types import IMMUTABLE_ROW_FIELDS, VERSIONED_ROW_FIELDS


# ---------------------------------------------------------------------------
# Envelope and row shape
# ---------------------------------------------------------------------------
def assert_meta_envelope(response) -> None:
    """Every response carries the request correlation metadata."""
    body = response.json()
    assert "meta" in body, "response has no meta block: %r" % (body,)
    meta = body["meta"]
    assert meta.get("api_request_id"), "meta.api_request_id is missing or empty"
    assert meta.get(
        "api_request_timestamp"
    ), "meta.api_request_timestamp is missing or empty"


def assert_error_payload_is_bare(response) -> None:
    """A failing response carries an error identifier and message and no row."""
    body = response.json()
    data = body.get("data") or {}
    assert data.get("error_id"), "error response carries no error_id: %r" % (body,)
    assert isinstance(data.get("message"), str) and data["message"].strip(), (
        "error response carries no human readable message: %r" % (body,)
    )
    for leaked in ("id", "version", "created_at", "updated_at"):
        assert leaked not in data, (
            "error payload leaked the row field %s: %r" % (leaked, data)
        )


def assert_versioned_row(row: Dict[str, Any]) -> None:
    """The row carries an id, both timestamps and a version counter."""
    for field in VERSIONED_ROW_FIELDS:
        assert field in row, "row is missing the common field %s: %r" % (field, row)
    assert is_iso8601_timestamp(row["created_at"]), (
        "created_at is not an ISO 8601 timestamp: %r" % (row["created_at"],)
    )
    assert isinstance(row["version"], int), "version is not an integer: %r" % (row,)


def assert_immutable_row(row: Dict[str, Any]) -> None:
    """The row carries only an id and a creation timestamp from the common set."""
    for field in IMMUTABLE_ROW_FIELDS:
        assert field in row, "row is missing the common field %s: %r" % (field, row)
    for absent in ("version", "updated_at"):
        assert absent not in row, (
            "an immutable row must not carry %s: %r" % (absent, row)
        )


def assert_uuid_like(value: str) -> None:
    assert isinstance(value, str) and value, "identifier is not a string: %r" % (value,)


# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------
def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Money is an exact integer count of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "%s must be an integer number of cents, got %r" % (label, actual)
    )
    assert actual == expected, "%s: expected %d cents, got %d" % (
        label,
        expected,
        actual,
    )


def assert_score(actual: Any, expected: float, label: str = "score") -> None:
    """A two decimal place quantity compared exactly at that precision."""
    assert actual is not None, "%s is missing" % label
    assert round(float(actual) - expected, 6) == 0, (
        "%s: expected %.2f, got %r" % (label, expected, actual)
    )


def assert_two_decimal_places(actual: Any, label: str = "value") -> None:
    assert actual is not None, "%s is missing" % label
    quantised = round(float(actual), 2)
    assert abs(float(actual) - quantised) < 1e-9, (
        "%s carries more than two decimal places: %r" % (label, actual)
    )


# ---------------------------------------------------------------------------
# Field level checks
# ---------------------------------------------------------------------------
_ISO_INSTANT = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]00:?00)$"
)


def as_instant(value: Any) -> Optional[str]:
    """The millisecond form of an ISO 8601 UTC instant, or None if it is not one.

    Timestamps are compared as instants rather than as byte strings so that a
    whole-second value and the same value carrying three fractional digits are
    treated as the one moment they are.
    """
    if not isinstance(value, str):
        return None
    match = _ISO_INSTANT.match(value)
    if match is None:
        return None
    date_part, time_part, fraction, _zone = match.groups()
    millis = (fraction or ".0")[1:].ljust(3, "0")[:3]
    return "%sT%s.%sZ" % (date_part, time_part, millis)


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """The value names the same UTC instant as the expected one."""
    actual_instant = as_instant(actual)
    assert actual_instant is not None, (
        "%s is not an ISO 8601 UTC instant: %r" % (label, actual)
    )
    assert actual_instant == as_instant(expected), "%s: expected %s, got %r" % (
        label,
        expected,
        actual,
    )


def assert_fields(row: Dict[str, Any], **expected: Any) -> None:
    """Every named field of the row equals the expected value."""
    for field, value in expected.items():
        assert field in row, "row is missing the field %s: %r" % (field, row)
        if row[field] == value:
            continue
        left, right = as_instant(row[field]), as_instant(value)
        if left is not None and right is not None and left == right:
            continue
        raise AssertionError(
            "%s: expected %r, got %r" % (field, value, row[field])
        )


def assert_null_fields(row: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert row.get(field) is None, "%s should be null, got %r" % (
            field,
            row.get(field),
        )


# ---------------------------------------------------------------------------
# Collection checks
# ---------------------------------------------------------------------------
def rows_of(response) -> List[Dict[str, Any]]:
    """The row list of a paginated read."""
    rows, _meta = validate_paginated(response)
    return rows


def assert_total_count(response, expected: int) -> List[Dict[str, Any]]:
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        "expected total_count %d, got %d" % (expected, meta["total_count"])
    )
    return rows


def assert_page(
    response,
    expected_count: int,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    rows, meta = validate_paginated(response)
    assert len(rows) == expected_count, "expected %d rows on the page, got %d" % (
        expected_count,
        len(rows),
    )
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            "expected total_count %d, got %d" % (expected_total, meta["total_count"])
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            "expected has_more %r, got %r" % (expected_has_more, meta["has_more"])
        )
    return rows


def assert_ids_exactly(rows: Sequence[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = [row["id"] for row in rows]
    expected = list(expected_ids)
    assert actual == expected, "expected exactly the ids %r, got %r" % (
        expected,
        actual,
    )


def assert_id_set(rows: Sequence[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = {row["id"] for row in rows}
    expected = set(expected_ids)
    assert actual == expected, "expected the id set %r, got %r" % (expected, actual)


def assert_ascending(rows: Sequence[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), "%s is not in ascending order: %r" % (
        field,
        values,
    )


def assert_field_sequence(
    rows: Sequence[Dict[str, Any]], field: str, expected: Sequence[Any]
) -> None:
    actual = [row[field] for row in rows]
    assert actual == list(expected), "%s sequence: expected %r, got %r" % (
        field,
        list(expected),
        actual,
    )


# ---------------------------------------------------------------------------
# Convenience readers
# ---------------------------------------------------------------------------
def created(response) -> Dict[str, Any]:
    """The row returned by a creating call."""
    return validate_success(response, 201)


def updated(response) -> Dict[str, Any]:
    """The row returned by a modifying or reading call."""
    return validate_success(response, 200)


def created_rows(response) -> List[Dict[str, Any]]:
    """The row list returned by a creating call that answers with a collection."""
    body = response.json()
    assert response.status_code == 201, "expected HTTP 201, got %d: %r" % (
        response.status_code,
        body,
    )
    data = body["data"]
    assert isinstance(data, list), "expected a list payload, got %r" % (data,)
    return data
