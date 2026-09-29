"""Domain assertions for the Pentest Assurance API test suite.

These helpers exist for two reasons. Instants are rendered by the server with
exactly three fractional-second digits, so a literal string comparison against
an instant written without them would fail for the wrong reason; and three
system-wide invariants (the hour ledger, the risk-point ledger and the
alert-existence rule) are worth checking in one place rather than in a dozen.
"""

from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .constants import SCORE_TOLERANCE


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def parse_instant(value):
    """Parse an ISO 8601 UTC instant into an aware ``datetime``."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected, label="instant"):
    """Compare two instants by value, ignoring fractional-digit rendering."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instants_equal(actual, expected, label="instant"):
    """Alias kept for readability at call sites that compare two fields."""
    assert_instant_equals(actual, expected, label)


def assert_three_fractional_digits(value, label="timestamp"):
    """Every persisted instant is rendered with exactly three fractional digits."""
    assert isinstance(value, str), f"{label}: expected a string, got {value!r}"
    body = value[:-1] if value.endswith("Z") else value
    assert "." in body, f"{label}: {value!r} carries no fractional part"
    fraction = body.split(".", 1)[1]
    assert len(fraction) == 3 and fraction.isdigit(), (
        f"{label}: {value!r} does not carry exactly three fractional digits"
    )


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
def assert_score(actual, expected, label="score"):
    """Compare a server-computed two-decimal score."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_exact_int(actual, expected, label="value"):
    """Risk points and rank numbers are integers and are never rounded."""
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Envelope shortcuts
# ---------------------------------------------------------------------------
def success_data(response, expected_status=200):
    """Validate the success envelope and return ``data``."""
    return validate_success(response, expected_status=expected_status)


def created_data(response):
    """Validate a 201 envelope and return the created resource."""
    return validate_success(response, expected_status=201)


def error_data(response, error_id):
    """Validate an error envelope, including its catalogued HTTP status."""
    return validate_error(response, error_id)


def assert_error_id(response, error_id):
    """Assert a specific ``error_id`` and return the error payload."""
    payload = validate_error(response, error_id)
    assert payload.get("message"), "an error response must carry a human-readable message"
    return payload


def assert_error_id_in(response, error_ids):
    """Assert the ``error_id`` is one of ``error_ids`` and return the one seen.

    Used where the requirements name more than one refusal that a single request
    legitimately trips, without stating which of them answers first.
    """
    return validate_error_is_one_of(response, list(error_ids))


def paginated(response):
    """Validate a list envelope and return ``(rows, meta)``."""
    return validate_paginated(response)


def assert_page(response, total_count=None, has_more=None, row_count=None,
                limit=None, offset=None):
    """Validate a list envelope and assert the pagination fields it reports."""
    rows, meta = validate_paginated(response)
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    if row_count is not None:
        assert len(rows) == row_count, (
            f"page size: expected {row_count} rows, got {len(rows)}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    return rows, meta


# ---------------------------------------------------------------------------
# System fields
# ---------------------------------------------------------------------------
def assert_system_fields(resource, version=None):
    """Every mutable resource carries an id, both timestamps and a version."""
    from prd_bench_local_runner.testing import is_valid_uuid

    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource.get('id')!r}"
    assert_three_fractional_digits(resource["created_at"], "created_at")
    assert_three_fractional_digits(resource["updated_at"], "updated_at")
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"
    if version is not None:
        assert resource["version"] == version, (
            f"version: expected {version}, got {resource['version']}"
        )


def assert_analytics_record_shape(record):
    """A training recommendation carries id and created_at and nothing else system-side."""
    from prd_bench_local_runner.testing import is_valid_uuid

    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record.get('id')!r}"
    assert_three_fractional_digits(record["created_at"], "created_at")
    assert "updated_at" not in record, "an immutable analytics record has no updated_at"
    assert "version" not in record, "an immutable analytics record has no version"


def assert_version_unchanged(before, after, label="version"):
    """A rejected write must not advance the parent's version."""
    assert before == after, f"{label}: expected {before} to be unchanged, got {after}"


# ---------------------------------------------------------------------------
# The engagement hour ledger
# ---------------------------------------------------------------------------
def assert_hour_ledger_balanced(engagement):
    """hours_allocated always equals reserved + consumed + available."""
    allocated = engagement["hours_allocated"]
    parts = (
        engagement["hours_reserved"]
        + engagement["hours_consumed"]
        + engagement["hours_available"]
    )
    assert allocated == parts, (
        "hour ledger is unbalanced: allocated "
        f"{allocated} != reserved {engagement['hours_reserved']} + consumed "
        f"{engagement['hours_consumed']} + available {engagement['hours_available']}"
    )


def assert_hour_ledger(engagement, allocated=None, reserved=None, consumed=None,
                       available=None):
    """Assert the four hour buckets and the invariant that ties them together."""
    if allocated is not None:
        assert_exact_int(engagement["hours_allocated"], allocated, "hours_allocated")
    if reserved is not None:
        assert_exact_int(engagement["hours_reserved"], reserved, "hours_reserved")
    if consumed is not None:
        assert_exact_int(engagement["hours_consumed"], consumed, "hours_consumed")
    if available is not None:
        assert_exact_int(engagement["hours_available"], available, "hours_available")
    assert_hour_ledger_balanced(engagement)


# ---------------------------------------------------------------------------
# The plan risk-point ledger
# ---------------------------------------------------------------------------
def assert_risk_ledger_balanced(plan):
    """total_risk_points always equals open + closed + accepted + duplicate."""
    total = plan["total_risk_points"]
    parts = (
        plan["open_risk_points"]
        + plan["closed_risk_points"]
        + plan["accepted_risk_points"]
        + plan["duplicate_risk_points"]
    )
    assert total == parts, (
        f"risk-point ledger is unbalanced: total {total} != open "
        f"{plan['open_risk_points']} + closed {plan['closed_risk_points']} + accepted "
        f"{plan['accepted_risk_points']} + duplicate {plan['duplicate_risk_points']}"
    )


def assert_risk_ledger(plan, total=None, open_points=None, closed=None, accepted=None,
                       duplicate=None):
    """Assert the five risk-point buckets and the conservation invariant."""
    if total is not None:
        assert_exact_int(plan["total_risk_points"], total, "total_risk_points")
    if open_points is not None:
        assert_exact_int(plan["open_risk_points"], open_points, "open_risk_points")
    if closed is not None:
        assert_exact_int(plan["closed_risk_points"], closed, "closed_risk_points")
    if accepted is not None:
        assert_exact_int(plan["accepted_risk_points"], accepted, "accepted_risk_points")
    if duplicate is not None:
        assert_exact_int(plan["duplicate_risk_points"], duplicate, "duplicate_risk_points")
    assert_risk_ledger_balanced(plan)


# ---------------------------------------------------------------------------
# Asset posture, engagement axes, severity
# ---------------------------------------------------------------------------
_UNSET = object()


def assert_asset_posture(asset, exposure_state=None, open_findings=None,
                         open_critical=None, remediated=None, last_cleared_at=_UNSET):
    """Assert an asset's exposure state and its three finding counters."""
    if exposure_state is not None:
        assert asset["exposure_state"] == exposure_state, (
            f"exposure_state: expected {exposure_state}, got {asset['exposure_state']}"
        )
    if open_findings is not None:
        assert_exact_int(asset["open_finding_count"], open_findings, "open_finding_count")
    if open_critical is not None:
        assert_exact_int(
            asset["open_critical_finding_count"], open_critical,
            "open_critical_finding_count",
        )
    if remediated is not None:
        assert_exact_int(
            asset["remediated_finding_count"], remediated, "remediated_finding_count"
        )
    if last_cleared_at is not _UNSET:
        if last_cleared_at is None:
            assert asset["last_cleared_at"] is None, (
                f"last_cleared_at: expected null, got {asset['last_cleared_at']}"
            )
        else:
            assert_instant_equals(
                asset["last_cleared_at"], last_cleared_at, "last_cleared_at"
            )


def assert_engagement_axes(engagement, execution_state=None, authorization_state=None):
    """The two engagement lifecycle axes move independently and are asserted together."""
    if execution_state is not None:
        assert engagement["execution_state"] == execution_state, (
            f"execution_state: expected {execution_state}, "
            f"got {engagement['execution_state']}"
        )
    if authorization_state is not None:
        assert engagement["authorization_state"] == authorization_state, (
            f"authorization_state: expected {authorization_state}, "
            f"got {engagement['authorization_state']}"
        )


def assert_severity(finding, score=None, band=None, points=None, immediate=None):
    """Assert a finding's derived severity trio and its immediate-action flag."""
    if score is not None:
        assert_score(finding["severity_score"], score, "severity_score")
    if band is not None:
        assert finding["severity_band"] == band, (
            f"severity_band: expected {band}, got {finding['severity_band']}"
        )
    if points is not None:
        assert_exact_int(finding["severity_points"], points, "severity_points")
    if immediate is not None:
        assert finding["immediate_action_required"] is immediate, (
            f"immediate_action_required: expected {immediate}, "
            f"got {finding['immediate_action_required']}"
        )


# ---------------------------------------------------------------------------
# Critical alert existence
# ---------------------------------------------------------------------------
def find_alert_for_finding(client, finding_id, headers=None):
    """Return the critical alert raised for a finding, or None when there is none."""
    rows, _meta = validate_paginated(
        client.list_critical_alerts(params={"finding_id": finding_id}, headers=headers)
    )
    return rows[0] if rows else None


def assert_alert_raised(client, finding_id, ack_deadline_at=None, state=None,
                        escalation_level=None, headers=None):
    """A CRITICAL finding must have exactly one alert; assert it and return it."""
    rows, meta = validate_paginated(
        client.list_critical_alerts(params={"finding_id": finding_id}, headers=headers)
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one critical alert for finding {finding_id}, "
        f"got {meta['total_count']}"
    )
    alert = rows[0]
    assert alert["finding_id"] == finding_id
    if ack_deadline_at is not None:
        assert_instant_equals(alert["ack_deadline_at"], ack_deadline_at, "ack_deadline_at")
    if state is not None:
        assert alert["state"] == state, f"alert state: expected {state}, got {alert['state']}"
    if escalation_level is not None:
        assert_exact_int(alert["escalation_level"], escalation_level, "escalation_level")
    return alert


def assert_no_alert_raised(client, finding_id, headers=None):
    """A finding below the CRITICAL band must raise no alert at all."""
    _rows, meta = validate_paginated(
        client.list_critical_alerts(params={"finding_id": finding_id}, headers=headers)
    )
    assert meta["total_count"] == 0, (
        f"expected no critical alert for finding {finding_id}, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Analytics generation
# ---------------------------------------------------------------------------
def emitted_rows(response):
    """Return the rows emitted by a trend-analysis generation call.

    Section 4 pins HTTP 201 for the creation of a resource and HTTP 200 for
    every other successful operation, and a generation call that emits a whole
    collection of immutable records answers to both descriptions, so the rows
    themselves rather than the status line are what these tests assert.
    """
    assert response.status_code in (200, 201), (
        f"expected 200 or 201 from a generation call, got "
        f"{response.status_code}: {response.text}"
    )
    body = response.json()
    assert "meta" in body, "Missing 'meta' in response envelope"
    assert "data" in body, "Missing 'data' in response envelope"
    assert body.get("response_type") in ("object", "array"), (
        f"unexpected response_type {body.get('response_type')!r}"
    )
    return body["data"]
