"""Domain assertion helpers.

These wrap the repetitive shape and precision checks the PRD mandates so that
individual tests read as statements about fire-district behaviour rather than
as dictionary plumbing.
"""

from datetime import datetime, timezone

import pytest

from .constants import (
    END_OF_DAY_SUFFIX,
    REQUEST_ID_PREFIX,
    RESPONSE_TYPE_ERROR,
    WATERFALL_BUCKETS,
)
from .types import APPEND_ONLY_FIELDS, COMMON_FIELDS

# Tolerances: the PRD fixes the number of decimals for each family of numbers,
# so comparisons only need to absorb float representation noise.
TOL_2DP = 0.001
TOL_1DP = 0.01
TOL_4DP = 0.00001


# ---------------------------------------------------------------------------
# Envelope and system fields
# ---------------------------------------------------------------------------

def assert_envelope_meta(response, expected_response_type=None):
    """Every response carries meta.api_request_id prefixed 'req_'.

    ``response_type`` lives at the top level of the envelope, beside ``meta``
    and ``data``, and is checked when the caller names the expected value.
    """
    body = response.json() if hasattr(response, "json") else response
    meta = body["meta"]
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX)
    assert isinstance(meta["api_request_timestamp"], str)
    if expected_response_type is not None:
        assert body["response_type"] == expected_response_type, (
            "response_type %r != %r" % (body["response_type"], expected_response_type)
        )
    return body


def assert_error_response_type(response):
    body = response.json() if hasattr(response, "json") else response
    assert body["response_type"] == RESPONSE_TYPE_ERROR


def assert_common_fields(row):
    """id, created_at, updated_at and version are all present."""
    for field in COMMON_FIELDS:
        assert field in row, "expected system field %s" % field


def assert_append_only_row(row):
    """An append-only record exposes id and created_at but no version."""
    for field in APPEND_ONLY_FIELDS:
        assert field in row, "expected system field %s" % field
    assert "version" not in row, "append-only records carry no version"
    assert "updated_at" not in row, "append-only records carry no updated_at"


def assert_version(row, expected):
    assert row["version"] == expected, "version %s != %s" % (
        row["version"],
        expected,
    )


def assert_fields_present(row, fields):
    missing = [f for f in fields if f not in row]
    assert not missing, "missing fields: %s" % missing


def assert_unchanged(before, after, fields):
    """None of the named fields moved between two reads of the same row."""
    for field in fields:
        assert before[field] == after[field], "%s changed from %r to %r" % (
            field,
            before[field],
            after[field],
        )


# ---------------------------------------------------------------------------
# Precision families
# ---------------------------------------------------------------------------

def assert_2dp(actual, expected):
    """A score or percentage carried to two decimals."""
    if expected is None:
        assert actual is None, "expected null, got %r" % (actual,)
        return
    assert actual is not None, "expected %r, got null" % (expected,)
    assert actual == pytest.approx(expected, abs=TOL_2DP)


def assert_1dp(actual, expected):
    """A clearance measured in feet to one decimal."""
    if expected is None:
        assert actual is None, "expected null, got %r" % (actual,)
        return
    assert actual is not None, "expected %r, got null" % (expected,)
    assert actual == pytest.approx(expected, abs=TOL_1DP)


def assert_ratio(actual, expected):
    """A deficit ratio carried to four decimals."""
    if expected is None:
        assert actual is None, "expected null, got %r" % (actual,)
        return
    assert actual is not None, "expected %r, got null" % (expected,)
    assert actual == pytest.approx(expected, abs=TOL_4DP)


def assert_cents(actual, expected):
    """Money is an integer number of cents and is compared exactly."""
    assert actual == expected, "%r cents != %r cents" % (actual, expected)
    if actual is not None:
        assert isinstance(actual, int), "money must be an integer of cents"


def normalize_instant(value):
    """Reduce an ISO 8601 UTC string to the instant it names.

    The PRD spells timestamps with three fractional-second digits while the
    end-of-day deadlines carry none, so two spellings of the same moment must
    compare equal: these helpers assert *instants*, never formatting.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def assert_end_of_day(timestamp, date_prefix):
    """A derived deadline lands on 23:59:59 UTC on the named date."""
    expected = date_prefix + END_OF_DAY_SUFFIX
    assert normalize_instant(timestamp) == normalize_instant(
        expected
    ), "%r is not %s end of day" % (timestamp, date_prefix)


def assert_instant(timestamp, expected):
    assert normalize_instant(timestamp) == normalize_instant(expected), "%r != %r" % (
        timestamp,
        expected,
    )


# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------

def assert_risk(parcel, score, risk_class, basis=None):
    assert_2dp(parcel["risk_score"], score)
    assert parcel["risk_class"] == risk_class, "%r != %r" % (
        parcel["risk_class"],
        risk_class,
    )
    if basis is not None:
        assert parcel["risk_score_basis"] == basis


def assert_posture(parcel, compliance_status, open_violation_count=None):
    assert parcel["compliance_status"] == compliance_status, "%r != %r" % (
        parcel["compliance_status"],
        compliance_status,
    )
    if open_violation_count is not None:
        assert parcel["open_violation_count"] == open_violation_count


# ---------------------------------------------------------------------------
# Zone evaluations
# ---------------------------------------------------------------------------

def assert_zone_grade(row, required_ft, deficit_ft, ratio, severity, points):
    assert_1dp(row["required_clearance_ft"], required_ft)
    assert_1dp(row["deficit_ft"], deficit_ft)
    assert_ratio(row["deficit_ratio"], ratio)
    assert row["deficiency_severity"] == severity, "%r != %r" % (
        row["deficiency_severity"],
        severity,
    )
    assert_2dp(row["points"], points)


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------

def assert_notice_schedule(
    notice, severity, delivered_at_utc, compliance_days, deadline_date, status=None
):
    assert notice["severity"] == severity, "%r != %r" % (notice["severity"], severity)
    assert_instant(notice["delivered_at_utc"], delivered_at_utc)
    assert notice["compliance_days"] == compliance_days, "%r days != %r days" % (
        notice["compliance_days"],
        compliance_days,
    )
    assert_end_of_day(notice["deadline_utc"], deadline_date)
    if status is not None:
        assert notice["status"] == status


# ---------------------------------------------------------------------------
# Cost recovery
# ---------------------------------------------------------------------------

def assert_cost_recovery(
    order,
    labor,
    disposal,
    mobilization,
    overhead,
    pre_subsidy_total,
    subsidy_pct,
    subsidy,
    total_recoverable,
    recovery_basis=None,
):
    assert_cents(order["labor_line_cents"], labor)
    assert_cents(order["disposal_line_cents"], disposal)
    assert_cents(order["mobilization_line_cents"], mobilization)
    assert_cents(order["admin_overhead_cents"], overhead)
    assert_cents(order["pre_subsidy_total_cents"], pre_subsidy_total)
    assert_2dp(order["subsidy_pct"], subsidy_pct)
    assert_cents(order["district_subsidy_cents"], subsidy)
    assert_cents(order["total_recoverable_cents"], total_recoverable)
    if recovery_basis is not None:
        assert order["recovery_basis"] == recovery_basis


def assert_allocation(payment, admin_overhead, mobilization, disposal, labor):
    """The waterfall allocation, bucket by bucket in the PRD's fixed order."""
    allocation = payment["allocation"]
    expected = {
        "ADMIN_OVERHEAD": admin_overhead,
        "MOBILIZATION": mobilization,
        "DISPOSAL": disposal,
        "LABOR": labor,
    }
    for bucket in WATERFALL_BUCKETS:
        assert bucket in allocation, "allocation is missing bucket %s" % bucket
        assert_cents(allocation[bucket], expected[bucket])


# ---------------------------------------------------------------------------
# Support programs and enrollments
# ---------------------------------------------------------------------------

def assert_award(
    enrollment, award_before_bonus, bonus_pct, hardship_bonus, award, reserved=None
):
    assert_cents(enrollment["award_before_bonus_cents"], award_before_bonus)
    assert_2dp(enrollment["bonus_pct"], bonus_pct)
    assert_cents(enrollment["hardship_bonus_cents"], hardship_bonus)
    assert_cents(enrollment["award_cents"], award)
    if reserved is not None:
        assert_cents(enrollment["reserved_amount_cents"], reserved)


def assert_program_capacity(program, budget_remaining, reserved_slots):
    assert_cents(program["budget_remaining_cents"], budget_remaining)
    assert program["reserved_slots"] == reserved_slots, "%r slots != %r slots" % (
        program["reserved_slots"],
        reserved_slots,
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def assert_metrics(metrics, eligible, compliant, rate_pct):
    assert metrics["eligible_parcel_count"] == eligible
    assert metrics["compliant_parcel_count"] == compliant
    assert_2dp(metrics["compliance_rate_pct"], rate_pct)


def assert_hours(actual, expected):
    """Crew hours are positive multiples of 0.5 carried to one decimal."""
    assert actual == pytest.approx(expected, abs=TOL_1DP), "%r hours != %r hours" % (
        actual,
        expected,
    )


def ids_of(rows):
    return [row["id"] for row in rows]
