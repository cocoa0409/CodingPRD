"""Domain assertion helpers for the facilities capacity API."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import CHASSIS, PAD_CLEARANCE_TOTAL_FT, RATED_SEATS


def assert_system_fields(row: Dict[str, Any], *, versioned: bool = True) -> None:
    """`id` is a server-minted UUID and `created_at` an ISO 8601 UTC instant."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {row['created_at']!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(row["updated_at"]), (
            f"updated_at is not an ISO 8601 UTC timestamp: {row['updated_at']!r}"
        )
        assert isinstance(row["version"], int)


def _parse_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_clock_stamp(actual: Any, expected_iso: str) -> None:
    """A logical-clock stamp records the clock's instant, whatever its rendering.

    PRD §2.4 fixes a rendering — "an ISO 8601 UTC timestamp with three fractional
    digits" — only for `created_at`; of `submitted_on`, `approved_on`,
    `certified_on` and `disposed_on` it says only that they "are all derived from
    this clock".  So compare the instant, not its textual form.
    """
    assert isinstance(actual, str) and actual.strip(), (
        f"expected an ISO 8601 clock stamp, got {actual!r}"
    )
    try:
        got = _parse_instant(actual)
    except ValueError as exc:  # pragma: no cover - assertion path
        raise AssertionError(f"not an ISO 8601 instant: {actual!r}") from exc
    assert got.tzinfo is not None, f"clock stamp is not UTC-qualified: {actual!r}"
    want = _parse_instant(expected_iso)
    assert got == want, (
        f"clock stamp {actual!r} does not record the logical-clock instant "
        f"{expected_iso!r}"
    )


_THREE_FRACTIONAL_DIGITS = re.compile(r"\.\d{3}(?:Z|z|[+-]\d{2}:?\d{2})$")


def assert_created_at(row: Dict[str, Any], expected_iso: str) -> None:
    """`created_at` is the logical-clock instant, "with three fractional digits".

    PRD §2.4 states both halves for this field: it is stamped from the logical
    clock and it is "an ISO 8601 UTC timestamp with three fractional digits".
    """
    stamp = row["created_at"]
    assert_clock_stamp(stamp, expected_iso)
    assert _THREE_FRACTIONAL_DIGITS.search(stamp), (
        f"created_at must carry three fractional digits: {stamp!r}"
    )


def assert_ledger_row(row: Dict[str, Any]) -> None:
    """An append-only ledger row carries no `updated_at` and no `version`."""
    assert_system_fields(row, versioned=False)
    assert "updated_at" not in row, "ledger rows carry no updated_at"
    assert "version" not in row, "ledger rows carry no version"


def assert_capacity_fields(
    study: Dict[str, Any],
    *,
    gross_room_seats: Optional[int] = None,
    set_aside_deduction_seats: Optional[int] = None,
    program_capacity_seats: Optional[int] = None,
    projected_enrollment_total: Optional[int] = None,
    utilization_pct: Optional[float] = None,
    portable_trigger_met: Optional[bool] = None,
    seat_deficit: Optional[int] = None,
    required_portable_count: Optional[int] = None,
) -> None:
    """Compare the frozen capacity block of a study against expected values."""
    expected = {
        "gross_room_seats": gross_room_seats,
        "set_aside_deduction_seats": set_aside_deduction_seats,
        "program_capacity_seats": program_capacity_seats,
        "projected_enrollment_total": projected_enrollment_total,
        "utilization_pct": utilization_pct,
        "portable_trigger_met": portable_trigger_met,
        "seat_deficit": seat_deficit,
        "required_portable_count": required_portable_count,
    }
    for field, value in expected.items():
        if value is not None:
            assert study[field] == value, (
                f"{field}: expected {value}, got {study[field]}"
            )


def assert_budget_partition(
    budget: Dict[str, Any],
    *,
    authorized_cents: int,
    encumbered_cents: int,
    expended_cents: int,
    uncommitted_cents: int,
) -> None:
    """The three buckets must hold their stated values and sum to the appropriation."""
    assert budget["authorized_cents"] == authorized_cents
    assert budget["encumbered_cents"] == encumbered_cents
    assert budget["expended_cents"] == expended_cents
    assert budget["uncommitted_cents"] == uncommitted_cents
    assert (
        budget["encumbered_cents"] + budget["expended_cents"]
        + budget["uncommitted_cents"] == budget["authorized_cents"]
    ), f"partition does not sum to the appropriation: {budget}"


def assert_cost_breakdown(model: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Compare the named components of a cost model response."""
    for field, value in expected.items():
        assert model[field] == value, f"{field}: expected {value}, got {model[field]}"


def assert_unit_dimensions(size_class: str, pad_length_ft: float,
                           pad_width_ft: float) -> None:
    """A pad fits a chassis when it clears the chassis footprint plus 5 ft a side."""
    length, width = CHASSIS[size_class][0], CHASSIS[size_class][1]
    assert pad_length_ft >= length + PAD_CLEARANCE_TOTAL_FT
    assert pad_width_ft >= width + PAD_CLEARANCE_TOTAL_FT


def assert_rated_seats(unit: Dict[str, Any]) -> None:
    """`rated_seats` is derived from the size class, never supplied."""
    assert unit["rated_seats"] == RATED_SEATS[unit["size_class"]]


def assert_unit_state(unit: Dict[str, Any], *, allocation_status: str,
                      condition_status: Optional[str] = None,
                      condition_grade: Optional[str] = None) -> None:
    """Both state dimensions of a portable unit."""
    assert unit["allocation_status"] == allocation_status
    if condition_status is not None:
        assert unit["condition_status"] == condition_status
    if condition_grade is not None:
        assert unit["condition_grade"] == condition_grade


def assert_ids_in_order(rows: Sequence[Dict[str, Any]],
                        expected_ids: Sequence[str]) -> None:
    """Rows arrive in exactly the expected order."""
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"order mismatch: {[row['id'] for row in rows]} != {list(expected_ids)}"
    )


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """List results are ordered by `created_at` ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"not ascending by created_at: {stamps}"


def assert_page_meta(meta: Dict[str, Any], *, limit: int, offset: int,
                     total_count: int, has_more: bool) -> None:
    """The four members of a list response's `meta` object."""
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more


def assert_mitigation_flags(site: Dict[str, Any],
                            expected: List[str]) -> None:
    """Mitigation flags arrive in the declared order."""
    assert site["mitigation_flags"] == expected, (
        f"mitigation flags: expected {expected}, got {site['mitigation_flags']}"
    )
