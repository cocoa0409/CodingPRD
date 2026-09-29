"""Domain assertion helpers built on top of the framework validators."""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)


# --------------------------------------------------------------------------
# Instant comparison
# --------------------------------------------------------------------------
# PRD 2.4 pins the *rendering* of exactly two things - `api_request_timestamp`
# (2.2) and `created_at` - to "an ISO 8601 UTC instant with three fractional
# digits".  For every other instant field (`closed_at`, `effective_at`,
# `lost_reported_at`, `assurance_expires_at`, `last_attestation_at`, and the
# client-supplied window bounds `valid_from` / `valid_until` /
# `effective_from` / `effective_until`) the PRD constrains only *which instant*
# the field holds, never how many fractional digits it is printed with.  A
# conforming server may therefore render `2026-08-01T00:00:00Z` as
# `2026-08-01T00:00:00.000Z`.  These helpers compare the instant a field holds
# rather than the byte string it is printed as, so the assertion tests the rule
# the PRD actually states.
_ISO_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)


def _looks_like_instant(value: Any) -> bool:
    return isinstance(value, str) and bool(_ISO_INSTANT_RE.match(value))


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional digits."""
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(left: Any, right: Any) -> bool:
    """True when both values denote the same instant, whatever the rendering."""
    if not (_looks_like_instant(left) and _looks_like_instant(right)):
        return False
    return parse_instant(left) == parse_instant(right)


def assert_instant(actual: Any, expected: str, field: str = "instant") -> None:
    """Assert a field holds the expected instant, ignoring fractional-digit style."""
    assert _looks_like_instant(actual), (
        f"{field}: not an ISO 8601 instant: {actual!r}"
    )
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field}: expected instant {expected!r} got {actual!r}"
    )


# --------------------------------------------------------------------------
# Envelope and common property helpers
# --------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """Assert the four common properties every mutable resource carries."""
    assert is_valid_uuid(data["id"]), f"id is not a uuid: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int)
    assert data["version"] >= 1


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only resources carry only id and created_at, never version."""
    assert is_valid_uuid(data["id"]), f"id is not a uuid: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert "updated_at" not in data, "append-only resource must not carry updated_at"
    assert "version" not in data, "append-only resource must not carry version"


def assert_field_values(data: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert a whole bundle of field values in one call."""
    for field, value in expected.items():
        assert field in data, f"response is missing field {field}"
        if instants_equal(data[field], value):
            continue
        assert data[field] == value, (
            f"{field}: expected {value!r} got {data[field]!r}"
        )


# --------------------------------------------------------------------------
# State axis helpers
# --------------------------------------------------------------------------
def assert_credential_axes(
    data: Dict[str, Any], lifecycle_state: str, sync_state: str
) -> None:
    """Assert both independent state axes of a credential in one place."""
    assert data["lifecycle_state"] == lifecycle_state, (
        f"lifecycle_state: expected {lifecycle_state} got {data['lifecycle_state']}"
    )
    assert data["sync_state"] == sync_state, (
        f"sync_state: expected {sync_state} got {data['sync_state']}"
    )


def assert_suspended_with_reason(data: Dict[str, Any], reason: str) -> None:
    assert data["lifecycle_state"] == "SUSPENDED", data["lifecycle_state"]
    assert data["suspend_reason"] == reason, data["suspend_reason"]


def assert_reason_only_when_suspended(data: Dict[str, Any]) -> None:
    """suspend_reason is populated only while the credential is SUSPENDED."""
    if data["lifecycle_state"] != "SUSPENDED":
        assert data["suspend_reason"] is None, data["suspend_reason"]


# --------------------------------------------------------------------------
# Ordering helpers
# --------------------------------------------------------------------------
def assert_ordered_by(rows: List[Dict[str, Any]], field: str) -> None:
    """Assert the rows come back in ascending order of the named field."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"{field} not ascending: {values}"


def assert_element_order(actual: List[str], expected: List[str]) -> None:
    """Assert an element projection matches the canonical order exactly."""
    assert actual == expected, f"expected {expected} got {actual}"


# --------------------------------------------------------------------------
# Money helpers
# --------------------------------------------------------------------------
def assert_whole_cents(value: Any) -> None:
    assert isinstance(value, int), f"money amount must be a whole-cent integer: {value!r}"


def assert_cents(data: Dict[str, Any], field: str, expected: int) -> None:
    assert_whole_cents(data[field])
    assert data[field] == expected, f"{field}: expected {expected} got {data[field]}"


# --------------------------------------------------------------------------
# Read-through helpers
# --------------------------------------------------------------------------
def data_of(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate a success response and hand back its data object."""
    return validate_success(response, expected_status)


def created(response) -> Dict[str, Any]:
    """Validate a 201 creation response and hand back its data object."""
    return validate_success(response, 201)


def rows_of(response) -> List[Dict[str, Any]]:
    """Hand back the row list of a collection response."""
    data = get_success_data(response)
    assert isinstance(data, list), f"expected a list, got {type(data)}"
    return data


def assert_row_count(response, expected: int) -> List[Dict[str, Any]]:
    rows = rows_of(response)
    assert len(rows) == expected, f"expected {expected} rows, got {len(rows)}"
    return rows


def assert_no_rows(response) -> None:
    assert_row_count(response, 0)


def find_row(rows: List[Dict[str, Any]], **match: Any) -> Optional[Dict[str, Any]]:
    for row in rows:
        if all(row.get(key) == value for key, value in match.items()):
            return row
    return None
