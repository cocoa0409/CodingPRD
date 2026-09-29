"""Domain assertion helpers layered on the framework validators."""
from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)


def assert_money(actual, expected, field="amount"):
    """A monetary field is carried at exactly 2 decimal places (PRD §2.6)."""
    assert actual is not None, f"{field} is null, expected {expected}"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{field}: expected {expected}, got {actual}"
    )
    text = f"{float(actual):.10f}".rstrip("0")
    fractional = text.split(".")[1] if "." in text else ""
    assert len(fractional) <= 2, f"{field} carries more than 2 decimals: {actual}"


def assert_ratio_4dp(actual, expected, field="ratio"):
    """A ratio field is carried at exactly 4 decimal places (PRD §2.6)."""
    assert actual is not None, f"{field} is null, expected {expected}"
    assert round(float(actual), 4) == round(float(expected), 4), (
        f"{field}: expected {expected}, got {actual}"
    )
    text = f"{float(actual):.10f}".rstrip("0")
    fractional = text.split(".")[1] if "." in text else ""
    assert len(fractional) <= 4, f"{field} carries more than 4 decimals: {actual}"


def assert_score_2dp(actual, expected, field="score"):
    assert actual is not None, f"{field} is null, expected {expected}"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_entity_shape(row, expect_version=True):
    """Common identity and audit fields (PRD §2.4)."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at: {row['created_at']}"
    if expect_version:
        assert is_iso8601_timestamp(row["updated_at"]), f"bad updated_at: {row['updated_at']}"
        assert isinstance(row["version"], int) and row["version"] >= 1
    else:
        assert "updated_at" not in row, "updated_at must be absent from this row"
        assert "version" not in row, "version must be absent from this row"


def assert_instant(actual, expected, field="timestamp"):
    """Compare two ISO 8601 UTC instants ignoring fractional-digit formatting."""
    from datetime import datetime

    def parse(value):
        assert isinstance(value, str), f"{field} is not a string: {value!r}"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert parse(actual) == parse(expected), f"{field}: expected {expected}, got {actual}"


def assert_status(row, expected, field="status"):
    assert row[field] == expected, f"{field}: expected {expected}, got {row[field]}"


def get_rows(response):
    """Return the `data` array of a successful list response."""
    data, _meta = validate_paginated(response)
    return data


def get_total_count(response):
    _data, meta = validate_paginated(response)
    return meta["total_count"]


def assert_total_count(response, expected):
    actual = get_total_count(response)
    assert actual == expected, f"total_count: expected {expected}, got {actual}"


def assert_ordered_by(rows, keys):
    """Assert `rows` are non-decreasing on the given (key, direction) pairs."""
    def sort_key(row):
        out = []
        for key, direction in keys:
            value = row[key]
            if direction == "DESC":
                value = -value if isinstance(value, (int, float)) else value
            out.append(value)
        return tuple(out)

    for earlier, later in zip(rows, rows[1:]):
        assert sort_key(earlier) <= sort_key(later), (
            f"rows out of order on {keys}: {earlier} then {later}"
        )


def find_row(rows, **match):
    for row in rows:
        if all(row.get(field) == value for field, value in match.items()):
            return row
    raise AssertionError(f"no row matching {match} in {rows}")


def data_of(response, expected_status=200):
    validate_success(response, expected_status=expected_status)
    return get_success_data(response)
