"""Domain assertions shared across the suite."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)


def assert_identifier(value):
    """Identifiers are bare UUIDs with no type prefix."""
    assert is_valid_uuid(value), f"Expected a bare UUID identifier, got {value!r}"


def assert_created_at_shape(value):
    """``created_at`` is ISO-8601 UTC with exactly three fractional-second digits."""
    assert isinstance(value, str), f"created_at must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"created_at must be ISO-8601, got {value!r}"
    assert value.endswith("Z"), f"created_at must be UTC with a Z suffix, got {value!r}"
    fraction = value[:-1].split(".")
    assert len(fraction) == 2 and len(fraction[1]) == 3, (
        f"created_at must carry exactly three fractional-second digits, got {value!r}"
    )


def assert_common_fields(data):
    """Every entity but the resident assessment carries id, timestamps and version."""
    assert_identifier(data["id"])
    assert_created_at_shape(data["created_at"])
    assert "updated_at" in data, "Expected an updated_at field"
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_no_version_fields(data):
    """The resident assessment carries neither updated_at nor version."""
    assert "version" not in data, "An assessment must not expose a version field"
    assert "updated_at" not in data, "An assessment must not expose an updated_at field"


def assert_value(data, field, expected):
    """Assert one stored field, quoting the observed row on failure."""
    actual = data.get(field)
    assert actual == expected, f"Expected {field} == {expected!r}, got {actual!r}"


def assert_values(data, **expected):
    """Assert several stored fields at once."""
    mismatches = {
        field: (value, data.get(field))
        for field, value in expected.items()
        if data.get(field) != value
    }
    assert not mismatches, f"Field mismatches (expected, actual): {mismatches}"


def assert_rounded(value, expected, places):
    """Assert a rounded numeric field to an exact number of decimal places."""
    assert isinstance(value, (int, float)), f"Expected a number, got {value!r}"
    assert round(float(value), places) == round(float(expected), places), (
        f"Expected {expected} to {places} decimal places, got {value}"
    )
    text = repr(float(value))
    decimals = text.split(".")[1] if "." in text else ""
    assert len(decimals.rstrip("0")) <= places, (
        f"Value {value} carries more than {places} decimal places"
    )


def read_data(response, expected_status=200):
    """Validate the envelope and hand back the data payload."""
    return validate_success(response, expected_status)


def assert_list_meta(meta, total_count=None, limit=None, offset=None, has_more=None):
    """Assert the pagination block of a list response."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more {has_more}, got {meta['has_more']}"
        )


def ids_of(rows):
    """The identifiers of a list payload, in the order the API returned them."""
    return [row["id"] for row in rows]
