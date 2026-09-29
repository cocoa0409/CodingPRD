"""Domain assertions for the Non-Traded REIT API.

These wrap the generic envelope validators with the entity-shape rules the PRD
states: which system fields a row must carry, which figures must be integers,
and which axes must read a particular way.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .types import Json

_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_system_fields(row: Json) -> None:
    """PRD §2.4: a UUID id with no type prefix, ISO 8601 stamps, integer version."""
    for field in _COMMON_FIELDS:
        assert field in row, f"Missing system field {field!r}: {row}"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert ":" not in row["id"] and "_" not in row["id"], (
        f"id must carry no type prefix: {row['id']!r}"
    )
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not ISO 8601 UTC: {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at is not ISO 8601 UTC: {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int) and row["version"] >= 1, (
        f"version must be an integer starting at 1: {row.get('version')!r}"
    )


def assert_ballot_fields(ballot: Json) -> None:
    """PRD §2.4: a ballot carries only ``id`` and ``created_at`` — no counter."""
    assert is_valid_uuid(ballot["id"]), f"id is not a UUID: {ballot['id']!r}"
    assert is_iso8601_timestamp(ballot["created_at"]), (
        f"created_at is not ISO 8601 UTC: {ballot['created_at']!r}"
    )
    assert "updated_at" not in ballot, "a ballot has no updated_at field"
    assert "version" not in ballot, "a ballot has no version field"


def assert_created(response: requests.Response) -> Json:
    """A creation returns 201 with a fully minted row (PRD §4, §2.4)."""
    data = validate_success(response, 201)
    assert_system_fields(data)
    return data


def assert_ok(response: requests.Response) -> Json:
    """A modification or read returns 200 (PRD §4)."""
    return validate_success(response, 200)


def assert_integer_money(row: Json, *fields: str) -> None:
    """PRD §2.5: every ``_cents``, ``_e4`` and ``_bps`` field is an integer."""
    for field in fields:
        assert isinstance(row[field], int) and not isinstance(row[field], bool), (
            f"{field} must be an integer, got {row[field]!r}"
        )


def assert_fields(row: Json, **expected: Any) -> None:
    """Assert an exact value for each named field, reporting all mismatches."""
    mismatches = [
        f"{name}: expected {value!r}, got {row.get(name)!r}"
        for name, value in expected.items()
        if row.get(name) != value
    ]
    assert not mismatches, "; ".join(mismatches)


def assert_offering_axes(
    offering: Json,
    registration_status: Optional[str] = None,
    escrow_status: Optional[str] = None,
    repurchase_plan_status: Optional[str] = None,
) -> None:
    """PRD §2.10: the three axes are read independently."""
    expected = {
        "registration_status": registration_status,
        "escrow_status": escrow_status,
        "repurchase_plan_status": repurchase_plan_status,
    }
    assert_fields(offering, **{k: v for k, v in expected.items() if v is not None})


def assert_error(
    response: requests.Response, error_id: str, status: Optional[int] = None
) -> Json:
    """Assert the PRD error identifier, cross-checked against the §5 status."""
    return validate_error(response, error_id, status)


def assert_total_count(response: requests.Response, expected: int) -> list:
    """PRD §2.3: ``meta.total_count`` counts matching rows, not page rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_ascending_created_at(rows: Iterable[Json]) -> None:
    """PRD §2.3: collections come back in ascending ``created_at`` order."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in ascending created_at order: {stamps}"


def assert_version_is(row: Json, expected: int) -> None:
    assert row["version"] == expected, (
        f"expected version {expected}, got {row['version']}"
    )


def assert_envelope_meta(response: requests.Response) -> Dict[str, Any]:
    """PRD §2.2: ``api_request_id`` starts ``req_`` and the stamp is ISO 8601."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO 8601 UTC: {meta['api_request_timestamp']!r}"
    )
    return meta
