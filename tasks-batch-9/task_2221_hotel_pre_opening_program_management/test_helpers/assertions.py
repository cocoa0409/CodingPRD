"""Domain assertions for the hotel pre-opening program management API.

Thin wrappers over the shared structural helpers that add the vocabulary of
this API: program dimensions, posture, ratio precision, money in integer cents,
append-only row shape and the two optimistic-concurrency pools.
"""

from typing import Any, Dict, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    COMMERCIAL_STATES,
    READINESS_POSTURES,
    SCHEDULE_STATES,
)

# ─── Envelope-adjacent structural checks ──────────────────────────────────────


def assert_common_fields(record: Dict[str, Any]) -> None:
    """Every non-append-only record carries id, created_at, updated_at, version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"created_at is not an ISO 8601 UTC instant: {record.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(record["updated_at"]), (
        f"updated_at is not an ISO 8601 UTC instant: {record.get('updated_at')!r}"
    )
    assert isinstance(record["version"], int), "version must be an integer"
    assert record["version"] >= 1, "version starts at 1"


def assert_append_only_row(record: Dict[str, Any]) -> None:
    """Append-only rows carry only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"created_at is not an ISO 8601 UTC instant: {record.get('created_at')!r}"
    )
    assert "updated_at" not in record, (
        "an append-only row must not carry updated_at"
    )
    assert "version" not in record, "an append-only row must not carry version"


def assert_no_version_field(record: Dict[str, Any]) -> None:
    assert "version" not in record, "this record type is not version-guarded"


# ─── Program state ────────────────────────────────────────────────────────────


def assert_program_dimensions(
    program: Dict[str, Any],
    schedule_state: Optional[str] = None,
    commercial_state: Optional[str] = None,
    readiness_posture: Optional[str] = None,
) -> None:
    """Check the two independent state dimensions and the derived posture."""
    assert program["schedule_state"] in SCHEDULE_STATES, (
        f"unknown schedule_state {program['schedule_state']!r}"
    )
    assert program["commercial_state"] in COMMERCIAL_STATES, (
        f"unknown commercial_state {program['commercial_state']!r}"
    )
    assert program["readiness_posture"] in READINESS_POSTURES, (
        f"unknown readiness_posture {program['readiness_posture']!r}"
    )
    if schedule_state is not None:
        assert program["schedule_state"] == schedule_state, (
            f"expected schedule_state {schedule_state}, "
            f"got {program['schedule_state']}"
        )
    if commercial_state is not None:
        assert program["commercial_state"] == commercial_state, (
            f"expected commercial_state {commercial_state}, "
            f"got {program['commercial_state']}"
        )
    if readiness_posture is not None:
        assert program["readiness_posture"] == readiness_posture, (
            f"expected readiness_posture {readiness_posture}, "
            f"got {program['readiness_posture']}"
        )


def assert_posture(program: Dict[str, Any], expected: str) -> None:
    assert program["readiness_posture"] == expected, (
        f"expected readiness_posture {expected}, got {program['readiness_posture']}"
    )


# ─── Numeric conventions ──────────────────────────────────────────────────────


def assert_ratio(actual: Any, expected: float) -> None:
    """Ratios are rounded half up to four decimal places before being reported.

    The tolerance is far tighter than one unit in the fourth decimal place, so
    two distinct four-decimal values can never compare equal here.
    """
    assert actual == pytest.approx(expected, abs=1e-6), (
        f"expected ratio {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int) -> None:
    """Money is carried as an integer count of cents; no fractional cents exist."""
    assert isinstance(actual, int), f"money must be an integer cent count, got {actual!r}"
    assert actual == expected, f"expected {expected} cents, got {actual} cents"


def assert_score(program_or_readiness: Dict[str, Any], expected: float) -> None:
    assert_ratio(program_or_readiness["readiness_score"], expected)


def assert_dates_null(program: Dict[str, Any]) -> None:
    """Before baselining, neither projection nor the authority date exists."""
    assert program["projected_opening_date_optimistic"] is None
    assert program["projected_opening_date_committed"] is None
    assert program.get("projected_opening_date") is None


def assert_committed_is_authority(program_or_readiness: Dict[str, Any]) -> None:
    """The single reported projected opening date always equals the committed one."""
    assert (
        program_or_readiness["projected_opening_date"]
        == program_or_readiness["projected_opening_date_committed"]
    ), (
        "projected_opening_date must equal projected_opening_date_committed: "
        f"{program_or_readiness['projected_opening_date']!r} vs "
        f"{program_or_readiness['projected_opening_date_committed']!r}"
    )


# ─── Budget line arithmetic ───────────────────────────────────────────────────


def assert_budget_split(
    line: Dict[str, Any],
    authorized_cents: int,
    committed_cents: int,
    spent_cents: int,
) -> None:
    """available = authorized - committed - spent must hold at every moment."""
    assert_cents(line["authorized_cents"], authorized_cents)
    assert_cents(line["committed_cents"], committed_cents)
    assert_cents(line["spent_cents"], spent_cents)
    expected_available = authorized_cents - committed_cents - spent_cents
    assert_cents(line["available_cents"], expected_available)


# ─── Pagination ───────────────────────────────────────────────────────────────


def assert_page(
    meta: Dict[str, Any],
    total_count: int,
    has_more: bool,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset


def assert_ids_equal(records: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    assert [r["id"] for r in records] == list(expected_ids), (
        f"expected ids {list(expected_ids)}, got {[r['id'] for r in records]}"
    )


def assert_contains_ids(records: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    actual = {r["id"] for r in records}
    for expected in expected_ids:
        assert expected in actual, f"id {expected} missing from listing"
