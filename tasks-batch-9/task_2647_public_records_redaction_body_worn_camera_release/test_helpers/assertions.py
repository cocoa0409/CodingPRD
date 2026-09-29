"""Domain assertion helpers layered over the generic framework validators."""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)


# ------------------------------------------------------------- envelope
def assert_envelope_meta(response: requests.Response) -> Dict[str, Any]:
    """The meta block carries a req_-prefixed id and an ISO 8601 UTC instant."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO 8601, got {meta['api_request_timestamp']!r}"
    )
    return meta


def assert_object_response(response: requests.Response, expected_status: int = 200) -> Dict[str, Any]:
    """A single-resource success: response_type 'object' and a dict payload."""
    data = validate_success(response, expected_status)
    assert response.json()["response_type"] == "object"
    assert isinstance(data, dict)
    assert_envelope_meta(response)
    return data


def assert_created(response: requests.Response) -> Dict[str, Any]:
    """A creation returns 201 with the created resource in data."""
    return assert_object_response(response, 201)


def assert_modified(response: requests.Response) -> Dict[str, Any]:
    """A modification, including a state transition, returns 200."""
    return assert_object_response(response, 200)


def assert_list_response(response: requests.Response):
    """A list success: response_type 'array' plus the pagination meta block."""
    data, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert isinstance(data, list)
    assert_envelope_meta(response)
    return data, meta


def assert_total_count(response: requests.Response, expected: int):
    """A list endpoint's total_count is the pre-pagination match count."""
    data, meta = assert_list_response(response)
    assert meta["total_count"] == expected, (
        f"Expected total_count {expected}, got {meta['total_count']}"
    )
    return data, meta


# -------------------------------------------------------- common fields
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource but the ledger entry carries id, created_at, updated_at, version."""
    assert is_valid_uuid(entity["id"]), f"id must be a canonical UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_ledger_entry_fields(entry: Dict[str, Any]) -> None:
    """The append-only ledger line carries id and created_at and nothing else."""
    assert is_valid_uuid(entry["id"]), f"id must be a canonical UUID, got {entry['id']!r}"
    assert is_iso8601_timestamp(entry["created_at"])
    assert "updated_at" not in entry, "a ledger entry has no updated_at"
    assert "version" not in entry, "a ledger entry has no version"


# ------------------------------------------------------------- instants
# The PRD pins three fractional digits only on `created_at`, `updated_at` and
# `meta.api_request_timestamp`; every other instant field (deadlines, stamped
# clock reads and echoed inputs) has no rendering pinned in prose. Instants are
# therefore compared as instants — an exact equality of the moment named — so
# that `2026-08-21T00:00:00Z` and `2026-08-21T00:00:00.000Z` agree while a
# deadline one second or one day out still fails.
_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})$"
)


def parse_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 instant string; None when the value is not one."""
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def same_instant(actual: Any, expected: Any) -> bool:
    """True when both values are ISO 8601 strings naming the very same instant."""
    left, right = parse_instant(actual), parse_instant(expected)
    return left is not None and right is not None and left == right


def assert_instant(actual: Any, expected: Any, field: str = "instant") -> None:
    """The field names exactly the expected instant."""
    assert same_instant(actual, expected), (
        f"{field}: expected instant {expected!r}, got {actual!r}"
    )


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Compare a batch of fields against their expected values in one call."""
    for field, value in expected.items():
        assert field in entity, f"missing field {field!r} on {sorted(entity)}"
        if entity[field] != value and same_instant(entity[field], value):
            continue
        assert entity[field] == value, (
            f"{field}: expected {value!r}, got {entity[field]!r}"
        )


def assert_money_is_integer_cents(entity: Dict[str, Any], *fields: str) -> None:
    """Monetary fields are integer counts of cents, never floats or strings."""
    for field in fields:
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer count of cents, got {value!r}"
        )


def assert_ids(actual: Iterable[Dict[str, Any]], expected_ids) -> None:
    """Compare a list payload's ids to an expected ordered sequence."""
    assert [row["id"] for row in actual] == list(expected_ids)


# ---------------------------------------------------- ledger conservation
def assert_ledger_conservation(request_body: Dict[str, Any]) -> None:
    """deposit_balance_cents == deposit_paid + waiver_credit_total - fee_recognized."""
    expected = (
        request_body["deposit_paid_cents"]
        + request_body["waiver_credit_total_cents"]
        - request_body["fee_recognized_cents"]
    )
    assert request_body["deposit_balance_cents"] == expected, (
        "conservation identity broken: "
        f"deposit_balance_cents {request_body['deposit_balance_cents']} != "
        f"{request_body['deposit_paid_cents']} + "
        f"{request_body['waiver_credit_total_cents']} - "
        f"{request_body['fee_recognized_cents']}"
    )


def assert_waiver_pct(entity: Dict[str, Any], field: str, expected: float) -> None:
    """Percentages are carried to two decimal places."""
    assert abs(float(entity[field]) - expected) < 1e-9, (
        f"{field}: expected {expected}, got {entity[field]}"
    )
