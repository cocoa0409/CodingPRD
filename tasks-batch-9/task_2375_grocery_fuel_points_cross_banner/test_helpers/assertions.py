"""Domain-specific assertion helpers.

Generic helpers (``validate_success``, ``validate_error``, ``validate_paginated``,
``is_valid_uuid``, ``is_iso8601_timestamp`` ...) come from the framework and are
re-exported by ``test_helpers``; only assertions that encode a rule from this
PRD live here.
"""
from datetime import datetime
from typing import Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import BANNER_DEFAULTS


def assert_common_fields(entity: dict, expected_version: Optional[int] = None) -> None:
    """Every entity except a ledger entry carries `id`, `created_at`,
    `updated_at` and `version`."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), entity["version"]
    assert entity["version"] >= 1, entity["version"]
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_created_shape(entity: dict) -> None:
    """A freshly created entity starts at version 1 with matching timestamps."""
    assert_common_fields(entity, expected_version=1)
    assert entity["created_at"] == entity["updated_at"], (
        f"created_at {entity['created_at']} != updated_at {entity['updated_at']}"
    )


def assert_no_version_field(entity: dict) -> None:
    """A point ledger entry is append-only and carries no version counter."""
    assert "version" not in entity, "ledger entry must not expose a version"
    assert "updated_at" not in entity, "ledger entry must not expose updated_at"


def assert_ledger_entry_shape(entry: dict) -> None:
    """A ledger entry carries only `id` and `created_at` from the common set."""
    assert is_valid_uuid(entry["id"]), entry["id"]
    assert is_iso8601_timestamp(entry["created_at"]), entry["created_at"]
    assert_no_version_field(entry)


def assert_banner_defaults(banner: dict) -> None:
    """Every configuration knob omitted at registration comes back at its
    declared default."""
    for field, default in BANNER_DEFAULTS.items():
        assert banner[field] == default, (
            f"{field}: expected default {default!r}, got {banner[field]!r}"
        )


def assert_household_aggregates_zeroed(household: dict) -> None:
    """A newly created household starts with every derived aggregate at zero."""
    assert household["linked_member_count"] == 0, household["linked_member_count"]
    assert household["aggregate_available_points"] == 0, household["aggregate_available_points"]
    assert household["fraud_score"] == 0, household["fraud_score"]
    assert household["cross_banner_member_ids"] == [], household["cross_banner_member_ids"]


def assert_member_balances(
    member: dict, available_points: int, lifetime_points: Optional[int] = None
) -> None:
    """Both member figures are projections recomputed from the ledger."""
    assert member["available_points"] == available_points, (
        f"expected available_points {available_points}, got {member['available_points']}"
    )
    if lifetime_points is not None:
        assert member["lifetime_points"] == lifetime_points, (
            f"expected lifetime_points {lifetime_points}, got {member['lifetime_points']}"
        )


def assert_ledger_deltas(entries: Iterable[dict], expected: List[int]) -> None:
    """The ledger rows for a member, in creation order, carry exactly these
    signed point movements."""
    actual = [e["points_delta"] for e in entries]
    assert actual == expected, f"expected deltas {expected}, got {actual}"


def assert_ledger_entry_types(entries: Iterable[dict], expected: List[str]) -> None:
    actual = [e["entry_type"] for e in entries]
    assert actual == expected, f"expected entry types {expected}, got {actual}"


def assert_points_summary(
    summary: dict,
    available_points: Optional[int] = None,
    pending_authorized_points: Optional[int] = None,
    projected_expiring_points: Optional[int] = None,
    projected_rollover_points: Optional[int] = None,
    projected_available_after_close: Optional[int] = None,
) -> None:
    """The forecast fields of the read-only points summary."""
    expected = {
        "available_points": available_points,
        "pending_authorized_points": pending_authorized_points,
        "projected_expiring_points": projected_expiring_points,
        "projected_rollover_points": projected_rollover_points,
        "projected_available_after_close": projected_available_after_close,
    }
    for field, want in expected.items():
        if want is None:
            continue
        assert summary[field] == want, (
            f"expected {field} {want}, got {summary[field]}"
        )


def assert_instant_equals(actual: Optional[str], expected: Optional[str]) -> None:
    """Compare two ISO 8601 UTC instants by value.

    Timestamps are stamped from the logical clock; the PRD fixes the instant a
    field carries but not whether a whole second is rendered with its three
    fractional digits, so the comparison is on the instant rather than on the
    string.
    """
    if expected is None:
        assert actual is None, f"expected null, got {actual!r}"
        return
    assert actual is not None, f"expected {expected!r}, got null"

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert parse(actual) == parse(expected), f"expected instant {expected}, got {actual}"


def assert_gallons_equal(actual, expected: str) -> None:
    """Gallon volumes are decimals carried to three places; compare on value so
    a string and a numeric encoding of the same volume both pass."""
    from decimal import Decimal

    assert Decimal(str(actual)) == Decimal(expected), (
        f"expected {expected} gallons, got {actual}"
    )


def assert_ledger_sum(entries: Iterable[dict], expected: int) -> None:
    """The member's available balance is the sum of their ledger rows."""
    total = sum(e["points_delta"] for e in entries)
    assert total == expected, f"expected ledger sum {expected}, got {total}"


def assert_ids_equal(actual: Iterable[dict], expected_ids: List[str]) -> None:
    actual_ids = [item["id"] for item in actual]
    assert actual_ids == expected_ids, f"expected ids {expected_ids}, got {actual_ids}"


def assert_id_set(actual: Iterable[dict], expected_ids: Iterable[str]) -> None:
    """Order-insensitive membership check for a listing."""
    actual_ids = {item["id"] for item in actual}
    assert actual_ids == set(expected_ids), (
        f"expected ids {sorted(set(expected_ids))}, got {sorted(actual_ids)}"
    )


def assert_pagination_meta(
    meta: dict, total_count: int, limit: int, offset: int, has_more: bool
) -> None:
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )
