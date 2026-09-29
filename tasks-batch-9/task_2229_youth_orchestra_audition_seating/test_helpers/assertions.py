"""Domain-specific assertion helpers layered on the framework validators."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# --------------------------------------------------------------------------
# Identity / timestamps / version (PRD §2.4)
# --------------------------------------------------------------------------

def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every persisted resource carries `id`, `created_at`, `updated_at`, `version`."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert "_" not in entity["id"], "the id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_sheet_shape(sheet: Dict[str, Any]) -> None:
    """A rubric sheet carries only `id` and `created_at` (PRD §2.4)."""
    assert is_valid_uuid(sheet["id"]), f"id is not a UUID: {sheet['id']!r}"
    assert is_iso8601_timestamp(sheet["created_at"]), sheet["created_at"]
    assert "updated_at" not in sheet, "a rubric sheet has no updated_at field"
    assert "version" not in sheet, "a rubric sheet has no version field"


def assert_three_fraction_digits(timestamp: str) -> None:
    """ISO 8601 UTC instant rendered with three fractional digits (PRD §2.4)."""
    assert is_iso8601_timestamp(timestamp), timestamp
    assert "." in timestamp, f"missing fractional seconds: {timestamp!r}"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits: {timestamp!r}"


# --------------------------------------------------------------------------
# Rounding (PRD §2.7)
# --------------------------------------------------------------------------

def assert_two_decimal_places(value: float) -> None:
    """Scores carry two decimal places (PRD §2.7)."""
    assert value is not None
    assert round(float(value), 2) == float(value), (
        f"{value!r} is not rounded to two decimal places"
    )


def assert_whole_cents(value: Any) -> None:
    """Monetary amounts are integers in whole cents (PRD §2.7)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"expected an integer number of cents, got {value!r}"
    )


# --------------------------------------------------------------------------
# Aid pool invariant (PRD §2.11)
# --------------------------------------------------------------------------

def assert_aid_pool_conserved(season: Dict[str, Any]) -> None:
    """`aid_committed_cents` plus `aid_available_cents` equals `aid_budget_cents`."""
    assert (
        season["aid_committed_cents"] + season["aid_available_cents"]
        == season["aid_budget_cents"]
    ), (
        f"aid pool not conserved: committed={season['aid_committed_cents']} "
        f"available={season['aid_available_cents']} budget={season['aid_budget_cents']}"
    )
    assert season["aid_available_cents"] >= 0, "aid_available_cents went negative"


# --------------------------------------------------------------------------
# Balance identity (PRD §3.7)
# --------------------------------------------------------------------------

def assert_balance_identity(account: Dict[str, Any]) -> None:
    """balance = assessed - aid_effective + loan_fee - payments (PRD §3.7)."""
    expected = (
        account["assessed_cents"]
        - account["aid_effective_cents"]
        + account["instrument_loan_fee_cents"]
        - account["payments_total_cents"]
    )
    assert account["balance_cents"] == expected, (
        f"expected balance_cents {expected}, got {account['balance_cents']}"
    )


# --------------------------------------------------------------------------
# Chair order (PRD §3.6)
# --------------------------------------------------------------------------

def assert_contiguous_chair_numbers(seats: Iterable[Dict[str, Any]]) -> None:
    """Active chair numbers are exactly 1..filled_count with no gaps or dupes."""
    numbers = sorted(s["chair_number"] for s in seats if s["status"] == "ACTIVE")
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"chair numbers are not contiguous from 1: {numbers}"
    )


def active_seats(seats: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in seats if s["status"] == "ACTIVE"]


def seat_by_chair_number(seats: Iterable[Dict[str, Any]], chair_number: int) -> Dict[str, Any]:
    matches = [
        s for s in seats if s["status"] == "ACTIVE" and s["chair_number"] == chair_number
    ]
    assert len(matches) == 1, f"expected one ACTIVE chair {chair_number}, got {len(matches)}"
    return matches[0]


# --------------------------------------------------------------------------
# Pagination meta (PRD §2.3)
# --------------------------------------------------------------------------

def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_limit: int,
    expected_offset: int,
    expected_total: int,
    expected_has_more: bool,
) -> None:
    assert meta["limit"] == expected_limit, meta
    assert meta["offset"] == expected_offset, meta
    assert meta["total_count"] == expected_total, meta
    assert meta["has_more"] is expected_has_more, meta


def assert_sorted_by_created_at_asc(rows: List[Dict[str, Any]]) -> None:
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"rows are not sorted by created_at ASC: {stamps}"


# --------------------------------------------------------------------------
# Instant arithmetic on the logical clock
# --------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_instant(value: str, **delta: Any) -> str:
    """Return `value` moved by the supplied timedelta keyword arguments."""
    return format_instant(parse_instant(value) + timedelta(**delta))


def assert_instants_equal(actual: str, expected: str) -> None:
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )
