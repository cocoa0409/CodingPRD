"""Domain assertion helpers.

These wrap the repeated shape checks: the four system-managed properties,
the three numeric precision families, and small lookups over pick ledgers.
"""

import re
from typing import Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ISO 8601 UTC with exactly three fractional digits.
_MILLIS_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# System-managed properties
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict, expected_version: Optional[int] = None) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version


def assert_millisecond_timestamp(value: str) -> None:
    """Timestamps are ISO 8601 UTC with three fractional digits."""
    assert _MILLIS_UTC.match(value), f"not a millisecond UTC timestamp: {value}"


def assert_version_is(entity: Dict, expected: int) -> None:
    assert entity["version"] == expected, (
        f"expected version {expected}, saw {entity['version']}"
    )


# ---------------------------------------------------------------------------
# Numeric precision families
# ---------------------------------------------------------------------------


def assert_chart_points(actual: float, expected: float) -> None:
    """Trade chart points carry one decimal place."""
    assert actual == pytest.approx(expected, abs=0.01)


def assert_imbalance_ratio(actual: float, expected: float) -> None:
    """The trade imbalance ratio carries four decimal places."""
    assert actual == pytest.approx(expected, abs=0.00001)


def assert_score(actual: float, expected: float) -> None:
    """Compensatory scores carry two decimal places."""
    assert actual == pytest.approx(expected, abs=0.01)


def assert_whole_cents(value) -> None:
    """Money is always an integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"money must be whole cents as an integer, saw {value!r}"
    )


def assert_cents_equal(actual, expected: int) -> None:
    assert_whole_cents(actual)
    assert actual == expected, f"expected {expected} cents, saw {actual}"


# ---------------------------------------------------------------------------
# Pagination envelope
# ---------------------------------------------------------------------------


def assert_pagination_meta(
    meta: Dict,
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"missing pagination field {key}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more


# ---------------------------------------------------------------------------
# Pick ledger lookups
# ---------------------------------------------------------------------------


def pick_by_overall_number(picks: List[Dict], overall_number: int) -> Dict:
    for pick in picks:
        if pick["overall_number"] == overall_number:
            return pick
    raise AssertionError(f"no pick with overall_number {overall_number}")


def pick_by_slot(picks: List[Dict], round_number: int, pick_in_round: int) -> Dict:
    for pick in picks:
        if (
            pick["round_number"] == round_number
            and pick["pick_in_round"] == pick_in_round
        ):
            return pick
    raise AssertionError(
        f"no pick at round {round_number} slot {pick_in_round}"
    )


def picks_of_club(picks: List[Dict], club_id: str) -> List[Dict]:
    return [p for p in picks if p["owning_club_id"] == club_id]


def find_by_id(rows: List[Dict], row_id: str) -> Dict:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError(f"no row with id {row_id}")


# ---------------------------------------------------------------------------
# Prospect dimension helper
# ---------------------------------------------------------------------------


def assert_prospect_dimensions(prospect: Dict, **expected) -> None:
    """Assert any subset of a prospect's parallel status dimensions."""
    for field, value in expected.items():
        assert prospect[field] == value, (
            f"{field}: expected {value!r}, saw {prospect[field]!r}"
        )
