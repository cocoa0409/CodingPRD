"""Domain assertion helpers.

The plan's numbers are money in whole cents, ratios carried to four decimal
places and basis weights carried to two, so comparisons go through ``Decimal``
rather than through float equality.  Timestamps are compared after normalisation
because an instant may be serialised with or without fractional seconds and with
either a ``Z`` suffix or a ``+00:00`` offset.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    COMMON_FIELDS,
    IDENTITY_FIELDS,
    MUTATION_FIELDS,
    Record,
)

# ---------------------------------------------------------------------------
# Instants and dates
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant into an aware UTC ``datetime``."""
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO-8601 instants denote the same moment."""
    assert actual is not None, f"{label}: expected {expected!r}, got None"
    assert is_iso8601_timestamp(actual), f"{label}: {actual!r} is not ISO-8601"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_date_equals(actual: Any, expected: str, label: str = "date") -> None:
    """Assert a calendar-date field equals the expected ``YYYY-MM-DD`` value."""
    assert actual is not None, f"{label}: expected {expected!r}, got None"
    assert str(actual)[:10] == expected, (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def parse_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def shift_date(value: str, days: int) -> str:
    """Return ``value`` (a ``YYYY-MM-DD`` date) shifted by ``days`` days."""
    return (parse_date(value) + timedelta(days=days)).isoformat()


def shift_instant(value: str, days: int) -> str:
    """Return ``value`` (an instant) shifted by whole days, ``Z``-suffixed."""
    moved = parse_instant(value) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def instant_from_date(value: str) -> str:
    """Midnight UTC on the given calendar date, as an instant."""
    return f"{str(value)[:10]}T00:00:00Z"


# ---------------------------------------------------------------------------
# Money, ratios and weights
# ---------------------------------------------------------------------------


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money field is an exact whole-cent integer."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert not isinstance(actual, bool), f"{label}: expected an integer, got {actual!r}"
    assert isinstance(actual, int) or (
        isinstance(actual, (str, float, Decimal)) and Decimal(str(actual)) == Decimal(str(actual)).to_integral_value()
    ), f"{label}: {actual!r} is not a whole number of cents"
    assert Decimal(str(actual)) == Decimal(expected), (
        f"{label}: expected {expected} cents, got {actual!r}"
    )


def assert_decimal_equals(
    actual: Any, expected: str, places: int, label: str = "value"
) -> None:
    """Assert a decimal-valued field equals ``expected`` at ``places`` places."""
    assert actual is not None, f"{label}: expected {expected!r}, got None"
    quantum = Decimal(1).scaleb(-places)
    got = Decimal(str(actual)).quantize(quantum)
    want = Decimal(expected).quantize(quantum)
    assert got == want, f"{label}: expected {expected!r}, got {actual!r}"


def assert_ratio(actual: Any, expected: str, label: str = "ratio") -> None:
    """Assert a ratio field matches at four decimal places."""
    assert_decimal_equals(actual, expected, 4, label)


def assert_pct(actual: Any, expected: str, label: str = "percentage") -> None:
    """Assert a percentage-weight field matches at two decimal places."""
    assert_decimal_equals(actual, expected, 2, label)


def round_half_up(value: Decimal) -> int:
    """Round to the nearest whole unit with halves going away from zero."""
    from decimal import ROUND_HALF_UP

    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Field-level shape assertions
# ---------------------------------------------------------------------------


def assert_field_equals(record: Mapping[str, Any], field: str, expected: Any) -> None:
    assert field in record, f"response record is missing {field!r}"
    assert record[field] == expected, (
        f"{field}: expected {expected!r}, got {record[field]!r}"
    )


def assert_fields_equal(record: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """Assert every key/value pair in ``expected`` matches the record."""
    for field, value in expected.items():
        assert_field_equals(record, field, value)


def assert_field_absent(record: Mapping[str, Any], field: str) -> None:
    assert field not in record, (
        f"{field!r} must be absent from the record, found {record.get(field)!r}"
    )


def assert_fields_absent(record: Mapping[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert_field_absent(record, field)


def assert_field_null(record: Mapping[str, Any], field: str) -> None:
    assert field in record, f"response record is missing {field!r}"
    assert record[field] is None, f"{field}: expected null, got {record[field]!r}"


def assert_fields_null(record: Mapping[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert_field_null(record, field)


def assert_fields_present(record: Mapping[str, Any], fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in record]
    assert not missing, f"record is missing fields {missing}"


# ---------------------------------------------------------------------------
# Audit-field contract
# ---------------------------------------------------------------------------


def assert_identity_fields(record: Record) -> None:
    """A record carries a UUID ``id`` and an ISO-8601 ``created_at``."""
    assert_fields_present(record, IDENTITY_FIELDS)
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"created_at is not ISO-8601: {record['created_at']!r}"
    )


def assert_versioned_record(record: Record, expected_version: Optional[int] = None) -> None:
    """A record carrying the full audit quartet, with an integer ``version``."""
    assert_identity_fields(record)
    assert_fields_present(record, MUTATION_FIELDS)
    assert is_iso8601_timestamp(record["updated_at"]), (
        f"updated_at is not ISO-8601: {record['updated_at']!r}"
    )
    version = record["version"]
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"version must be an integer, got {version!r}"
    )
    if expected_version is not None:
        assert version == expected_version, (
            f"version: expected {expected_version}, got {version}"
        )


def assert_unversioned_record(record: Record) -> None:
    """A record carrying only ``id`` and ``created_at``."""
    assert_identity_fields(record)
    assert_fields_absent(record, MUTATION_FIELDS)


def assert_common_fields(record: Record) -> None:
    assert_fields_present(record, COMMON_FIELDS)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def assert_count(items: Sequence[Any], expected: int, label: str = "collection") -> None:
    assert len(items) == expected, (
        f"{label}: expected {expected} item(s), got {len(items)}: {items!r}"
    )


def index_by(items: Iterable[Record], field: str) -> dict:
    """Index a list of records by one of their fields."""
    return {item[field]: item for item in items}


def find_one(items: Iterable[Record], field: str, value: Any) -> Record:
    """Return the single record whose ``field`` equals ``value``."""
    matches = [item for item in items if item.get(field) == value]
    assert len(matches) == 1, (
        f"expected exactly one record with {field}={value!r}, got {len(matches)}"
    )
    return matches[0]


def assert_ids_equal(items: Iterable[Record], expected_ids: Sequence[str]) -> None:
    """Assert the records appear in exactly the given id order."""
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), (
        f"expected id order {list(expected_ids)}, got {actual}"
    )


def assert_descending_by(items: Sequence[Record], field: str) -> None:
    """Assert records are ordered newest-first on an instant field."""
    values = [parse_instant(item[field]) for item in items]
    assert values == sorted(values, reverse=True), (
        f"records are not in descending {field} order: {[i[field] for i in items]}"
    )


def assert_pagination_meta(
    meta: Mapping[str, Any],
    total_count: int,
    limit: int,
    offset: int,
    has_more: Optional[bool] = None,
) -> None:
    """Assert the pagination envelope reports the expected window."""
    assert_field_equals(meta, "total_count", total_count)
    assert_field_equals(meta, "limit", limit)
    assert_field_equals(meta, "offset", offset)
    if has_more is None:
        has_more = offset + limit < total_count
    assert_field_equals(meta, "has_more", has_more)
