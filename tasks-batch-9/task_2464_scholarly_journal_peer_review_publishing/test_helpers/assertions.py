"""Domain assertion helpers layered over the generic framework validators."""

import re

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# Record identity (PRD §2.4)
# --------------------------------------------------------------------------


def assert_mutable_record_fields(entity, expected_version=None):
    """Assert a mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert_timestamp_format(entity["created_at"])
    assert_timestamp_format(entity["updated_at"])
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_record_fields(record):
    """Assert an append-only evidence record carries only id and created_at."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']!r}"
    assert_timestamp_format(record["created_at"])
    assert "updated_at" not in record, (
        "append-only evidence records have no updated_at field"
    )
    assert "version" not in record, (
        "append-only evidence records have no version field"
    )


def assert_date_only(value):
    """Assert a value is a whole calendar date in the form YYYY-MM-DD."""
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"Expected a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_timestamp_with_millis(value):
    """Assert an ISO 8601 UTC timestamp with three fractional digits."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC timestamp: {value!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value), (
        f"Expected three fractional digits, got {value!r}"
    )


# --------------------------------------------------------------------------
# Numeric precision (PRD §2.7)
# --------------------------------------------------------------------------


def assert_integer_cents(value, label="amount"):
    """Assert a monetary field is a whole number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_decimal_places(value, places, label="value"):
    """Assert a decimal field carries at most `places` decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    quantised = round(float(value), places)
    assert abs(quantised - float(value)) < 1e-12, (
        f"{label} carries more than {places} decimal places: {value!r}"
    )


def assert_score_equals(actual, expected, label="score"):
    """Assert a 2-decimal score equals its expected value exactly."""
    assert_decimal_places(actual, 2, label)
    assert abs(float(actual) - float(expected)) < 1e-9, (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_weight_equals(actual, expected, label="reliability_weight"):
    """Assert a 4-decimal weight equals its expected value exactly."""
    assert_decimal_places(actual, 4, label)
    assert abs(float(actual) - float(expected)) < 1e-9, (
        f"Expected {label} {expected}, got {actual}"
    )


# --------------------------------------------------------------------------
# Entity-shaped assertions
# --------------------------------------------------------------------------


def assert_fields(entity, **expected):
    """Assert each named field on `entity` equals its expected value."""
    for field, value in expected.items():
        assert field in entity, f"Missing field {field!r} on {entity!r}"
        assert entity[field] == value, (
            f"Expected {field} == {value!r}, got {entity[field]!r}"
        )


def assert_invoice_amounts(invoice, **expected):
    """Assert an invoice's fee components, each a whole number of cents."""
    for field, value in expected.items():
        assert field in invoice, f"Missing field {field!r} on the invoice"
        if field.endswith("_cents"):
            assert_integer_cents(invoice[field], field)
        assert invoice[field] == value, (
            f"Expected {field} == {value!r}, got {invoice[field]!r}"
        )


def assert_production_stages(job, content_stage, clearance_stage):
    """Assert a production job's two independent state dimensions."""
    assert job["content_stage"] == content_stage, (
        f"Expected content_stage {content_stage}, got {job['content_stage']}"
    )
    assert job["clearance_stage"] == clearance_stage, (
        f"Expected clearance_stage {clearance_stage}, got {job['clearance_stage']}"
    )


def assert_journal_ledgers(journal, apc_receivable_cents=None, apc_waived_cents=None):
    """Assert a journal's conserved fee ledgers."""
    if apc_receivable_cents is not None:
        assert_integer_cents(journal["apc_receivable_cents"], "apc_receivable_cents")
        assert journal["apc_receivable_cents"] == apc_receivable_cents, (
            f"Expected apc_receivable_cents {apc_receivable_cents}, "
            f"got {journal['apc_receivable_cents']}"
        )
    if apc_waived_cents is not None:
        assert_integer_cents(journal["apc_waived_cents"], "apc_waived_cents")
        assert journal["apc_waived_cents"] == apc_waived_cents, (
            f"Expected apc_waived_cents {apc_waived_cents}, "
            f"got {journal['apc_waived_cents']}"
        )
