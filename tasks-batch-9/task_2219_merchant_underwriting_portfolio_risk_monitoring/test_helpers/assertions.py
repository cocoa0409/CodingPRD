"""Domain assertions over the API's entity shapes and envelope."""

from __future__ import annotations

from typing import Any, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import REQUEST_ID_PREFIX

VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")


def assert_envelope(body: dict[str, Any], expected_response_type: str) -> None:
    """The standard envelope: meta with a req_-prefixed id, a response_type, data."""
    assert set(body.keys()) >= {"meta", "response_type", "data"}
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        f"api_request_id must start with '{REQUEST_ID_PREFIX}', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp not ISO 8601: {meta['api_request_timestamp']!r}"
    )
    assert body["response_type"] == expected_response_type


def assert_versioned_entity(entity: dict[str, Any]) -> None:
    """A mutable entity carries id, created_at, updated_at and version."""
    for field in VERSIONED_COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r}"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int) and entity["version"] >= 1


def assert_append_only_entity(entity: dict[str, Any]) -> None:
    """An append-only entity carries only id and created_at - no version, no updated_at."""
    for field in APPEND_ONLY_COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r}"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert "updated_at" not in entity, "append-only entity must not expose updated_at"
    assert "version" not in entity, "append-only entity must not expose version"


def assert_fields(entity: dict[str, Any], **expected: Any) -> None:
    """Assert a bundle of field values with one clear message per mismatch."""
    mismatches = []
    for key, want in expected.items():
        assert key in entity, f"field {key!r} missing from {sorted(entity)}"
        got = entity[key]
        if isinstance(want, float) or isinstance(got, float):
            if got != pytest.approx(want, abs=0.005):
                mismatches.append(f"{key}: expected {want!r}, got {got!r}")
        elif got != want:
            mismatches.append(f"{key}: expected {want!r}, got {got!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_pct(entity: dict[str, Any], field: str, expected: float) -> None:
    """Two-decimal percentage comparison (ownership percentages)."""
    assert float(entity[field]) == pytest.approx(expected, abs=0.005), (
        f"{field}: expected {expected}, got {entity[field]!r}"
    )


def assert_ids_in_order(rows: Iterable[dict[str, Any]], expected_ids: list[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected order {expected_ids}, got {actual}"


def assert_page_meta(
    meta: dict[str, Any],
    total_count: int,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    assert meta["total_count"] == total_count, (
        f"total_count: expected {total_count}, got {meta['total_count']}"
    )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_ledger_conservation(reserve_account: dict[str, Any]) -> None:
    """total_accrued = held + released + offset, for any reserve account."""
    total = reserve_account["total_accrued_cents"]
    parts = (
        reserve_account["held_balance_cents"]
        + reserve_account["released_to_date_cents"]
        + reserve_account["offset_to_date_cents"]
    )
    assert total == parts, (
        "reserve ledger conservation broken: total_accrued_cents "
        f"{total} != held {reserve_account['held_balance_cents']} + released "
        f"{reserve_account['released_to_date_cents']} + offset "
        f"{reserve_account['offset_to_date_cents']}"
    )


def assert_batch_conservation(batch: dict[str, Any]) -> None:
    """gross = net_payout + reserve_hold + loss_offset_from_settlement."""
    gross = batch["gross_volume_cents"]
    parts = (
        batch["net_payout_cents"]
        + batch["reserve_hold_cents"]
        + batch["loss_offset_from_settlement_cents"]
    )
    assert gross == parts, (
        "settlement identity broken: gross_volume_cents "
        f"{gross} != net_payout {batch['net_payout_cents']} + reserve_hold "
        f"{batch['reserve_hold_cents']} + loss_offset "
        f"{batch['loss_offset_from_settlement_cents']}"
    )
