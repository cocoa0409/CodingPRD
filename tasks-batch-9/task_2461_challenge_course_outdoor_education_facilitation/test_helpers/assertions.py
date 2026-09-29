"""Domain assertion helpers.

These wrap the repetitive multi-field checks that several tests share. Each one
states the expectation in the vocabulary of the PRD so a failure message names
the rule that broke rather than a bare field comparison.
"""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import APPEND_ONLY_SYSTEM_FIELDS


def assert_posture(course, posture, reason):
    """The course-level safety verdict and the clause that produced it."""
    assert course["posture"] == posture, (
        f"Expected posture {posture}, got {course['posture']} "
        f"(reason {course.get('posture_reason')})"
    )
    assert course["posture_reason"] == reason, (
        f"Expected posture_reason {reason}, got {course['posture_reason']}"
    )


def assert_course_counters(
    course,
    restricted=None,
    out_of_service=None,
    quarantined=None,
    blocked_blocks=None,
    at_risk_bookings=None,
):
    """Assert only the course counters a caller names."""
    if restricted is not None:
        assert course["restricted_element_count"] == restricted
    if out_of_service is not None:
        assert course["out_of_service_element_count"] == out_of_service
    if quarantined is not None:
        assert course["quarantined_equipment_count"] == quarantined
    if blocked_blocks is not None:
        assert course["blocked_block_count"] == blocked_blocks
    if at_risk_bookings is not None:
        assert course["at_risk_booking_count"] == at_risk_bookings


def assert_money(actual_cents, expected_cents, label="amount"):
    """Money is carried in whole cents, so the comparison is exact."""
    assert actual_cents == expected_cents, (
        f"Expected {label} of {expected_cents} cents, got {actual_cents}"
    )


def assert_kg(actual, expected, label="weight_kg"):
    assert actual == pytest.approx(expected, abs=0.01), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_one_decimal(actual, expected, label="value"):
    """Weather readings are carried to one decimal place."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_instant(actual, expected, label="instant"):
    """Compare two UTC instants to the second, ignoring fractional-digit spelling."""
    assert actual is not None, f"Expected {label} {expected}, got null"

    def _normalise(value):
        text = value.replace("+00:00", "Z")
        if "." in text:
            head, _, tail = text.partition(".")
            suffix = "Z" if tail.endswith("Z") else ""
            return head + suffix
        return text

    assert _normalise(actual) == _normalise(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_element_forecast(element, calendar, usage, forecast, basis):
    """The two retirement variants and the one that won."""
    assert element["calendar_life_forecast_date"] == calendar
    assert element["usage_life_forecast_date"] == usage
    assert element["retirement_forecast_date"] == forecast
    assert element["retirement_basis"] == basis


def assert_belay_requirement(element, required_sets, ready):
    assert element["required_belay_set_count"] == required_sets
    assert element["belay_ready"] is ready


def assert_settlement(booking, variant, fee, refund, retained, notice_days=None):
    """Cancellation settlement, which must always exhaust the deposit."""
    assert booking["cancellation_variant"] == variant
    assert_money(booking["cancellation_fee_cents"], fee, "cancellation_fee_cents")
    assert_money(booking["refund_cents"], refund, "refund_cents")
    assert_money(booking["retained_cents"], retained, "retained_cents")
    if notice_days is not None:
        assert booking["notice_days_at_cancel"] == notice_days


def assert_ledger(client, credit=None, payments=None):
    if credit is not None:
        assert_money(client["credit_balance_cents"], credit, "credit_balance_cents")
    if payments is not None:
        assert_money(
            client["payments_received_cents"], payments, "payments_received_cents"
        )


def assert_append_only_record(record):
    """Append-only records carry id and created_at and nothing else systemic."""
    for field in APPEND_ONLY_SYSTEM_FIELDS:
        assert field in record, f"Append-only record missing {field}"
    assert "version" not in record, "Append-only record must not carry version"
    assert "updated_at" not in record, "Append-only record must not carry updated_at"
    assert is_valid_uuid(record["id"]), f"id must be a UUID, got {record['id']}"


def assert_versioned_record(record, version=None):
    assert is_valid_uuid(record["id"]), f"id must be a UUID, got {record['id']}"
    assert is_iso8601_timestamp(record["created_at"])
    assert "updated_at" in record
    assert "version" in record
    if version is not None:
        assert record["version"] == version


def assert_error_envelope_meta(body):
    """Error envelopes carry only the two request fields inside meta."""
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
