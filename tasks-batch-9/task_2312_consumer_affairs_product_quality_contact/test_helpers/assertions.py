"""Domain assertions layered on top of the generic framework helpers."""

import re
from typing import Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import APPEND_ONLY_COMMON_FIELDS, VERSIONED_COMMON_FIELDS

_BARE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_MILLIS_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------
def assert_bare_uuid(value) -> None:
    """Identifiers are bare UUIDs with no prefix of any kind."""
    assert isinstance(value, str), f"identifier must be a string, got {value!r}"
    assert _BARE_UUID.match(value), f"identifier is not a bare UUID: {value!r}"
    assert is_valid_uuid(value), f"identifier is not a valid UUID: {value!r}"


def assert_millisecond_timestamp(value) -> None:
    """Timestamps are ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert _MILLIS_TIMESTAMP.match(value), (
        f"timestamp must carry exactly three fractional digits and a Z suffix: {value!r}"
    )
    assert is_iso8601_timestamp(value), f"timestamp is not ISO 8601: {value!r}"


def assert_versioned_common_fields(record: dict, expected_version: Optional[int] = None) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    for field in VERSIONED_COMMON_FIELDS:
        assert field in record, f"missing common field {field!r}"
    assert_bare_uuid(record["id"])
    assert_millisecond_timestamp(record["created_at"])
    assert_millisecond_timestamp(record["updated_at"])
    assert isinstance(record["version"], int), "version must be an integer"
    assert record["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_append_only_common_fields(record: dict) -> None:
    """An append-only resource carries id and created_at and nothing else common."""
    for field in APPEND_ONLY_COMMON_FIELDS:
        assert field in record, f"missing common field {field!r}"
    assert_bare_uuid(record["id"])
    assert_millisecond_timestamp(record["created_at"])
    assert "updated_at" not in record, "an append-only record has no updated_at"
    assert "version" not in record, "an append-only record has no version"


# ---------------------------------------------------------------------------
# Numeric conventions
# ---------------------------------------------------------------------------
def assert_two_decimal_value(actual, expected) -> None:
    """A two-decimal quantity, compared at its own precision."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"expected {expected}, got {actual}"
    )


def assert_whole_cents(value) -> None:
    """Monetary amounts are whole numbers of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"monetary value must be a whole number of cents, got {value!r}"
    )


def assert_goodwill_math(
    remedy: dict,
    base_value_cents: int,
    uplift_pct: float,
    uplift_cents: int,
    payout_cents: int,
    authority_tier_required: str,
) -> None:
    """The full goodwill chain published on a remedy."""
    assert remedy["base_value_cents"] == base_value_cents
    assert_two_decimal_value(remedy["uplift_pct"], uplift_pct)
    assert remedy["uplift_cents"] == uplift_cents
    assert remedy["payout_cents"] == payout_cents
    assert remedy["payout_cents"] == remedy["base_value_cents"] + remedy["uplift_cents"]
    assert remedy["authority_tier_required"] == authority_tier_required
    for field in ("base_value_cents", "uplift_cents", "payout_cents"):
        assert_whole_cents(remedy[field])


def assert_severity(
    complaint: dict,
    provisional_score=None,
    provisional_band=None,
    adjudicated_score=None,
    adjudicated_band=None,
    effective_band=None,
) -> None:
    if provisional_score is not None:
        assert_two_decimal_value(complaint["provisional_severity_score"], provisional_score)
    if provisional_band is not None:
        assert complaint["provisional_severity_band"] == provisional_band
    if adjudicated_score is not None:
        assert_two_decimal_value(complaint["adjudicated_severity_score"], adjudicated_score)
    if adjudicated_band is not None:
        assert complaint["adjudicated_severity_band"] == adjudicated_band
    if effective_band is not None:
        assert complaint["effective_severity_band"] == effective_band


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
def assert_goodwill_ledger(
    consumer: dict,
    authorized: Optional[int] = None,
    outstanding: Optional[int] = None,
    paid: Optional[int] = None,
    voided: Optional[int] = None,
) -> None:
    """Paid plus outstanding plus voided always equals authorized."""
    if authorized is not None:
        assert consumer["goodwill_authorized_cents"] == authorized
    if outstanding is not None:
        assert consumer["goodwill_outstanding_cents"] == outstanding
    if paid is not None:
        assert consumer["goodwill_paid_cents"] == paid
    if voided is not None:
        assert consumer["goodwill_voided_cents"] == voided
    assert (
        consumer["goodwill_paid_cents"]
        + consumer["goodwill_outstanding_cents"]
        + consumer["goodwill_voided_cents"]
        == consumer["goodwill_authorized_cents"]
    ), (
        "paid + outstanding + voided must equal authorized, got "
        f"{consumer['goodwill_paid_cents']} + {consumer['goodwill_outstanding_cents']}"
        f" + {consumer['goodwill_voided_cents']} != {consumer['goodwill_authorized_cents']}"
    )


def assert_lot_buckets(
    lot: dict,
    linked: Optional[int] = None,
    provisional: Optional[int] = None,
    adjudicated: Optional[int] = None,
    duplicate: Optional[int] = None,
) -> None:
    """The three complaint buckets partition the linked total exactly."""
    if linked is not None:
        assert lot["linked_complaint_count"] == linked
    if provisional is not None:
        assert lot["provisional_complaint_count"] == provisional
    if adjudicated is not None:
        assert lot["adjudicated_complaint_count"] == adjudicated
    if duplicate is not None:
        assert lot["duplicate_complaint_count"] == duplicate
    assert (
        lot["provisional_complaint_count"]
        + lot["adjudicated_complaint_count"]
        + lot["duplicate_complaint_count"]
        == lot["linked_complaint_count"]
    ), "the three buckets must sum to linked_complaint_count"


def assert_unchanged(before: dict, after: dict, *fields: str) -> None:
    """The named fields did not move between two reads of the same resource."""
    for field in fields:
        assert before[field] == after[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
def assert_ids_exactly(items: Iterable[dict], expected_ids: Iterable[str]) -> None:
    """The listing returned exactly this id set, each id once."""
    actual = [item["id"] for item in items]
    assert len(actual) == len(set(actual)), f"duplicate ids in listing: {actual}"
    assert set(actual) == set(expected_ids), (
        f"expected ids {sorted(set(expected_ids))}, got {sorted(set(actual))}"
    )


def assert_pagination_meta(
    meta: dict,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_error_envelope(response) -> dict:
    """The error envelope shape itself, independent of which error it carries."""
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert isinstance(body["data"]["error_id"], str)
    assert body["data"]["message"].strip(), "an error carries a non-empty message"
    return body["data"]


def assert_request_meta(response) -> dict:
    """Every response carries a correlation id prefixed ``req_``."""
    meta = response.json()["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"], (
        "api_request_id must be a non-empty string"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert isinstance(meta["api_request_timestamp"], str)
    return meta
