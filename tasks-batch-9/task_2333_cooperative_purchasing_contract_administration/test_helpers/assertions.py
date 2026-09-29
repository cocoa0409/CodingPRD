"""Domain-specific assertion helpers."""

from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

SCORE_TOLERANCE = 0.01
FRACTION_TOLERANCE = 0.00005


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional seconds."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant(actual, expected, label="timestamp"):
    """Two instants are equal when they denote the same moment in UTC."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_score(actual, expected, label="score"):
    """Scores, percentages and variance figures carry exactly two decimals."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_fraction(actual, expected, label="fraction"):
    """Discount ladders, escalation caps and scope shares are four-decimal fractions."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=FRACTION_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual, expected, label="cents"):
    """Money is an integer number of cents and is never a decimal."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_system_fields(row, expect_version=None):
    """Mutable rows carry a UUID id, both timestamps and an integer version."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int)
    if expect_version is not None:
        assert row["version"] == expect_version, (
            f"version: expected {expect_version}, got {row['version']}"
        )


def assert_envelope_meta(body):
    """Every response carries a request id prefixed req_ and an ISO 8601 timestamp."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta["api_request_timestamp"]


def assert_error_data_shape(error_data):
    """An error payload carries exactly error_id and message."""
    assert set(error_data.keys()) == {"error_id", "message"}, error_data


def assert_fee_ledger_balanced(contract):
    """fee_outstanding_cents always equals assessed minus remitted."""
    assert contract["fee_outstanding_cents"] == (
        contract["fee_assessed_cents_total"] - contract["fee_remitted_cents_total"]
    ), contract
    assert contract["fee_outstanding_cents"] >= 0, contract


def assert_deduction_detail(actual, expected):
    """Compare the ordered deduction ledger of an authority opinion."""
    assert len(actual) == len(expected), f"expected {expected}, got {actual}"
    for got, want in zip(actual, expected):
        assert got["reason_code"] == want[0], f"expected {expected}, got {actual}"
        assert_score(got["points"], want[1], f"deduction {want[0]}")


def assert_add_on_detail(actual, expected):
    """Compare the ordered add-on charge ledger of an order."""
    assert len(actual) == len(expected), f"expected {expected}, got {actual}"
    for got, want in zip(actual, expected):
        assert got["code"] == want[0], f"expected {expected}, got {actual}"
        assert_cents(got["raw_cents"], want[1], f"{want[0]}.raw_cents")
        assert_cents(got["capped_cents"], want[2], f"{want[0]}.capped_cents")
