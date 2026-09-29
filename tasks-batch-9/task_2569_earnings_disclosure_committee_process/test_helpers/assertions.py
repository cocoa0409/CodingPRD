"""Domain assertions shared by the suite.

These wrap the repetitive shape checks — the four common record properties, the
two-decimal money convention, the normalised rendering of a computed instant,
and the ascending rule-ladder ordering of the readiness dashboard's blocking
list — so the test bodies read as statements about the business rules.
"""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_errors import ladder_rank

MONEY_TOLERANCE = 0.01


def assert_common_record(record):
    """Every persisted record carries id, created_at, updated_at and version,
    and no record type omits any of them."""
    assert is_valid_uuid(record["id"]), f"id must be a UUID with no prefix: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int), "version must be an integer"
    assert record["version"] >= 1, "version starts at 1"


def assert_fresh_record(record):
    """A row that has never been mutated reads version 1."""
    assert_common_record(record)
    assert record["version"] == 1, f"a freshly created row starts at version 1, got {record['version']}"


def assert_three_fractional_digits(instant):
    """Timestamps are rendered with exactly three fractional-second digits and
    a trailing Z."""
    assert instant.endswith("Z"), f"{instant} must end with Z"
    assert "." in instant, f"{instant} must carry fractional seconds"
    fraction = instant.split(".")[1][:-1]
    assert len(fraction) == 3, f"{instant} must carry exactly three fractional digits"


def _parse(instant):
    text = instant.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equals(actual, expected):
    """Compare two ISO 8601 UTC instants by the moment they name, so that a
    rendering carrying the normalised `.000` fraction matches one without it."""
    assert actual is not None, f"expected the instant {expected}, got null"
    assert _parse(actual) == _parse(expected), f"expected {expected}, got {actual}"


def assert_money(actual, expected):
    """Monetary amounts, weights and percentages are carried to two decimal
    places."""
    assert actual is not None, f"expected {expected}, got null"
    assert float(actual) == pytest.approx(float(expected), abs=MONEY_TOLERANCE / 2), (
        f"expected {expected}, got {actual}"
    )


def assert_two_decimal_places(value):
    """A two-decimal quantity never carries a third significant decimal."""
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{value} carries more than two decimal places"
    )


def assert_integer(value):
    """Slack figures, prominence indices, quorum counts, buffer day counts and
    event counts are integers with no rounding at all."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{value!r} must be an integer"
    )


def assert_ladder_order(error_ids):
    """The blocking list is de-duplicated and in ascending order of the rule
    ladder."""
    assert len(error_ids) == len(set(error_ids)), f"duplicated identifiers in {error_ids}"
    ranks = [ladder_rank(e) for e in error_ids]
    assert ranks == sorted(ranks), f"{error_ids} is not in ascending rule-ladder order"


def assert_blocking(readiness, expected_ids):
    """The blocking list matches exactly, in order, and the eligibility flag
    agrees with its emptiness."""
    actual = readiness["blocking_error_ids"]
    assert actual == list(expected_ids), f"expected blocking {list(expected_ids)}, got {actual}"
    assert_ladder_order(actual)
    assert readiness["filing_ready_eligible"] is (len(actual) == 0), (
        "filing_ready_eligible is true if and only if blocking_error_ids is empty"
    )


def assert_version_bumped_by(before, after, amount=1):
    assert after == before + amount, (
        f"expected version {before} + {amount}, got {after}"
    )


def find_by_id(rows, row_id):
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError(f"row {row_id} is absent from the listing")


def ids_of(rows):
    return [row["id"] for row in rows]


def assert_cycle_rollups(cycle, total_weight=None, coverage=None, open_events=None,
                         deficiency_weight=None):
    """Spot-check the cycle's conserved roll-ups and its event count."""
    if total_weight is not None:
        assert_money(cycle["total_assigned_scope_weight"], total_weight)
    if coverage is not None:
        assert_money(cycle["certification_coverage_pct"], coverage)
    if open_events is not None:
        assert cycle["open_material_event_count"] == open_events, (
            f"expected {open_events} open material events, got {cycle['open_material_event_count']}"
        )
    if deficiency_weight is not None:
        assert_money(cycle["unresolved_deficiency_weight"], deficiency_weight)


def assert_slack(record, calendar_days, business_days):
    """A milestone or cycle reports both slack variants."""
    actual_calendar = record.get("slack_calendar_days", record.get("min_slack_days_calendar"))
    actual_business = record.get("slack_business_days", record.get("min_slack_days_business"))
    assert actual_calendar == calendar_days, (
        f"expected calendar slack {calendar_days}, got {actual_calendar}"
    )
    assert actual_business == business_days, (
        f"expected business slack {business_days}, got {actual_business}"
    )
