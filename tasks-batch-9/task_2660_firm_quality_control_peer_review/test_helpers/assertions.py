"""Domain assertion helpers layered over the framework validators."""
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """Every entity carries id, created_at, updated_at and version."""
    for field in COMMON_FIELDS:
        assert field in entity, f"missing common field {field}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at not ISO-8601: {entity['created_at']}"
    assert is_iso8601_timestamp(
        entity["updated_at"]
    ), f"updated_at not ISO-8601: {entity['updated_at']}"
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_fields(entity: Dict[str, Any], **expected) -> None:
    """Assert a set of field values in one shot, reporting all mismatches."""
    mismatches = []
    for field, value in expected.items():
        assert field in entity, f"missing field {field}: {sorted(entity)}"
        if isinstance(value, float):
            actual = float(entity[field])
            if abs(actual - value) > 1e-9:
                mismatches.append(f"{field}: expected {value}, got {entity[field]}")
        elif entity[field] != value:
            mismatches.append(f"{field}: expected {value!r}, got {entity[field]!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_decimal_equals(actual: Any, expected: float, places: int = 2) -> None:
    """Compare a monetary/score value to the expected two-decimal figure."""
    assert actual is not None, f"expected {expected}, got None"
    assert (
        round(float(actual), places) == round(float(expected), places)
    ), f"expected {expected}, got {actual}"


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    assert entity["version"] == expected, (
        f"expected version {expected}, got {entity['version']}"
    )


def assert_list_equals_unordered(actual: Iterable, expected: Iterable) -> None:
    assert sorted(actual) == sorted(expected), f"expected {expected}, got {actual}"


def read_entity(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate a single-resource response and return its data payload."""
    validate_success(response, expected_status=expected_status)
    return get_success_data(response)


def created_entity(response) -> Dict[str, Any]:
    """Validate a 201 creation response and return its data payload."""
    validate_success(response, expected_status=201)
    return get_success_data(response)
