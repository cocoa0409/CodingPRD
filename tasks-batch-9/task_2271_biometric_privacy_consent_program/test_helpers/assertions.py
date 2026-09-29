"""Domain assertions for the biometric privacy consent API."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

# ----------------------------------------------------------------------
# Timestamps
# ----------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an API timestamp into an aware UTC datetime."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "timestamp") -> None:
    """Compare two instants for equality, tolerating formatting differences
    (trailing ``Z`` versus ``+00:00``, presence or absence of milliseconds)."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_is_null(value: Any, label: str) -> None:
    assert value is None, f"{label}: expected null, got {value!r}"


def days_after(instant: str, days: int) -> str:
    """The instant ``days`` calendar days after ``instant``, in API form."""
    return iso(parse_instant(instant) + timedelta(days=days))


def hours_after(instant: str, hours: int) -> str:
    return iso(parse_instant(instant) + timedelta(hours=hours))


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ----------------------------------------------------------------------
# Money and percentages
# ----------------------------------------------------------------------


def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Monetary amounts are integer cents; a float or a string is a defect."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: monetary amounts must be integer cents, got {type(actual).__name__} {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_two_decimal_value(actual: Any, expected: float, label: str = "value") -> None:
    """Compare a 2-decimal number exactly, without float drift."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label}: expected a number, got {type(actual).__name__} {actual!r}"
    )
    actual_dec = Decimal(str(actual)).quantize(Decimal("0.01"))
    expected_dec = Decimal(str(expected)).quantize(Decimal("0.01"))
    assert actual_dec == expected_dec, f"{label}: expected {expected_dec}, got {actual}"
    assert -Decimal(str(actual)).as_tuple().exponent <= 2, (
        f"{label}: expected at most 2 decimal places, got {actual!r}"
    )


# ----------------------------------------------------------------------
# Entity-shaped assertions
# ----------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity carries id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"missing common field {field}"
    assert isinstance(entity["version"], int), "version must be an integer"
    parse_instant(entity["created_at"])
    parse_instant(entity["updated_at"])
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_program_state(
    program: Dict[str, Any],
    posture: Optional[str] = None,
    consent_gap_count: Optional[int] = None,
    gated_asset_count: Optional[int] = None,
    open_deletion_obligation_count: Optional[int] = None,
    pra_exposure_cents: Optional[int] = None,
    inventory_completeness_pct: Optional[float] = None,
) -> None:
    if posture is not None:
        assert program["posture"] == posture, (
            f"expected posture {posture}, got {program['posture']}"
        )
    if consent_gap_count is not None:
        assert program["consent_gap_count"] == consent_gap_count, (
            f"expected consent_gap_count {consent_gap_count}, got {program['consent_gap_count']}"
        )
    if gated_asset_count is not None:
        assert program["gated_asset_count"] == gated_asset_count, (
            f"expected gated_asset_count {gated_asset_count}, got {program['gated_asset_count']}"
        )
    if open_deletion_obligation_count is not None:
        assert program["open_deletion_obligation_count"] == open_deletion_obligation_count, (
            "expected open_deletion_obligation_count "
            f"{open_deletion_obligation_count}, got {program['open_deletion_obligation_count']}"
        )
    if pra_exposure_cents is not None:
        assert_cents(program["pra_exposure_cents"], pra_exposure_cents, "pra_exposure_cents")
    if inventory_completeness_pct is not None:
        assert_two_decimal_value(
            program["inventory_completeness_pct"],
            inventory_completeness_pct,
            "inventory_completeness_pct",
        )


def assert_asset_state(
    asset: Dict[str, Any],
    status: Optional[str] = None,
    pinned_policy_id: Optional[str] = None,
    collection_started_at: Optional[str] = None,
    destruction_due_at: Optional[str] = None,
    enrolled_subject_count: Optional[int] = None,
    consent_gap_count: Optional[int] = None,
) -> None:
    if status is not None:
        assert asset["status"] == status, f"expected asset status {status}, got {asset['status']}"
    if pinned_policy_id is not None:
        assert asset["pinned_policy_id"] == pinned_policy_id, (
            f"expected pinned_policy_id {pinned_policy_id}, got {asset['pinned_policy_id']}"
        )
    if collection_started_at is not None:
        assert_instant_equals(asset["collection_started_at"], collection_started_at, "collection_started_at")
    if destruction_due_at is not None:
        assert_instant_equals(asset["destruction_due_at"], destruction_due_at, "destruction_due_at")
    if enrolled_subject_count is not None:
        assert asset["enrolled_subject_count"] == enrolled_subject_count, (
            f"expected enrolled_subject_count {enrolled_subject_count}, "
            f"got {asset['enrolled_subject_count']}"
        )
    if consent_gap_count is not None:
        assert asset["consent_gap_count"] == consent_gap_count, (
            f"expected asset consent_gap_count {consent_gap_count}, got {asset['consent_gap_count']}"
        )


def assert_pagination(meta: Dict[str, Any], total_count: int, has_more: bool, limit: int, offset: int) -> None:
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, f"expected has_more {has_more}, got {meta['has_more']}"
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_unchanged_version(before: Dict[str, Any], after: Dict[str, Any], label: str = "row") -> None:
    """A rejected write must not bump the row's version."""
    assert after["version"] == before["version"], (
        f"{label}: version moved from {before['version']} to {after['version']} on a rejected write"
    )
