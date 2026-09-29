"""Domain assertions for the induction mentorship API.

Timestamps are compared as instants rather than as strings, because the PRD
mandates an ISO 8601 UTC timestamp with three fractional digits while the
instants a test supplies to the logical clock are written without them; the two
spellings denote the same moment and must compare equal.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, field: str = "timestamp") -> None:
    """Assert two ISO 8601 spellings denote the same UTC instant."""
    assert actual is not None, f"{field} must be stamped, got None"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field} should be the instant {expected}, got {actual}"
    )


def assert_three_fractional_digits(value: str, field: str = "timestamp") -> None:
    """Assert a stored timestamp carries three fractional digits, per the PRD."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"
    assert "." in value, f"{field} must carry three fractional digits, got {value!r}"
    fraction = value.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


def assert_date_component(actual: Optional[str], expected_date: str, field: str = "date") -> None:
    """Assert an instant falls on a given UTC calendar date."""
    assert actual is not None, f"{field} must be present, got None"
    assert parse_instant(actual).date().isoformat() == expected_date, (
        f"{field} should fall on {expected_date}, got {actual}"
    )


def assert_system_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the audit stamps every mutable entity carries."""
    assert is_valid_uuid(row.get("id")), f"id must be a UUID with no type prefix, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"version should be {expected_version}, got {row['version']}"
        )


def assert_immutable_system_fields(row: Dict[str, Any]) -> None:
    """Assert an immutable configuration row carries only id and created_at."""
    assert is_valid_uuid(row.get("id")), f"id must be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, "an immutable milestone definition must have no updated_at"
    assert "version" not in row, "an immutable milestone definition must have no version"


def assert_money_cents(value: Any, expected: int, field: str = "cents") -> None:
    """Assert a money field is an exact integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be held in integer cents, got {value!r}"
    )
    assert value == expected, f"{field} should be {expected} cents, got {value}"


def assert_two_decimals(value: Any, expected: float, field: str = "value") -> None:
    """Assert a 2-decimal-place quantity equals its expected value."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert value == pytest.approx(expected, abs=0.005), (
        f"{field} should be {expected:.2f}, got {value}"
    )


def assert_four_decimals(value: Any, expected: float, field: str = "ratio") -> None:
    """Assert a 4-decimal-place ratio equals its expected value."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert value == pytest.approx(expected, abs=0.00005), (
        f"{field} should be {expected:.4f}, got {value}"
    )


def assert_pagination_defaults(meta: Dict[str, Any]) -> None:
    """Assert the list envelope carries the PRD's default page window."""
    assert meta["limit"] == 10, f"limit should default to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset should default to 0, got {meta['offset']}"


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Assert a list read is sorted by created_at ascending."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "list results must be sorted by created_at ascending"


def assert_ascending_by(rows: List[Dict[str, Any]], field: str) -> None:
    """Assert a list read is sorted ascending by a named field."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"list results must be sorted by {field} ascending"


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    """Collect the ids of a list read, preserving order."""
    return [row["id"] for row in rows]


def assert_novice_counters(
    novice: Dict[str, Any],
    verified_contact_minutes: Optional[int] = None,
    documented_observation_cycles: Optional[int] = None,
    credited_seminar_sessions: Optional[int] = None,
    attained_milestone_count: Optional[int] = None,
    readiness_index_live: Optional[float] = None,
    readiness_index_snapshot: Optional[float] = None,
) -> None:
    """Assert whichever progress counters a caller names."""
    if verified_contact_minutes is not None:
        assert novice["verified_contact_minutes"] == verified_contact_minutes, (
            f"verified_contact_minutes should be {verified_contact_minutes}, "
            f"got {novice['verified_contact_minutes']}"
        )
    if documented_observation_cycles is not None:
        assert novice["documented_observation_cycles"] == documented_observation_cycles, (
            f"documented_observation_cycles should be {documented_observation_cycles}, "
            f"got {novice['documented_observation_cycles']}"
        )
    if credited_seminar_sessions is not None:
        assert novice["credited_seminar_sessions"] == credited_seminar_sessions, (
            f"credited_seminar_sessions should be {credited_seminar_sessions}, "
            f"got {novice['credited_seminar_sessions']}"
        )
    if attained_milestone_count is not None:
        assert novice["attained_milestone_count"] == attained_milestone_count, (
            f"attained_milestone_count should be {attained_milestone_count}, "
            f"got {novice['attained_milestone_count']}"
        )
    if readiness_index_live is not None:
        assert_two_decimals(
            novice["readiness_index_live"], readiness_index_live, "readiness_index_live"
        )
    if readiness_index_snapshot is not None:
        assert_two_decimals(
            novice["readiness_index_snapshot"],
            readiness_index_snapshot,
            "readiness_index_snapshot",
        )
