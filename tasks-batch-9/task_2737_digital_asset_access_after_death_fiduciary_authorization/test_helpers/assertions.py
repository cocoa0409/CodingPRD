"""
Domain assertions for the Digital Estate Fiduciary Access API.

These wrap the generic structural helpers with the checks this contract makes
repeatedly: the four common fields on every resource, the response envelope,
the two estate ledger identities, the inventory counter identity, and the
convenience of reading one field of a resource back through the API.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)


# ─── Envelope and common fields ──────────────────────────────────────────────
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity.get("id", "")), f"id is not a bare UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"created_at is not an ISO 8601 UTC timestamp: {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at", "")), (
        f"updated_at is not an ISO 8601 UTC timestamp: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_envelope_object(response) -> Dict[str, Any]:
    """Assert a single-resource envelope and return its data."""
    body = response.json()
    assert body.get("response_type") == "object", (
        f"Expected response_type 'object', got {body.get('response_type')!r}"
    )
    meta = body.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must be a string beginning 'req_': {meta.get('api_request_id')!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"meta.api_request_timestamp must be ISO 8601 UTC: {meta.get('api_request_timestamp')!r}"
    )
    return body["data"]


def assert_envelope_array(response) -> tuple:
    """Assert a collection envelope and return (rows, meta)."""
    body = response.json()
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got {body.get('response_type')!r}"
    )
    return validate_paginated(response)


def assert_created(response) -> Dict[str, Any]:
    """A creation endpoint answers 201 with a fully-formed resource."""
    data = validate_success(response, 201)
    assert_common_fields(data, expected_version=1)
    return data


def assert_ok(response) -> Dict[str, Any]:
    """A non-creation endpoint answers 200."""
    return validate_success(response, 200)


# ─── Pagination ──────────────────────────────────────────────────────────────
def assert_page(
    response,
    expected_ids: Optional[List[str]] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> tuple:
    """Assert a page's contents, ordering and metadata in one call."""
    rows, meta = validate_paginated(response)
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    if expected_ids is not None:
        assert [row["id"] for row in rows] == expected_ids, (
            f"Expected rows {expected_ids}, got {[row['id'] for row in rows]}"
        )
    return rows, meta


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Collections are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"Rows are not in created_at ascending order: {stamps}"


# ─── Field-level shorthands ──────────────────────────────────────────────────
def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert several fields of one resource, reporting all mismatches at once."""
    wrong = {
        key: (entity.get(key), value)
        for key, value in expected.items()
        if entity.get(key) != value
    }
    assert not wrong, "Field mismatches (field: got != want): " + ", ".join(
        f"{k}: {got!r} != {want!r}" for k, (got, want) in wrong.items()
    )


def assert_null_fields(entity: Dict[str, Any], *names: str) -> None:
    """Assert that each named field is present and null."""
    for name in names:
        assert entity.get(name, "MISSING") is None, (
            f"Expected {name} to be null, got {entity.get(name, 'MISSING')!r}"
        )


def assert_not_null_fields(entity: Dict[str, Any], *names: str) -> None:
    for name in names:
        assert entity.get(name) is not None, f"Expected {name} to be set, got null"


# ─── Ledger and counter identities ───────────────────────────────────────────
def assert_estate_value_identity(estate: Dict[str, Any], designations: List[Dict[str, Any]]) -> None:
    """gross_digital_estate_cents == undistributed_value_cents + the received sum."""
    received = sum(d.get("received_value_cents", 0) for d in designations)
    assert estate["gross_digital_estate_cents"] == estate["undistributed_value_cents"] + received, (
        "Value ledger broken: gross "
        f"{estate['gross_digital_estate_cents']} != undistributed "
        f"{estate['undistributed_value_cents']} + received {received}"
    )


def assert_refund_recovered_identity(estate: Dict[str, Any], claims: List[Dict[str, Any]]) -> None:
    """refund_recovered_cents == the credited sum over claims still CREDITED."""
    credited = sum(
        c.get("credited_cents", 0) for c in claims if c.get("status") == "CREDITED"
    )
    assert estate["refund_recovered_cents"] == credited, (
        "Refund ledger broken: refund_recovered_cents "
        f"{estate['refund_recovered_cents']} != sum of credited claims {credited}"
    )


def assert_inventory_counter_identity(estate: Dict[str, Any]) -> None:
    """inventory_total_count == pending + disposed."""
    total = estate["inventory_total_count"]
    pending = estate["assets_pending_disposition_count"]
    disposed = estate["assets_disposed_count"]
    assert total == pending + disposed, (
        f"Inventory counters broken: {total} != {pending} + {disposed}"
    )


# ─── Money and time ──────────────────────────────────────────────────────────
def assert_integer_cents(value: Any, name: str = "amount") -> None:
    """Every monetary field is a whole number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{name} must be an integer number of cents, got {value!r}"
    )


def assert_date_only(value: str, name: str = "date") -> None:
    """A date-only field is a bare calendar date with no time part."""
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{name} must be a bare YYYY-MM-DD date, got {value!r}"
    )


def assert_utc_timestamp(value: str, name: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), (
        f"{name} must be an ISO 8601 UTC timestamp, got {value!r}"
    )
