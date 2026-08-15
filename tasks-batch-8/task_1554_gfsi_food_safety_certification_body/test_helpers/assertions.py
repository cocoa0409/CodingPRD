"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Timestamp comparisons use instant
equality so that the PRD's fractional-seconds rendering (PRD §2.4: ISO 8601
in UTC with three fractional digits) and the bare `...Z` rendering both
match the pinned logical-clock instants.
"""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_nullable_timestamp(value, field):
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601, got {value!r}"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional seconds."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equal(actual, expected_iso: str):
    """Assert two ISO 8601 strings denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual!r}"
    )


def assert_money(actual, expected: float):
    """Money is handled at two decimals with round-half-up (PRD §2.9)."""
    assert_cost_precision(actual)
    assert actual == pytest.approx(expected, abs=0.001), (
        f"Expected {expected}, got {actual}"
    )


def assert_scheme(data: dict):
    _assert_common_fields(data)
    assert data["code"] in ("SQF", "BRC")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["supported_category_codes"], list) and \
        len(data["supported_category_codes"]) > 0
    for field in ("critical_nc_days", "major_nc_days", "minor_nc_days",
                  "pass_score", "unannounced_every_n",
                  "unannounced_min_window_days", "announced_max_window_days",
                  "min_audit_gap_days", "cert_validity_days",
                  "witness_validity_days", "appeal_window_days",
                  "max_cap_rejections", "rotation_limit"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    for field in ("base_fee", "per_category_fee", "day_rate",
                  "unannounced_uplift_pct", "high_risk_multiplier"):
        assert isinstance(data[field], (int, float)), \
            f"{field} must be numeric"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["country"], str) and data["country"]


def assert_auditor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["competency_categories"], list)
    assert isinstance(data["conflicted_client_ids"], list)
    assert isinstance(data["active_audit_count"], int) and \
        data["active_audit_count"] >= 0
    assert data["calibration_status"] in ("CURRENT", "LAPSED")
    _assert_nullable_timestamp(data.get("last_witnessed_on"), "last_witnessed_on")


def assert_decision_maker(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data.get("linked_auditor_id") is None or \
        isinstance(data["linked_auditor_id"], str)


def assert_scope_entries(entries):
    assert isinstance(entries, list) and len(entries) > 0
    for entry in entries:
        assert isinstance(entry["category_code"], str) and entry["category_code"]
        assert entry["risk_tier"] in ("STANDARD", "HIGH")


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["scheme_id"])
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert_scope_entries(data["product_categories"])
    assert isinstance(data["scope_text"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert data.get("provisional_fee_quote") is None or \
        isinstance(data["provisional_fee_quote"], (int, float))
    _assert_nullable_timestamp(data.get("submitted_at"), "submitted_at")
    _assert_nullable_timestamp(data.get("reviewed_at"), "reviewed_at")


def assert_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data.get("auditor_id") is None or is_valid_uuid(data["auditor_id"])
    assert data.get("decision_maker_id") is None or \
        is_valid_uuid(data["decision_maker_id"])
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert data["audit_type"] in ("INITIAL", "SURVEILLANCE", "UNANNOUNCED")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "REPORT_SUBMITTED",
                              "DECIDED", "CANCELLED")
    assert data.get("reported_score") is None or \
        isinstance(data["reported_score"], (int, float))
    assert data.get("resolved_score") is None or \
        isinstance(data["resolved_score"], (int, float))
    assert data.get("audit_fee") is None or \
        isinstance(data["audit_fee"], (int, float))
    assert data.get("actual_days") is None or isinstance(data["actual_days"], int)
    assert data.get("decision_outcome") in (None, "GRANT", "DENY")
    _assert_nullable_timestamp(data.get("started_at"), "started_at")
    _assert_nullable_timestamp(data.get("reported_at"), "reported_at")
    _assert_nullable_timestamp(data.get("decided_at"), "decided_at")


def assert_nonconformity(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_id"])
    assert data["grade"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["clause_ref"], str) and data["clause_ref"]
    assert isinstance(data["description"], str)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "CLOSED", "OVERDUE")
    assert is_iso8601_timestamp(data["deadline"])
    assert data.get("cap_text") is None or isinstance(data["cap_text"], str)
    _assert_nullable_timestamp(data.get("submitted_at"), "submitted_at")
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0
    _assert_nullable_timestamp(data.get("reviewed_at"), "reviewed_at")


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["scheme_id"])
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["audit_id"])
    assert isinstance(data["certificate_number"], str) and \
        data["certificate_number"].startswith("CERT-")
    assert_scope_entries(data["product_categories"])
    assert isinstance(data["scope_text"], str)
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_to"])
    assert data["status"] in ("ACTIVE", "SUSPENDED", "WITHDRAWN", "EXPIRED")
    assert data.get("suspension_reason") in (None, "MANUAL", "NC_OVERDUE",
                                             "CAP_REJECT_LIMIT")
    assert is_iso8601_timestamp(data["status_changed_at"])
    assert isinstance(data["final_fee"], (int, float))


def assert_scope_change(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["certificate_id"])
    assert_scope_entries(data["requested_categories"])
    assert isinstance(data["reason"], str)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")
    assert data.get("decided_by") is None or isinstance(data["decided_by"], str)
    _assert_nullable_timestamp(data.get("decided_at"), "decided_at")


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["grounds"], str) and data["grounds"]
    assert data["status"] in ("FILED", "UPHELD", "OVERTURNED")
    assert data.get("decided_by") is None or isinstance(data["decided_by"], str)
    _assert_nullable_timestamp(data.get("decided_at"), "decided_at")


def assert_witness_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["auditor_id"])
    assert is_iso8601_timestamp(data["witnessed_on"])
    assert data["result"] in ("PASS", "FAIL")
    assert data.get("notes") is None or isinstance(data["notes"], str)


def assert_directory_listing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["client_name"], str) and data["client_name"]
    assert data["scheme_code"] in ("SQF", "BRC")
    assert isinstance(data["scope_summary"], str) and data["scope_summary"]
    assert data["status"] in ("LISTED", "UNLISTED")
    assert is_iso8601_timestamp(data["listed_at"])
    _assert_nullable_timestamp(data.get("unlisted_at"), "unlisted_at")
