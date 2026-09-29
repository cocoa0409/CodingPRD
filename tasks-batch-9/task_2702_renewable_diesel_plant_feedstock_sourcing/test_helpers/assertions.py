"""Domain assertion helpers layered over the framework's generic assertions."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)


def assert_decimal_places(value, places: int, field: str = "value") -> None:
    """The JSON number carries at most `places` decimal places once formatted."""
    assert value is not None, f"{field} must not be null"
    text = f"{value:.{places + 3}f}".rstrip("0")
    if "." in text:
        frac = text.split(".", 1)[1]
        assert len(frac) <= places, (
            f"{field} = {value!r} carries more than {places} decimal places"
        )


def assert_money(value, expected, field: str = "amount") -> None:
    """Compare a 2-decimal money field exactly at cent precision."""
    assert value is not None, f"{field} must not be null"
    assert round(float(value), 2) == round(float(expected), 2), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_mass(value, expected, field: str = "mass_mt") -> None:
    """Compare a 3-decimal mass field exactly at kilogram precision."""
    assert value is not None, f"{field} must not be null"
    assert round(float(value), 3) == round(float(expected), 3), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_activity_index(value, expected) -> None:
    """Compare a 4-decimal catalyst activity index."""
    assert value is not None, "activity_index must not be null"
    assert round(float(value), 4) == round(float(expected), 4), (
        f"activity_index: expected {expected}, got {value}"
    )


def assert_one_decimal(value, expected, field: str) -> None:
    """Compare a 1-decimal field (hydrogen kg/day, product gallons)."""
    assert value is not None, f"{field} must not be null"
    assert round(float(value), 1) == round(float(expected), 1), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_identity_fields(entity: dict, expect_version: bool = True) -> None:
    """Every entity carries a UUID id and an ISO-8601 created_at."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be ISO-8601: {entity['created_at']!r}"
    )
    if expect_version:
        assert isinstance(entity["version"], int) and entity["version"] >= 1
        assert is_iso8601_timestamp(entity["updated_at"])


def assert_append_only_shape(row: dict) -> None:
    """Append-only rows carry id and created_at but no updated_at or version."""
    assert is_valid_uuid(row["id"])
    assert is_iso8601_timestamp(row["created_at"])
    assert "updated_at" not in row, "append-only rows must not expose updated_at"
    assert "version" not in row, "append-only rows must not expose version"


def assert_timestamp_equals(actual, expected_instant: str, field: str) -> None:
    """Compare a stored timestamp to an instant, tolerating the millis suffix."""
    assert actual is not None, f"{field} must not be null"
    normalized = str(actual).replace(".000Z", "Z")
    assert normalized == expected_instant, (
        f"{field}: expected {expected_instant}, got {actual}"
    )


def assert_fields_null(entity: dict, *fields) -> None:
    """Assert each named field is present and null (not absent, not zero)."""
    for field in fields:
        assert field in entity, f"{field} must be present in the payload"
        assert entity[field] is None, f"{field} must be null, got {entity[field]!r}"


def assert_fields_equal(entity: dict, **expected) -> None:
    """Assert a batch of scalar fields at once with readable failures."""
    for field, value in expected.items():
        assert entity.get(field) == value, (
            f"{field}: expected {value!r}, got {entity.get(field)!r}"
        )


def read_entity(response, expected_status: int = 200) -> dict:
    """Validate the envelope of a read and return the entity payload."""
    return validate_success(response, expected_status)
