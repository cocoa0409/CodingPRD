"""Domain assertions for the Studio Operations API.

Thin wrappers over the framework's structural helpers, expressed in the
vocabulary of this PRD so that individual tests read as statements about the
studio rather than about dictionaries.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import DECIMAL_TOLERANCE


# ─── Identity and timestamps (§2.5) ────────────────────────────────────────

def assert_prefix_free_uuid(value: Any) -> None:
    """Assert the id is "a UUID string with no type prefix of any kind"."""
    assert isinstance(value, str), f"id must be a string, got {value!r}"
    assert is_valid_uuid(value), f"id must be a prefix-free UUID, got {value!r}"


def assert_three_fraction_timestamp(value: Any) -> None:
    """Assert an ISO 8601 UTC instant "rendered with exactly three fractional-second digits"."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"timestamp must end in Z: {value!r}"
    assert "." in value, f"timestamp must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits: {value!r}"
    )


def assert_versioned_resource(row: Dict[str, Any]) -> None:
    """Assert the common identity/version envelope every versioned resource carries."""
    assert_prefix_free_uuid(row["id"])
    assert_three_fraction_timestamp(row["created_at"])
    assert_three_fraction_timestamp(row["updated_at"])
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1"


def assert_asset_profile_shape(row: Dict[str, Any]) -> None:
    """Assert the AssetProfile exception: only id and created_at, no updated_at/version."""
    assert_prefix_free_uuid(row["id"])
    assert_three_fraction_timestamp(row["created_at"])
    assert "updated_at" not in row, "AssetProfile must not carry updated_at"
    assert "version" not in row, "AssetProfile must not carry version"


# ─── Money and precision (§2.8) ────────────────────────────────────────────

def assert_whole_cents(value: Any, field: str = "amount") -> None:
    """Assert a monetary field is an integer number of whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of whole cents, got {value!r}"
    )


def assert_two_decimals(value: Any, expected: float, field: str = "value") -> None:
    """Assert a two-decimal figure equals the expected value."""
    assert value is not None, f"{field} must not be null"
    assert float(value) == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_whole_minutes(value: Any, field: str = "minutes") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole number of minutes, got {value!r}"
    )


# ─── State assertions ──────────────────────────────────────────────────────

def assert_content_state(style: Dict[str, Any], expected: str) -> None:
    assert style["content_state"] == expected, (
        f"expected style content_state {expected}, got {style['content_state']}"
    )


def assert_custody(sample: Dict[str, Any], custody: str, match: str) -> None:
    """Assert both independent sample axes at once (§3.3)."""
    assert sample["custody_state"] == custody, (
        f"expected custody_state {custody}, got {sample['custody_state']}"
    )
    assert sample["match_state"] == match, (
        f"expected match_state {match}, got {sample['match_state']}"
    )


def assert_session_state(session: Dict[str, Any], expected: str) -> None:
    assert session["session_state"] == expected, (
        f"expected session_state {expected}, got {session['session_state']}"
    )


def assert_booking_state(booking: Dict[str, Any], expected: str) -> None:
    assert booking["booking_state"] == expected, (
        f"expected booking_state {expected}, got {booking['booking_state']}"
    )


def assert_item_state(item: Dict[str, Any], expected: str) -> None:
    assert item["item_state"] == expected, (
        f"expected item_state {expected}, got {item['item_state']}"
    )


def assert_asset_state(asset: Dict[str, Any], expected: str) -> None:
    assert asset["asset_state"] == expected, (
        f"expected asset_state {expected}, got {asset['asset_state']}"
    )


def assert_task_state(task: Dict[str, Any], expected: str) -> None:
    assert task["task_state"] == expected, (
        f"expected task_state {expected}, got {task['task_state']}"
    )


# ─── Counter assertions (§2.9) ─────────────────────────────────────────────

def assert_vendor_ledger(
    vendor: Dict[str, Any],
    outstanding: Optional[int] = None,
    late: Optional[int] = None,
    hold: Optional[bool] = None,
) -> None:
    if outstanding is not None:
        assert vendor["outstanding_sample_count"] == outstanding, (
            f"expected outstanding_sample_count {outstanding}, "
            f"got {vendor['outstanding_sample_count']}"
        )
    if late is not None:
        assert vendor["late_return_count"] == late, (
            f"expected late_return_count {late}, got {vendor['late_return_count']}"
        )
    if hold is not None:
        assert vendor["coordination_hold"] is hold, (
            f"expected coordination_hold {hold}, got {vendor['coordination_hold']}"
        )


def assert_bumped_by(new_row: Dict[str, Any], old_version: int, increments: int) -> None:
    """Assert a row's version moved by exactly the expected number of increments."""
    assert new_row["version"] == old_version + increments, (
        f"expected version {old_version + increments}, got {new_row['version']}"
    )


# ─── Ordering assertions (§2.3) ────────────────────────────────────────────

def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Assert "List results are always ordered by created_at ascending"."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert [row["id"] for row in rows] == expected_ids, (
        f"expected ids {expected_ids}, got {[row['id'] for row in rows]}"
    )
