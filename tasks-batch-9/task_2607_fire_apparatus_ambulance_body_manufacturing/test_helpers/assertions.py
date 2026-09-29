"""Domain assertion helpers.

These wrap the shape rules that hold across the whole API — the audit-field
contract, the two-resource immutable exception, list metadata and the version
counters — so individual tests can assert business outcomes instead of
re-checking envelope structure.
"""

import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import DEFAULT_LIMIT

_THREE_FRACTIONAL_DIGITS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


# ─── Audit fields ─────────────────────────────────────────────────────────

def assert_audit_fields(record, expected_version=None):
    """A mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int), record["version"]
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_immutable_record_fields(record):
    """A clause and a bay carry only id and created_at.

    Both ``updated_at`` and ``version`` are absent from them entirely.
    """
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "an immutable resource carries no updated_at"
    assert "version" not in record, "an immutable resource carries no version"


def assert_created_at_precision(record):
    """``created_at`` is an ISO 8601 UTC timestamp with three fractional digits.

    The requirements pin the precision of the audit stamp -- "a ``created_at``,
    which is an ISO 8601 UTC timestamp with three fractional digits recording
    when the row was first written" -- but never say which time source writes
    it, so only the rendering is asserted here.
    """
    assert _THREE_FRACTIONAL_DIGITS.match(record["created_at"]), record["created_at"]


def assert_updated_at_refreshed(record):
    """``updated_at`` is "refreshed on every mutation", so it never precedes
    ``created_at``.

    The requirements do not name the time source that writes either stamp, so
    only their ordering and their ISO 8601 rendering are asserted.
    """
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert _instant(record["updated_at"]) >= _instant(record["created_at"]), record


def _instant(value):
    """Parse an ISO 8601 UTC timestamp, with or without fractional digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def assert_clock_stamp(actual, expected_instant):
    """A field stamped from the logical clock records that exact instant.

    The requirements pin *which* instant such a field carries -- delivery
    "stamping ``delivered_at`` with the current logical clock", a hold
    "stamps ``held_at`` with the current logical clock" -- but they never pin
    whether these fields are serialised with fractional digits, so the two
    renderings are compared as instants rather than as strings.
    """
    assert isinstance(actual, str), f"expected a timestamp string, got {actual!r}"
    assert _instant(actual) == _instant(expected_instant), (
        f"expected the instant {expected_instant}, got {actual}"
    )


def assert_version_advanced_by(record, previous_version, increments):
    assert record["version"] == previous_version + increments, (
        f"expected version {previous_version + increments}, got {record['version']}"
    )


# ─── List metadata ────────────────────────────────────────────────────────

def assert_list_meta(meta, total_count=None, has_more=None, limit=DEFAULT_LIMIT,
                     offset=0):
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta
    assert meta["limit"] == limit, meta
    assert meta["offset"] == offset, meta
    if total_count is not None:
        assert meta["total_count"] == total_count, meta
    if has_more is not None:
        assert meta["has_more"] is has_more, meta


def assert_ids_in_order(rows, expected_ids):
    """Lists are sorted by created_at ascending, oldest row first."""
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"expected {list(expected_ids)}, got {[row['id'] for row in rows]}"
    )


def assert_response_envelope(response_json, response_type):
    assert response_json["response_type"] == response_type, response_json
    assert response_json["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(response_json["meta"]["api_request_timestamp"])


# ─── Program ledger ───────────────────────────────────────────────────────

def assert_program_ledger(program, committed_cents, status, suspension_reason):
    assert program["committed_cents"] == committed_cents, program
    assert program["status"] == status, program
    assert program["suspension_reason"] == suspension_reason, program


def soft_ceiling(contract_ceiling_cents):
    """Ninety percent of the hard ceiling, quantised with round-half-up.

    Committed money landing exactly on this figure is not a breach; the
    comparison is strict.
    """
    return int(
        (Decimal(contract_ceiling_cents) * 90 / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


# ─── Unit order weight model ──────────────────────────────────────────────

def assert_axle_loads(unit, front_kg, rear_kg, gross_kg, weight_status):
    assert unit["front_axle_load_kg"] == front_kg, unit
    assert unit["rear_axle_load_kg"] == rear_kg, unit
    assert unit["gross_weight_kg"] == gross_kg, unit
    assert unit["weight_status"] == weight_status, unit


def assert_unit_dimensions(unit, build_status=None, certification_status=None,
                           long_lead_status=None, spec_drift_flag=None):
    """The three status dimensions advance on entirely different triggers."""
    if build_status is not None:
        assert unit["build_status"] == build_status, unit
    if certification_status is not None:
        assert unit["certification_status"] == certification_status, unit
    if long_lead_status is not None:
        assert unit["long_lead_status"] == long_lead_status, unit
    if spec_drift_flag is not None:
        assert unit["spec_drift_flag"] is spec_drift_flag, unit


def assert_unit_money(unit, price_cents=None, change_order_total_cents=None,
                      open_change_order_count=None):
    if price_cents is not None:
        assert unit["price_cents"] == price_cents, unit
    if change_order_total_cents is not None:
        assert unit["change_order_total_cents"] == change_order_total_cents, unit
    if open_change_order_count is not None:
        assert unit["open_change_order_count"] == open_change_order_count, unit


# ─── Specification scores ─────────────────────────────────────────────────

def assert_spec_scores(spec, strict=None, provisional=None, restrictive_ratio=None,
                       clause_count=None, mandatory_clause_count=None):
    if strict is not None:
        assert float(spec["compliance_score_strict"]) == strict, spec
    if provisional is not None:
        assert float(spec["compliance_score_provisional"]) == provisional, spec
    if restrictive_ratio is not None:
        assert float(spec["restrictive_clause_ratio_pct"]) == restrictive_ratio, spec
    if clause_count is not None:
        assert spec["clause_count"] == clause_count, spec
    if mandatory_clause_count is not None:
        assert spec["mandatory_clause_count"] == mandatory_clause_count, spec


# ─── Slot line occupancy ──────────────────────────────────────────────────

def assert_slot_occupancy(line, reserved, available, total=None):
    """Availability is total minus occupancy and is a conserved quantity."""
    assert line["reserved_slot_count"] == reserved, line
    assert line["available_slot_count"] == available, line
    if total is not None:
        assert line["total_slot_count"] == total, line
    assert (
        line["available_slot_count"]
        == line["total_slot_count"] - line["reserved_slot_count"]
    ), line
    assert line["available_slot_count"] >= 0, line


# ─── Sweep report ─────────────────────────────────────────────────────────

def assert_sweep_report(report, program_id, expired_reservation_count,
                        warranty_activated_count, warranty_expired_count,
                        committed_cents, program_status):
    assert report["program_id"] == program_id, report
    assert report["expired_reservation_count"] == expired_reservation_count, report
    assert report["warranty_activated_count"] == warranty_activated_count, report
    assert report["warranty_expired_count"] == warranty_expired_count, report
    assert report["committed_cents"] == committed_cents, report
    assert report["program_status"] == program_status, report


# ─── Warranty window ──────────────────────────────────────────────────────

def assert_calendar_date(actual, expected_date):
    """Compare a stored warranty date against a ``YYYY-MM-DD`` expectation.

    The requirements pin the calendar day a warranty window lands on -- whole
    days for the deferral and whole calendar months for the term -- without
    pinning whether the field is serialised as a bare date or as a full
    timestamp, so only the calendar-date component is compared.
    """
    assert isinstance(actual, str), f"expected a date string, got {actual!r}"
    assert actual[:10] == expected_date, f"expected {expected_date}, got {actual}"


def assert_warranty_window(warranty, status=None, training_hours=None,
                           start_date=None, end_date=None):
    if status is not None:
        assert warranty["status"] == status, warranty
    if training_hours is not None:
        assert float(warranty["training_hours"]) == training_hours, warranty
    if start_date is not None:
        assert_calendar_date(warranty["warranty_start_date"], start_date)
    if end_date is not None:
        assert_calendar_date(warranty["warranty_end_date"], end_date)


def assert_price_reconciliation(warranty, final_price_cents, price_variance_cents):
    assert warranty["final_price_cents"] == final_price_cents, warranty
    assert warranty["price_variance_cents"] == price_variance_cents, warranty
