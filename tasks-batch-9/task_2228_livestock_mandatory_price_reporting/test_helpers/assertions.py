"""Domain assertion helpers.

Each helper asserts one invariant the PRD states, so a failing test names the
rule it broke rather than a bare field comparison.
"""

from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AggregationState,
    DisclosureState,
    PublicationState,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable instant."""
    assert isinstance(value, str), f"not a timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_clock_stamp(actual, expected_instant, field="timestamp"):
    """A clock-written stamp records the instant the logical clock then held.

    The PRD fixes the instant, not the number of fractional digits it is
    serialized with, so the comparison is made on the instant itself.
    """
    assert is_iso8601_timestamp(actual), f"{field} is not ISO 8601: {actual!r}"
    assert _instant(actual) == _instant(expected_instant), (
        f"expected {field} to record {expected_instant}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common fields (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_versioned_resource(resource, expected_version=None):
    """A versioned resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert is_iso8601_timestamp(resource["updated_at"]), resource["updated_at"]
    assert isinstance(resource["version"], int) and resource["version"] >= 1
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_append_only_line(line):
    """An append-only line carries id and created_at but no updated_at/version."""
    assert is_valid_uuid(line["id"]), f"id is not a UUID: {line['id']}"
    assert is_iso8601_timestamp(line["created_at"]), line["created_at"]
    assert "updated_at" not in line, "an append-only line carries no updated_at"
    assert "version" not in line, "an append-only line carries no version"


# ---------------------------------------------------------------------------
# Error envelope (PRD §2.2)
# ---------------------------------------------------------------------------


def assert_error_envelope_shape(response):
    """The error envelope carries only the two meta keys and error_id/message."""
    body = response.json()
    assert body["response_type"] == "error", body
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only api_request_id and api_request_timestamp: "
        f"{sorted(body['meta'].keys())}"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must contain only error_id and message: "
        f"{sorted(body['data'].keys())}"
    )
    message = body["data"]["message"]
    assert isinstance(message, str) and message.strip(), "message must be non-empty"
    assert message != body["data"]["error_id"], (
        "message must be human-readable prose, not a repeat of the error_id"
    )
    return body


# ---------------------------------------------------------------------------
# Registration (PRD §3.2)
# ---------------------------------------------------------------------------


def assert_registration_number_format(registration_number, determination_year, sequence):
    """registration_number is MPR-<year>-NNNN, zero padded to four digits."""
    expected = f"MPR-{determination_year}-{sequence:04d}"
    assert registration_number == expected, (
        f"expected registration_number {expected}, got {registration_number}"
    )


def assert_determination(registration, measured_head, threshold_head, outcome):
    assert registration["measured_head"] == measured_head, registration
    assert registration["threshold_head"] == threshold_head, registration
    assert registration["determination_outcome"] == outcome, registration


# ---------------------------------------------------------------------------
# Window ledger (PRD §2.11)
# ---------------------------------------------------------------------------


def assert_window_ledger(window, total_head_reported, accepted_submission_count):
    assert window["total_head_reported"] == total_head_reported, (
        f"expected total_head_reported {total_head_reported}, "
        f"got {window['total_head_reported']}"
    )
    assert window["accepted_submission_count"] == accepted_submission_count, (
        f"expected accepted_submission_count {accepted_submission_count}, "
        f"got {window['accepted_submission_count']}"
    )


# ---------------------------------------------------------------------------
# Submission totals and lateness (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------


def assert_submission_totals(
    submission,
    reported_head=None,
    reported_cwt=None,
    reported_value_dollars=None,
    reported_pounds=None,
    reported_load_count=None,
):
    if reported_head is not None:
        assert submission["reported_head"] == reported_head, submission
    if reported_cwt is not None:
        assert submission["reported_cwt"] == reported_cwt, submission
    if reported_value_dollars is not None:
        assert submission["reported_value_dollars"] == reported_value_dollars, submission
    if reported_pounds is not None:
        assert submission["reported_pounds"] == reported_pounds, submission
    if reported_load_count is not None:
        assert submission["reported_load_count"] == reported_load_count, submission


def assert_lateness(submission, lateness_minutes, is_late, days_late):
    assert submission["lateness_minutes"] == lateness_minutes, submission
    assert submission["is_late"] is is_late, submission
    assert submission["days_late"] == days_late, submission


# ---------------------------------------------------------------------------
# Market report (PRD §3.6)
# ---------------------------------------------------------------------------


def assert_report_dimensions(
    report, aggregation_state=None, disclosure_state=None, publication_state=None
):
    """Assert the three independent state dimensions of a market report."""
    if aggregation_state is not None:
        assert report["aggregation_state"] == aggregation_state, report
    if disclosure_state is not None:
        assert report["disclosure_state"] == disclosure_state, report
    if publication_state is not None:
        assert report["publication_state"] == publication_state, report


def assert_initial_report_dimensions(report):
    assert_report_dimensions(
        report,
        AggregationState.PENDING.value,
        DisclosureState.UNREVIEWED.value,
        PublicationState.UNPUBLISHED.value,
    )


def assert_price_statistics(report, average, low, high):
    assert report["weighted_average_price_per_cwt"] == average, report
    assert report["price_low_per_cwt"] == low, report
    assert report["price_high_per_cwt"] == high, report


def assert_report_masked(report, suppression_reason, reporter_count, max_reporter_share_pct):
    """A WITHHELD report nulls prices and volumes but retains the two counters."""
    assert report["disclosure_state"] == DisclosureState.WITHHELD.value, report
    assert report["suppression_reason"] == suppression_reason, report
    for field in (
        "weighted_average_price_per_cwt",
        "price_low_per_cwt",
        "price_high_per_cwt",
        "total_head",
        "total_pounds",
    ):
        assert report[field] is None, f"{field} must be masked to null on a withheld report"
    assert report["reporter_count"] == reporter_count, report
    assert report["max_reporter_share_pct"] == max_reporter_share_pct, report


# ---------------------------------------------------------------------------
# Audit case (PRD §3.7)
# ---------------------------------------------------------------------------


def assert_discrepancy_rates(case, head_rate, value_rate, finding):
    assert case["head_discrepancy_rate_pct"] == head_rate, case
    assert case["value_discrepancy_rate_pct"] == value_rate, case
    assert case["finding"] == finding, case


# ---------------------------------------------------------------------------
# Penalty assessment and firm ledger (PRD §2.11, §3.8)
# ---------------------------------------------------------------------------


def assert_penalty_breakdown(
    penalty,
    base_amount_cents=None,
    days_late=None,
    day_tier_multiplier=None,
    repeat_index=None,
    repeat_multiplier=None,
    volume_factor=None,
    suspension_surcharge=None,
    assessed_amount_cents=None,
    points=None,
    delinquency_tier_at_assessment=None,
):
    """Assert the retained multiplier breakdown of an assessment."""
    expected = {
        "base_amount_cents": base_amount_cents,
        "days_late": days_late,
        "day_tier_multiplier": day_tier_multiplier,
        "repeat_index": repeat_index,
        "repeat_multiplier": repeat_multiplier,
        "volume_factor": volume_factor,
        "suspension_surcharge": suspension_surcharge,
        "assessed_amount_cents": assessed_amount_cents,
        "points": points,
        "delinquency_tier_at_assessment": delinquency_tier_at_assessment,
    }
    for field, value in expected.items():
        if value is not None:
            assert penalty[field] == value, (
                f"expected {field} {value}, got {penalty[field]}"
            )


def assert_penalty_ledger(
    entity,
    assessed_penalty_cents=None,
    paid_penalty_cents=None,
    waived_penalty_cents=None,
    outstanding_penalty_cents=None,
    delinquency_points=None,
):
    expected = {
        "assessed_penalty_cents": assessed_penalty_cents,
        "paid_penalty_cents": paid_penalty_cents,
        "waived_penalty_cents": waived_penalty_cents,
        "outstanding_penalty_cents": outstanding_penalty_cents,
        "delinquency_points": delinquency_points,
    }
    for field, value in expected.items():
        if value is not None:
            assert entity[field] == value, f"expected {field} {value}, got {entity[field]}"
    assert_penalty_conservation(entity)


def assert_penalty_conservation(entity):
    """assessed equals paid plus waived plus outstanding, all non-negative."""
    assert entity["assessed_penalty_cents"] == (
        entity["paid_penalty_cents"]
        + entity["waived_penalty_cents"]
        + entity["outstanding_penalty_cents"]
    ), (
        "conservation invariant broken: "
        f"{entity['assessed_penalty_cents']} != "
        f"{entity['paid_penalty_cents']} + {entity['waived_penalty_cents']} + "
        f"{entity['outstanding_penalty_cents']}"
    )
    for field in (
        "assessed_penalty_cents",
        "paid_penalty_cents",
        "waived_penalty_cents",
        "outstanding_penalty_cents",
        "delinquency_points",
    ):
        assert isinstance(entity[field], int) and entity[field] >= 0, (
            f"{field} must be a non-negative integer, got {entity[field]}"
        )
