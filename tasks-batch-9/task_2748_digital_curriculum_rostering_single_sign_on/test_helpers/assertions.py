"""
Domain assertions for the Digital Curriculum Rostering & Single Sign-On API.

These build on the framework's structural helpers and add the checks this
contract needs repeatedly: the common record properties, the ISO-8601 shape with
exactly three fractional digits, integer-cent money, the two independent
AppAccount axes, seat counters, pagination meta and created_at ordering.
"""

import math
import re
from datetime import date, timedelta

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_MILLIS_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ── timestamps and identifiers ───────────────────────────────────────────────

def assert_uuid(value, label="id"):
    """Assert the value is a UUID string."""
    assert is_valid_uuid(value), f"{label} is not a UUID: {value!r}"


def assert_millis_timestamp(value, label="timestamp"):
    """
    Assert an ISO-8601 UTC instant carrying exactly three fractional digits,
    which is the only timestamp rendering this contract permits.
    """
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _MILLIS_TIMESTAMP_RE.match(value), (
        f"{label} must be ISO-8601 UTC with exactly three fractional digits, "
        f"got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{label} is not ISO-8601: {value!r}"


def assert_iso_date(value, label="date"):
    """Assert a bare ISO calendar date (YYYY-MM-DD)."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", value), (
        f"{label} must be an ISO calendar date, got {value!r}"
    )


def assert_common_fields(record, label="record", expected_version=None):
    """
    Assert the four common record properties: a UUID id, ISO-8601 created_at and
    updated_at with millisecond precision, and an integer version starting at 1.
    """
    assert_uuid(record.get("id"), f"{label}.id")
    assert_millis_timestamp(record.get("created_at"), f"{label}.created_at")
    assert_millis_timestamp(record.get("updated_at"), f"{label}.updated_at")
    version = record.get("version")
    assert isinstance(version, int), f"{label}.version must be an integer, got {version!r}"
    assert version >= 1, f"{label}.version must start at 1, got {version}"
    if expected_version is not None:
        assert version == expected_version, (
            f"{label}.version expected {expected_version}, got {version}"
        )


def assert_version(record, expected, label="record"):
    """Assert an exact version value."""
    assert record.get("version") == expected, (
        f"{label}.version expected {expected}, got {record.get('version')}"
    )


# ── money and seats ──────────────────────────────────────────────────────────

def assert_integer_cents(value, label="amount"):
    """Assert a monetary field is an integer number of cents, never a string."""
    assert not isinstance(value, str), (
        f"{label} must be integer cents, not a string: {value!r}"
    )
    assert not isinstance(value, bool), f"{label} must be an integer, got {value!r}"
    assert isinstance(value, int), f"{label} must be integer cents, got {value!r}"


def assert_integer_seats(value, label="seats"):
    """Assert a seat count is a non-negative integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer, got {value!r}"
    )
    assert value >= 0, f"{label} must be non-negative, got {value}"


def assert_two_decimal_places(value, label="score"):
    """Assert a stored score carries at most two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


# ── entity-shaped assertions ─────────────────────────────────────────────────

def assert_school(school, **expected):
    """Assert a School record's shape and any supplied field expectations."""
    assert_common_fields(school, "school")
    assert_integer_seats(school.get("enrolled_student_count"), "school.enrolled_student_count")
    _assert_fields(school, expected, "school")


def assert_term(term, **expected):
    """Assert a Term record's shape and any supplied field expectations."""
    assert_common_fields(term, "term")
    _assert_fields(term, expected, "term")


def assert_vendor_app(vendor_app, **expected):
    """Assert a VendorApp record's shape and any supplied field expectations."""
    assert_common_fields(vendor_app, "vendor_app")
    assert_integer_seats(vendor_app.get("consumed_seats"), "vendor_app.consumed_seats")
    assert_integer_cents(
        vendor_app.get("committed_charge_cents"), "vendor_app.committed_charge_cents"
    )
    _assert_fields(vendor_app, expected, "vendor_app")


def assert_allocation(allocation, **expected):
    """Assert a BuildingAllocation record's shape and field expectations."""
    assert_common_fields(allocation, "building_allocation")
    assert_integer_seats(allocation.get("allocated_seats"), "allocation.allocated_seats")
    assert_integer_seats(allocation.get("consumed_seats"), "allocation.consumed_seats")
    assert_integer_seats(allocation.get("borrowed_seats"), "allocation.borrowed_seats")
    _assert_fields(allocation, expected, "building_allocation")


def assert_app_account(account, **expected):
    """Assert an AppAccount record's shape and field expectations."""
    assert_common_fields(account, "app_account")
    assert_integer_cents(account.get("seat_charge_cents"), "app_account.seat_charge_cents")
    assert_integer_cents(
        account.get("refunded_charge_cents"), "app_account.refunded_charge_cents"
    )
    _assert_fields(account, expected, "app_account")


def assert_account_axes(account, seat_status=None, identity_status=None, password_state=None):
    """
    Assert the AppAccount's two independent lifecycle axes (and its password
    sub-state) hold exactly the expected values.
    """
    if seat_status is not None:
        assert account.get("seat_status") == seat_status, (
            f"seat_status expected {seat_status}, got {account.get('seat_status')}"
        )
    if identity_status is not None:
        assert account.get("identity_status") == identity_status, (
            f"identity_status expected {identity_status}, "
            f"got {account.get('identity_status')}"
        )
    if password_state is not None:
        assert account.get("password_state") == password_state, (
            f"password_state expected {password_state}, "
            f"got {account.get('password_state')}"
        )


def assert_sync_run(run, **expected):
    """Assert a SyncRun record's shape and field expectations."""
    assert_common_fields(run, "sync_run")
    _assert_fields(run, expected, "sync_run")


def assert_error_queue_item(item, **expected):
    """Assert an ErrorQueueItem record's shape and field expectations."""
    assert_common_fields(item, "error_queue_item")
    _assert_fields(item, expected, "error_queue_item")


def assert_seat_counters(vendor_app, consumed_seats=None, unallocated_seats=None,
                         committed_charge_cents=None):
    """Assert the licence-level seat and money counters."""
    if consumed_seats is not None:
        assert vendor_app.get("consumed_seats") == consumed_seats, (
            f"consumed_seats expected {consumed_seats}, "
            f"got {vendor_app.get('consumed_seats')}"
        )
    if unallocated_seats is not None:
        assert vendor_app.get("unallocated_seats") == unallocated_seats, (
            f"unallocated_seats expected {unallocated_seats}, "
            f"got {vendor_app.get('unallocated_seats')}"
        )
    if committed_charge_cents is not None:
        assert_integer_cents(
            vendor_app.get("committed_charge_cents"), "committed_charge_cents"
        )
        assert vendor_app.get("committed_charge_cents") == committed_charge_cents, (
            f"committed_charge_cents expected {committed_charge_cents}, "
            f"got {vendor_app.get('committed_charge_cents')}"
        )


def _assert_fields(record, expected, label):
    for key, value in expected.items():
        assert key in record, f"{label} is missing field {key!r}"
        assert record[key] == value, (
            f"{label}.{key} expected {value!r}, got {record[key]!r}"
        )


# ── list and pagination assertions ───────────────────────────────────────────

def assert_pagination_meta(meta, limit=None, offset=None, total_count=None,
                           has_more=None):
    """Assert the four pagination fields carried by a list response's meta."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination meta is missing {field!r}"
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"meta.offset expected {offset}, got {meta['offset']}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more expected {has_more}, got {meta['has_more']}"
        )


def assert_ordered_by_created_at(items):
    """Assert a list page is ordered by created_at ascending."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"page is not ordered by created_at ascending: {stamps}"


def assert_ids_equal(items, expected_ids, label="page"):
    """Assert a list page holds exactly the expected ids in the expected order."""
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), (
        f"{label} expected ids {list(expected_ids)}, got {actual}"
    )


def assert_contains_id(items, expected_id, label="page"):
    ids = [item["id"] for item in items]
    assert expected_id in ids, f"{label} should contain {expected_id}, got {ids}"


def assert_omits_id(items, unexpected_id, label="page"):
    ids = [item["id"] for item in items]
    assert unexpected_id not in ids, f"{label} should omit {unexpected_id}, got {ids}"


# ── date and rate arithmetic helpers ─────────────────────────────────────────

def inclusive_day_count(start_date: str, end_date: str) -> int:
    """Inclusive count of calendar days from start_date through end_date."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return (end - start).days + 1


def add_calendar_days(iso_date: str, days: int) -> str:
    """Calendar-day addition on a date, as the contract's retention windows do."""
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def expected_seat_rate(price_per_seat_cents: int, priced_on: str, term_start: str,
                       term_end: str, add_drop_cutoff: str) -> int:
    """
    The per-seat rate for a provisioning date: full list price on or before the
    add/drop cutoff, otherwise the ceiling of price * remaining / total days.
    """
    if date.fromisoformat(priced_on) <= date.fromisoformat(add_drop_cutoff):
        return price_per_seat_cents
    total_days = inclusive_day_count(term_start, term_end)
    remaining = max(1, inclusive_day_count(priced_on, term_end))
    return math.ceil(price_per_seat_cents * remaining / total_days)
