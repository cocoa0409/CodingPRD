"""Domain assertion helpers built on the framework validators."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import DECIMAL_TOLERANCE


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def assert_created(response) -> Dict[str, Any]:
    """A successful create returns 201 and the new resource."""
    return validate_success(response, expected_status=201)


def assert_ok(response) -> Dict[str, Any]:
    """A successful read or transition returns 200 and the resource."""
    return validate_success(response, expected_status=200)


def assert_error(response, expected_error_id: str) -> Dict[str, Any]:
    """The request failed with exactly the expected error identifier."""
    return validate_error(response, expected_error_id)


def assert_page(response):
    """A successful list read returns the collection plus its pagination meta."""
    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), "id must be a UUID: %r" % (entity.get("id"),)
    assert_timestamp_format(entity["created_at"])
    assert_timestamp_format(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    """The resource's optimistic-concurrency counter holds the expected value."""
    assert entity["version"] == expected, "expected version %s, got %s" % (
        expected,
        entity.get("version"),
    )


def assert_millisecond_timestamp(value: str) -> None:
    """Timestamps are serialised in UTC with exactly three fractional digits."""
    assert isinstance(value, str), "timestamp must be a string: %r" % (value,)
    assert is_iso8601_timestamp(value), "not an ISO-8601 timestamp: %r" % (value,)
    assert value.endswith("Z"), "timestamp must end with Z: %r" % (value,)
    assert len(value) == len("2026-08-01T00:00:00.000Z"), (
        "timestamp must carry exactly three fractional digits: %r" % (value,)
    )
    assert value[19] == ".", "timestamp must carry a fractional part: %r" % (value,)


def assert_timestamp_equals(value: str, expected: str) -> None:
    """A derived timestamp lands on exactly the expected instant."""
    assert_millisecond_timestamp(value)
    assert value == expected, "expected timestamp %s, got %s" % (expected, value)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def assert_decimal_equals(actual: Any, expected: float) -> None:
    """A two-decimal percentage or rate matches to the cent."""
    assert actual == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        "expected %s, got %s" % (expected, actual)
    )


def assert_two_decimal_places(value: Any) -> None:
    """A rate is carried with two decimal places of resolution."""
    assert isinstance(value, (int, float)), "expected a number, got %r" % (value,)
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        "value carries more than two decimal places: %r" % (value,)
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_attempt_budget_conserved(contact: Dict[str, Any]) -> None:
    """attempts_charged plus attempt_budget_remaining equals attempt_budget_total."""
    assert (
        contact["attempts_charged"] + contact["attempt_budget_remaining"]
        == contact["attempt_budget_total"]
    ), (
        "budget not conserved: charged=%s remaining=%s total=%s"
        % (
            contact.get("attempts_charged"),
            contact.get("attempt_budget_remaining"),
            contact.get("attempt_budget_total"),
        )
    )


def assert_consent_census_conserved(contact: Dict[str, Any]) -> None:
    """total_consent_count equals the sum of the four status buckets."""
    buckets = (
        contact["active_consent_count"]
        + contact["suspended_consent_count"]
        + contact["revoked_consent_count"]
        + contact["superseded_consent_count"]
    )
    assert contact["total_consent_count"] == buckets, (
        "census not conserved: total=%s buckets=%s"
        % (contact.get("total_consent_count"), buckets)
    )


def assert_status(entity: Dict[str, Any], expected: str, field: str = "status") -> None:
    """The resource sits in exactly the expected state."""
    assert entity[field] == expected, "expected %s %s, got %s" % (
        field,
        expected,
        entity.get(field),
    )


def assert_fields_null(entity: Dict[str, Any], *field_names: str) -> None:
    """The named fields are present and null."""
    for field_name in field_names:
        assert entity[field_name] is None, "%s should be null, got %r" % (
            field_name,
            entity.get(field_name),
        )


def assert_fields_equal(entity: Dict[str, Any], **expected: Any) -> None:
    """Each named field holds exactly the expected value."""
    for field_name, value in expected.items():
        assert entity[field_name] == value, "expected %s == %r, got %r" % (
            field_name,
            value,
            entity.get(field_name),
        )


def ids_of(rows: Iterable[Dict[str, Any]]) -> list:
    """Collect the identifiers of a listing page in order."""
    return [row["id"] for row in rows]


def assert_total_count(meta: Dict[str, Any], expected: int) -> None:
    """The pagination meta reports the expected total across all pages."""
    assert meta["total_count"] == expected, "expected total_count %s, got %s" % (
        expected,
        meta.get("total_count"),
    )


def find_by_id(rows: Iterable[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    """Locate one row of a listing page by identifier."""
    for row in rows:
        if row["id"] == row_id:
            return row
    return None
