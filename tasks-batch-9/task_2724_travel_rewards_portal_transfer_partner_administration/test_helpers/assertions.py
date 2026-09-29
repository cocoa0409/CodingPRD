"""
Domain assertions over envelopes, audit fields, ledgers, postures and sweeps.

Each helper restates one PRD rule once, so a test reads as a sentence about the
domain rather than as a pile of dictionary lookups.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_timestamp
from .constants import SWEEP_COUNTERS
from .types import FORBIDDEN_ON_IMMUTABLE

# ─── Envelope (§2.2) ──────────────────────────────────────────────────


def assert_envelope_meta(response, response_type: str = "object") -> Dict[str, Any]:
    """
    Assert the §2.2 envelope: a `req_`-prefixed request id, an ISO 8601 UTC
    timestamp, and the declared `response_type`.
    """
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp is not ISO 8601 UTC: "
        f"{meta['api_request_timestamp']!r}"
    )
    assert body["response_type"] == response_type, (
        f"Expected response_type {response_type!r}, got {body['response_type']!r}"
    )
    return meta


def assert_error_meta_is_minimal(response) -> None:
    """
    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    """
    meta = response.json()["meta"]
    assert set(meta) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must carry exactly the two identity keys, got {sorted(meta)}"
    )


# ─── Audit fields (§2.4) ──────────────────────────────────────────────


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """
    Assert the four audit fields of a mutable collection: a prefix-free UUID `id`,
    a `created_at` and an `updated_at` in ISO 8601 UTC, and an integer `version`.
    """
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not ISO 8601 UTC: {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at is not ISO 8601 UTC: {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )
    return row


def assert_immutable_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    "both carry only `id` and `created_at`. Neither `updated_at` nor `version`
    exists on those two resources at all."
    """
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not ISO 8601 UTC: {row['created_at']!r}"
    )
    for field in FORBIDDEN_ON_IMMUTABLE:
        assert field not in row, (
            f"An immutable row must not carry {field!r}: {sorted(row)}"
        )
    return row


def assert_timestamp_equals(actual: Any, expected: str) -> None:
    """Compare a returned instant against a literal, both canonicalised."""
    assert actual is not None, f"Expected the instant {expected}, got null"
    assert canonical_timestamp(actual) == canonical_timestamp(expected), (
        f"Expected instant {canonical_timestamp(expected)}, "
        f"got {canonical_timestamp(actual)}"
    )


# ─── Accounts and the ledger (§2.7, §3.1) ─────────────────────────────


def assert_account_aggregates(
    row: Dict[str, Any],
    points_balance: Optional[int] = None,
    points_pending_redemption: Optional[int] = None,
    lifetime_points_earned: Optional[int] = None,
    lifetime_points_redeemed: Optional[int] = None,
    transfer_hold_count: Optional[int] = None,
    fraud_posture: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Assert whichever of the derived account aggregates a test pins."""
    expectations = {
        "points_balance": points_balance,
        "points_pending_redemption": points_pending_redemption,
        "lifetime_points_earned": lifetime_points_earned,
        "lifetime_points_redeemed": lifetime_points_redeemed,
        "transfer_hold_count": transfer_hold_count,
        "fraud_posture": fraud_posture,
        "status": status,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert row[field] == expected, (
                f"Expected {field} == {expected!r}, got {row[field]!r}"
            )
    return row


def read_account(api, headers, account_id: str) -> Dict[str, Any]:
    """Read one account and return its row."""
    return validate_success(api.get_account(account_id, headers))


def read_ledger(api, headers, account_id: str) -> List[Dict[str, Any]]:
    """
    Read one account's whole ledger in the §2.7 order — "`occurred_at` ascending
    order with `created_at` ascending as the tie-break".
    """
    response = api.list_ledger_entries(
        headers, {"account_id": account_id, "limit": 100}
    )
    rows, _ = validate_paginated(response)
    return rows


def assert_ledger_entry_types(
    entries: Sequence[Dict[str, Any]], expected: Sequence[str]
) -> None:
    """Assert the `entry_type` sequence of a ledger reading, in ledger order."""
    actual = [entry["entry_type"] for entry in entries]
    assert actual == list(expected), (
        f"Expected ledger entry types {list(expected)}, got {actual}"
    )


def assert_ledger_entry(
    entry: Dict[str, Any],
    entry_type: Optional[str] = None,
    points_delta: Optional[int] = None,
    balance_after: Optional[int] = None,
    source_entity_type: Optional[str] = None,
    source_entity_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Assert the fields of one immutable ledger entry."""
    assert_immutable_row(entry)
    expectations = {
        "entry_type": entry_type,
        "points_delta": points_delta,
        "balance_after": balance_after,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert entry[field] == expected, (
                f"Expected ledger {field} == {expected!r}, got {entry[field]!r}"
            )
    assert is_iso8601_timestamp(entry["occurred_at"]), (
        f"occurred_at is not ISO 8601 UTC: {entry['occurred_at']!r}"
    )
    return entry


def assert_conserved_quantity(account: Dict[str, Any], expected_total: int) -> None:
    """
    "`points_balance` plus `points_pending_redemption` is conserved across every
    reservation and every release."
    """
    total = account["points_balance"] + account["points_pending_redemption"]
    assert total == expected_total, (
        f"Conserved sum should be {expected_total}, got "
        f"{account['points_balance']} + {account['points_pending_redemption']} "
        f"= {total}"
    )


# ─── The sweep (§2.10) ────────────────────────────────────────────────


def assert_sweep_counters(data: Dict[str, Any], **expected: int) -> Dict[str, Any]:
    """
    Assert the eight sweep counters. Every counter the caller does not name is
    asserted to be 0, because "A sweep that finds nothing to do ... returns
    zeroes" and each step reports independently.
    """
    unknown = set(expected) - set(SWEEP_COUNTERS)
    assert not unknown, f"Not sweep counters: {sorted(unknown)}"
    for counter in SWEEP_COUNTERS:
        assert counter in data, f"Sweep response is missing {counter!r}"
        wanted = expected.get(counter, 0)
        assert data[counter] == wanted, (
            f"Expected {counter} == {wanted}, got {data[counter]}"
        )
    assert is_iso8601_timestamp(data["clock_utc"]), (
        f"clock_utc is not ISO 8601 UTC: {data.get('clock_utc')!r}"
    )
    return data


# ─── Listings (§2.3) ──────────────────────────────────────────────────


def assert_page(
    response,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    length: Optional[int] = None,
):
    """Validate a paginated envelope and pin whichever `meta` fields matter."""
    rows, meta = validate_paginated(response)
    expectations = {
        "total_count": total_count,
        "has_more": has_more,
        "limit": limit,
        "offset": offset,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert meta[field] == expected, (
                f"Expected meta.{field} == {expected!r}, got {meta[field]!r}"
            )
    if length is not None:
        assert len(rows) == length, f"Expected {length} rows, got {len(rows)}"
    return rows, meta


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """The `id` of every row, in the order the listing returned them."""
    return [row["id"] for row in rows]


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """"List results are ordered by `created_at` ascending" (§2.3)."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"Rows are not in created_at order: {stamps}"
