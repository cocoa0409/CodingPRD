"""Domain assertions for the pulmonary function laboratory API.

These helpers name the laboratory's own rules — envelope shape, rounding
places, the rescue-dose ledger, the append-only evidence rows — so that a test
body reads as a clinical statement instead of a pile of dictionary lookups.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import pytest

from .constants import (
    RESCUE_ADMIN_DOSES,
    RESCUE_RESERVE_DOSES,
    TEMPLATE_VERSION,
)

_REQUEST_ID_PATTERN = re.compile(r"^req_.+")
_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|[+-]\d{2}:\d{2})$"
)


# ------------------------------------------------------------------- envelope
def assert_envelope_meta(body: Mapping[str, Any]) -> None:
    """Every answer carries a request id and a millisecond-precision stamp."""
    meta = body.get("meta")
    assert isinstance(meta, dict), f"expected a meta block, got {body.get('meta')!r}"
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and _REQUEST_ID_PATTERN.match(request_id), (
        f"api_request_id must be a req_-prefixed string, got {request_id!r}"
    )
    stamp = meta.get("api_request_timestamp")
    assert isinstance(stamp, str) and _TIMESTAMP_PATTERN.match(stamp), (
        f"api_request_timestamp must be an ISO8601 instant with three "
        f"fractional digits, got {stamp!r}"
    )


def assert_response_type(body: Mapping[str, Any], expected: str) -> None:
    assert body.get("response_type") == expected, (
        f"expected response_type {expected!r}, got {body.get('response_type')!r}"
    )


# ------------------------------------------------------------------- instants
def parse_instant(value: Any) -> datetime:
    """Read one of the API's UTC instants, whatever its fractional precision."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(value: Any, expected_iso: str) -> None:
    """The field names the expected UTC instant."""
    assert parse_instant(value) == parse_instant(expected_iso), (
        f"expected the instant {expected_iso}, got {value!r}"
    )


def assert_minutes_between(earlier: Any, later: Any, minutes: int) -> None:
    delta = parse_instant(later) - parse_instant(earlier)
    actual = int(delta.total_seconds() // 60)
    assert actual == minutes, f"expected {minutes} minutes apart, got {actual}"


# ------------------------------------------------------------------- precision
def assert_rounded_to(value: Any, places: int, expected: float) -> None:
    """A numeric field must match the expected value at its declared place."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"expected a number, got {value!r}"
    )
    tolerance = 0.5 * (10 ** -places)
    assert value == pytest.approx(expected, abs=tolerance), (
        f"expected {expected} at {places} decimal places, got {value}"
    )
    quantised = round(float(value), places)
    assert float(value) == pytest.approx(quantised, abs=1e-9), (
        f"{value} carries more than {places} decimal places"
    )


def assert_1dp(value: Any, expected: float) -> None:
    assert_rounded_to(value, 1, expected)


def assert_2dp(value: Any, expected: float) -> None:
    assert_rounded_to(value, 2, expected)


def assert_3dp(value: Any, expected: float) -> None:
    assert_rounded_to(value, 3, expected)


def assert_4dp(value: Any, expected: float) -> None:
    assert_rounded_to(value, 4, expected)


# ------------------------------------------------------------ common properties
MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
EVIDENCE_COMMON_FIELDS = ("id", "created_at")


def assert_mutable_record(record: Mapping[str, Any]) -> None:
    """A revisable row carries an id, both stamps and a version counter."""
    for field in MUTABLE_COMMON_FIELDS:
        assert field in record, f"expected the row to carry {field!r}"
    assert isinstance(record["version"], int) and record["version"] >= 1


def assert_evidence_record(record: Mapping[str, Any]) -> None:
    """An append-only evidence row carries only an id and a creation stamp."""
    for field in EVIDENCE_COMMON_FIELDS:
        assert field in record, f"expected the row to carry {field!r}"
    assert "version" not in record, "an append-only row must not carry a version"
    assert "updated_at" not in record, "an append-only row is never updated"


def assert_version_is(record: Mapping[str, Any], expected: int) -> None:
    assert record["version"] == expected, (
        f"expected version {expected}, got {record['version']}"
    )


def assert_version_advanced_by(
    before: Mapping[str, Any], after: Mapping[str, Any], steps: int
) -> None:
    assert after["version"] == before["version"] + steps, (
        f"expected the version to advance by {steps} from {before['version']}, "
        f"got {after['version']}"
    )


def assert_unchanged(
    before: Mapping[str, Any], after: Mapping[str, Any], fields: Sequence[str]
) -> None:
    for field in fields:
        assert after.get(field) == before.get(field), (
            f"{field!r} should not have moved: {before.get(field)!r} -> "
            f"{after.get(field)!r}"
        )


# --------------------------------------------------------------- device quality
def assert_device_quarantined(
    device: Mapping[str, Any],
    reason: str,
    trigger_staff_id: Optional[str] = None,
    quarantined_at: Optional[str] = None,
) -> None:
    assert device["status"] == "QUARANTINED", (
        f"expected the device to be QUARANTINED, got {device['status']!r}"
    )
    assert device["quarantine_reason"] == reason
    if trigger_staff_id is not None:
        assert device["quarantine_trigger_staff_id"] == trigger_staff_id
    if quarantined_at is not None:
        assert_instant(device["quarantined_at"], quarantined_at)


def assert_device_cleared(device: Mapping[str, Any]) -> None:
    """Returning a device to service wipes the whole quarantine record."""
    assert device["status"] == "AVAILABLE", (
        f"expected the device to be AVAILABLE, got {device['status']!r}"
    )
    assert device["quarantined_at"] is None
    assert device["quarantine_reason"] is None
    assert device["quarantine_trigger_staff_id"] is None


# ------------------------------------------------------------ maneuver quality
def assert_maneuver_acceptable(maneuver: Mapping[str, Any]) -> None:
    assert maneuver["acceptability"] == "ACCEPTABLE", (
        f"expected an ACCEPTABLE effort, got {maneuver['acceptability']!r}"
    )
    assert maneuver["rejection_reasons"] == [], (
        f"an acceptable effort carries no rejection reasons, got "
        f"{maneuver['rejection_reasons']!r}"
    )


def assert_maneuver_unacceptable(
    maneuver: Mapping[str, Any], reasons: Sequence[str]
) -> None:
    assert maneuver["acceptability"] == "UNACCEPTABLE", (
        f"expected an UNACCEPTABLE effort, got {maneuver['acceptability']!r}"
    )
    assert maneuver["rejection_reasons"] == list(reasons), (
        f"expected rejection reasons {list(reasons)!r}, got "
        f"{maneuver['rejection_reasons']!r}"
    )


# ------------------------------------------------------------ rescue-dose ledger
def assert_dose_ledger_balanced(
    lot: Mapping[str, Any], administered_totals: Iterable[int]
) -> None:
    """Invariant I1: remaining doses plus every dose spent equals the receipt."""
    spent = sum(administered_totals)
    assert lot["doses_remaining"] + spent == lot["doses_at_receipt"], (
        f"{lot['doses_remaining']} remaining + {spent} administered != "
        f"{lot['doses_at_receipt']} at receipt"
    )


def assert_reservation_matches_live_runs(lot: Mapping[str, Any], live_runs: int) -> None:
    """Invariant I2: the reservation is four doses per live challenge run."""
    assert lot["doses_reserved"] == RESCUE_RESERVE_DOSES * live_runs, (
        f"expected {RESCUE_RESERVE_DOSES * live_runs} doses reserved for "
        f"{live_runs} live run(s), got {lot['doses_reserved']}"
    )


def assert_rescue_administered_in_full(run: Mapping[str, Any]) -> None:
    assert run["rescue_doses_administered"] == RESCUE_ADMIN_DOSES, (
        f"a rescued abort spends {RESCUE_ADMIN_DOSES} doses, got "
        f"{run['rescue_doses_administered']}"
    )


# ------------------------------------------------------------------- reporting
def assert_signed_interpretation(
    report: Mapping[str, Any],
    pattern: str,
    severity: str,
    signed_at: Optional[str] = None,
) -> None:
    assert report["status"] == "SIGNED", (
        f"expected a SIGNED report, got {report['status']!r}"
    )
    assert report["pattern"] == pattern
    assert report["severity"] == severity
    assert report["template_version"] == TEMPLATE_VERSION
    if signed_at is not None:
        assert_instant(report["signed_at"], signed_at)


def assert_unsigned_report(report: Mapping[str, Any]) -> None:
    """A report that has not been signed carries no interpretation yet."""
    assert report["signed_at"] is None
    assert report["pattern"] is None
    assert report["severity"] is None


def assert_open_report_totals(
    staff_rows: Sequence[Mapping[str, Any]], expected_total: int
) -> None:
    total = sum(row["open_report_count"] for row in staff_rows)
    assert total == expected_total, (
        f"expected {expected_total} open report(s) across the roster, got {total}"
    )


# ------------------------------------------------------------------- listings
def assert_listing_ids(rows: Sequence[Mapping[str, Any]], expected_ids: Sequence[str]) -> None:
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"expected the listing to hold {list(expected_ids)!r}, got "
        f"{[row['id'] for row in rows]!r}"
    )


def assert_page(
    meta: Mapping[str, Any],
    total_count: int,
    has_more: bool,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']!r}"
    )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset


def assert_fields_equal(
    record: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    """Compare a batch of plain fields, reporting each mismatch by name."""
    mismatches: Dict[str, Any] = {
        field: (value, record.get(field))
        for field, value in expected.items()
        if record.get(field) != value
    }
    assert not mismatches, f"field mismatches (expected, actual): {mismatches!r}"
