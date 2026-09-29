"""Domain assertions layered on the shared response validators."""

import re

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

LICENSE_NUMBER_RE = re.compile(r"^PE-\d{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def assert_license_number_format(license_number):
    """Licence numbers are PE- followed by exactly six digits."""
    assert isinstance(license_number, str), f"expected a string, got {license_number!r}"
    assert LICENSE_NUMBER_RE.match(license_number), (
        f"expected a PE-<6 digits> licence number, got {license_number!r}"
    )


def assert_money_cents(value, expected=None):
    """Money crosses the wire as an integer count of cents, never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"expected an integer count of cents, got {value!r} ({type(value).__name__})"
    )
    if expected is not None:
        assert value == expected, f"expected {expected} cents, got {value}"


def assert_pdh_value(value, expected):
    """PDH totals carry at most one decimal place and must not drift."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"expected a numeric PDH value, got {value!r} ({type(value).__name__})"
    )
    assert round(float(value), 6) == round(float(value), 1), (
        f"expected at most one decimal place of PDH, got {value!r}"
    )
    assert round(float(value), 1) == round(float(expected), 1), (
        f"expected {expected} PDH, got {value}"
    )


def assert_uuid(value):
    assert is_valid_uuid(str(value)), f"expected a UUID, got {value!r}"


def assert_iso_timestamp(value):
    assert value is not None, "expected a timestamp, got None"
    assert is_iso8601_timestamp(str(value)), (
        f"expected an ISO-8601 timestamp, got {value!r}"
    )


def assert_iso_date(value):
    assert isinstance(value, str) and DATE_RE.match(value), (
        f"expected a YYYY-MM-DD date, got {value!r}"
    )


def assert_year_month(value):
    assert isinstance(value, str) and MONTH_RE.match(value), (
        f"expected a YYYY-MM month, got {value!r}"
    )


def assert_no_version_field(entity):
    """Append-only rows expose neither updated_at nor version."""
    assert "version" not in entity, (
        f"an append-only row must not expose version, got {entity.get('version')!r}"
    )
    assert "updated_at" not in entity, (
        f"an append-only row must not expose updated_at, got {entity.get('updated_at')!r}"
    )


def assert_has_common_fields(entity):
    """Mutable rows expose id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"expected field {field!r} on {sorted(entity)}"
    assert isinstance(entity["version"], int), (
        f"expected an integer version, got {entity['version']!r}"
    )


def assert_fields(entity, **expected):
    """Assert several stored fields at once with a readable failure message."""
    actual = {key: entity.get(key) for key in expected}
    assert actual == expected, f"expected {expected}, got {actual}"


def assert_seat_ledger(center, seat_count=None, committed=None, available=None):
    """Seat totals must always satisfy seat_count == committed + available."""
    assert center["seats_committed"] + center["seats_available"] == center["seat_count"], (
        "seat ledger broken: "
        f"{center['seats_committed']} committed + {center['seats_available']} available "
        f"!= {center['seat_count']} seats"
    )
    if seat_count is not None:
        assert center["seat_count"] == seat_count, (
            f"expected seat_count {seat_count}, got {center['seat_count']}"
        )
    if committed is not None:
        assert center["seats_committed"] == committed, (
            f"expected seats_committed {committed}, got {center['seats_committed']}"
        )
    if available is not None:
        assert center["seats_available"] == available, (
            f"expected seats_available {available}, got {center['seats_available']}"
        )


def assert_version_is(entity, expected):
    assert entity["version"] == expected, (
        f"expected version {expected}, got {entity['version']}"
    )
