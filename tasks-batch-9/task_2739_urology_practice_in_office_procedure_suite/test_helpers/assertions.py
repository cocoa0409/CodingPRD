"""
Domain assertions for the Urology Practice & In-Office Procedure Suite API.

These helpers keep the tests readable: they compare whole field sets in one
call, check the four common fields every entity carries, and check the
conserved-quantity invariants the contract states for consignment lots and
therapy visit ledgers.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import GATE_ORDER


# ─── Generic field assertions ──────────────────────────────────────────────
def assert_fields(data: Dict[str, Any], **expected: Any) -> None:
    """Assert every named field of ``data`` equals its expected value."""
    for name, value in expected.items():
        assert name in data, f"missing field {name!r} in {sorted(data.keys())}"
        assert data[name] == value, (
            f"field {name!r}: expected {value!r}, got {data[name]!r}"
        )


def assert_null_fields(data: Dict[str, Any], *names: str) -> None:
    """Assert every named field is present and null."""
    for name in names:
        assert name in data, f"missing field {name!r} in {sorted(data.keys())}"
        assert data[name] is None, f"field {name!r}: expected null, got {data[name]!r}"


def assert_not_null_fields(data: Dict[str, Any], *names: str) -> None:
    """Assert every named field is present and not null."""
    for name in names:
        assert name in data, f"missing field {name!r} in {sorted(data.keys())}"
        assert data[name] is not None, f"field {name!r}: expected a value, got null"


def assert_has_fields(data: Dict[str, Any], *names: str) -> None:
    """Assert every named field is present, whatever its value."""
    missing = [name for name in names if name not in data]
    assert not missing, f"missing fields {missing} in {sorted(data.keys())}"


def assert_no_fields(data: Dict[str, Any], *names: str) -> None:
    """Assert none of the named fields appear at all."""
    present = [name for name in names if name in data]
    assert not present, f"unexpected fields {present} in payload"


# ─── Common fields ─────────────────────────────────────────────────────────
def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    Assert the four fields every entity of this contract carries: a server
    minted identifier, creation and update timestamps, and an integer version.
    """
    assert_has_fields(data, "id", "created_at", "updated_at", "version")
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not ISO 8601: {data['created_at']!r}"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at is not ISO 8601: {data['updated_at']!r}"
    )
    assert isinstance(data["version"], int) and not isinstance(data["version"], bool), (
        f"version is not an integer: {data['version']!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"version: expected {expected_version}, got {data['version']}"
        )


def assert_freshly_created(data: Dict[str, Any]) -> None:
    """A row just created carries version 1 and identical timestamps."""
    assert_common_fields(data, expected_version=1)
    assert data["created_at"] == data["updated_at"], (
        "a freshly created row must have created_at equal to updated_at, "
        f"got {data['created_at']!r} and {data['updated_at']!r}"
    )


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    """Assert a row's version rose by the given amount across a mutation."""
    assert after["version"] == before["version"] + by, (
        f"version: expected {before['version'] + by}, got {after['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Assert a row was left untouched: same version, same update stamp."""
    assert after["version"] == before["version"], (
        f"version changed from {before['version']} to {after['version']}"
    )
    assert after["updated_at"] == before["updated_at"], (
        f"updated_at changed from {before['updated_at']!r} to {after['updated_at']!r}"
    )


# ─── Timestamps and dates ──────────────────────────────────────────────────
def assert_iso_timestamp(value: Any, field: str = "timestamp") -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{field} is not an ISO 8601 timestamp: {value!r}"
    )


def assert_iso_date(value: Any, field: str = "date") -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} is not an ISO 8601 calendar date: {value!r}"
    )


# ─── Case occupancy window ─────────────────────────────────────────────────
def assert_occupancy_window(
    case: Dict[str, Any],
    procedure_minutes: int,
    turnover_minutes: int,
    scheduled_start_at: str,
    scheduled_end_at: str,
    block_end_at: str,
) -> None:
    """Assert the whole derived occupancy window of a case at once."""
    assert_fields(
        case,
        procedure_minutes=procedure_minutes,
        turnover_minutes=turnover_minutes,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        block_end_at=block_end_at,
    )


def assert_case_dimensions(
    case: Dict[str, Any], schedule_status: str, clearance_status: str
) -> None:
    """Assert both of a case's independent state dimensions."""
    assert_fields(
        case, schedule_status=schedule_status, clearance_status=clearance_status
    )


def assert_specimen_dimensions(
    specimen: Dict[str, Any], chain_status: str, notification_status: str
) -> None:
    """Assert both of a specimen's independent state dimensions."""
    assert_fields(
        specimen, chain_status=chain_status, notification_status=notification_status
    )


# ─── Readiness gates ───────────────────────────────────────────────────────
def assert_blocking_reason_codes(data: Dict[str, Any], expected: Sequence[str]) -> None:
    """
    Assert the unmet check-in gates, as an ordered list. The contract fixes the
    gate order, so order is part of the expectation.
    """
    actual = data["blocking_reason_codes"]
    assert actual == list(expected), (
        f"blocking_reason_codes: expected {list(expected)}, got {actual}"
    )


def assert_gate_order_respected(codes: Sequence[str]) -> None:
    """Assert a reported gate list is a subsequence of the fixed gate order."""
    positions = [GATE_ORDER.index(code) for code in codes]
    assert positions == sorted(positions), (
        f"gate codes {list(codes)} are not in the fixed gate order {GATE_ORDER}"
    )


def assert_readiness(
    readiness: Dict[str, Any],
    blocking_reason_codes: Sequence[str],
    check_in_allowed: bool,
) -> None:
    assert_blocking_reason_codes(readiness, blocking_reason_codes)
    assert_gate_order_respected(readiness["blocking_reason_codes"])
    expected_first = list(blocking_reason_codes)[0] if blocking_reason_codes else None
    assert readiness.get("first_blocking_reason_code") == expected_first, (
        "first_blocking_reason_code: expected "
        f"{expected_first!r}, got {readiness.get('first_blocking_reason_code')!r}"
    )
    assert readiness["check_in_allowed"] is check_in_allowed, (
        f"check_in_allowed: expected {check_in_allowed}, got {readiness['check_in_allowed']}"
    )


# ─── Conserved quantities ──────────────────────────────────────────────────
def assert_lot_ledger_conserved(lot: Dict[str, Any]) -> None:
    """
    Assert a consignment lot's unit ledger balances: everything received is
    still available, reserved, consumed, returned or wasted.
    """
    parts = (
        lot["quantity_available"]
        + lot["quantity_reserved"]
        + lot["quantity_consumed"]
        + lot["quantity_returned"]
        + lot["quantity_wasted"]
    )
    assert parts == lot["quantity_received"], (
        f"lot ledger does not balance: received {lot['quantity_received']} but "
        f"available {lot['quantity_available']} + reserved {lot['quantity_reserved']} "
        f"+ consumed {lot['quantity_consumed']} + returned {lot['quantity_returned']} "
        f"+ wasted {lot['quantity_wasted']} = {parts}"
    )


def assert_lot_counters(
    lot: Dict[str, Any],
    available: int,
    reserved: int,
    consumed: int,
    returned: int,
    wasted: int,
) -> None:
    """Assert every unit counter of a lot, then that the ledger balances."""
    assert_fields(
        lot,
        quantity_available=available,
        quantity_reserved=reserved,
        quantity_consumed=consumed,
        quantity_returned=returned,
        quantity_wasted=wasted,
    )
    assert_lot_ledger_conserved(lot)


def assert_visit_ledger_conserved(referral: Dict[str, Any]) -> None:
    """
    Assert a referral's therapy visit ledger balances: every authorised visit
    is either used, still remaining, or forfeited.
    """
    parts = (
        referral["visits_used"]
        + referral["visits_remaining"]
        + referral["visits_forfeited"]
    )
    assert parts == referral["visits_authorized"], (
        f"visit ledger does not balance: authorized {referral['visits_authorized']} but "
        f"used {referral['visits_used']} + remaining {referral['visits_remaining']} "
        f"+ forfeited {referral['visits_forfeited']} = {parts}"
    )


def assert_visit_counters(
    referral: Dict[str, Any],
    authorized: int,
    used: int,
    remaining: int,
    forfeited: int,
) -> None:
    assert_fields(
        referral,
        visits_authorized=authorized,
        visits_used=used,
        visits_remaining=remaining,
        visits_forfeited=forfeited,
    )
    assert_visit_ledger_conserved(referral)


# ─── Collections ───────────────────────────────────────────────────────────
def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert_fields(
        meta, limit=limit, offset=offset, total_count=total_count, has_more=has_more
    )


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Assert a page holds exactly these rows, in exactly this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"page contents: expected {list(expected_ids)}, got {actual}"
    )


def assert_ids_present(rows: List[Dict[str, Any]], *expected_ids: str) -> None:
    actual = {row["id"] for row in rows}
    missing = [row_id for row_id in expected_ids if row_id not in actual]
    assert not missing, f"rows {missing} are absent from the result set"


def assert_ids_absent(rows: List[Dict[str, Any]], *unexpected_ids: str) -> None:
    actual = {row["id"] for row in rows}
    present = [row_id for row_id in unexpected_ids if row_id in actual]
    assert not present, f"rows {present} should not be in the result set"


def assert_ascending_created_at(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"collection read is not in ascending created_at order: {stamps}"
    )
