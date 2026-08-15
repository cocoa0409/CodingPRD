"""Entity assertions and domain invariant checkers.

assert_timestamp_instant compares two ISO 8601 UTC renderings by instant:
the PRD pins *when* a timestamp lands (logical-clock arithmetic) while the
exact rendering of a derived timestamp (with or without fractional digits)
is left to the implementation, so tests compare parsed instants.
"""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _parse_instant(value: str) -> datetime:
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_timestamp_instant(actual: str, expected_iso: str):
    """Assert two ISO 8601 UTC timestamps denote the same instant."""
    actual_dt = _parse_instant(actual)
    expected_dt = _parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"Expected instant {expected_iso}, got {actual}"
    )


def assert_charge_precision(value: float):
    """Charge weights are carried to one tenth of a pound."""
    assert round(value, 1) == pytest.approx(value, abs=1e-9), (
        f"Charge {value} has precision finer than 0.1 lb"
    )


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts from its initial value"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_facility(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["threshold_lbs"], (int, float))
    assert isinstance(data["total_charge_lbs"], (int, float))
    assert data["charge_posture"] in ("BELOW_THRESHOLD", "AT_OR_ABOVE_THRESHOLD")
    assert data["psm_program_status"] in ("NOT_REQUIRED", "REQUIRED")
    assert isinstance(data["overdue_inspection_count"], int)
    assert isinstance(data["open_incident_count"], int)
    assert isinstance(data["expired_training_count"], int)
    assert isinstance(data["posture_score"], int)
    assert data["compliance_posture"] in ("COMPLIANT", "DEGRADED", "NONCOMPLIANT")


def assert_refrigeration_system(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["design_charge_lbs"], (int, float))
    assert isinstance(data["condenser_approach_f"], (int, float))
    assert isinstance(data["min_head_psig"], (int, float))
    assert isinstance(data["max_head_psig"], (int, float))
    assert isinstance(data["float_head_enabled"], bool)
    assert data.get("last_gauge_reading_lbs") is None or \
        isinstance(data["last_gauge_reading_lbs"], (int, float))
    assert data.get("last_gauge_reading_at") is None or \
        is_iso8601_timestamp(data["last_gauge_reading_at"])
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE", "DECOMMISSIONED")


def assert_equipment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("system_id", ""))
    assert isinstance(data["tag_number"], str) and len(data["tag_number"]) > 0
    assert data["equipment_type"] in ("VESSEL", "COMPRESSOR", "PIPING_CIRCUIT", "PRV")
    assert isinstance(data["inspection_interval_days"], int)
    assert data["inspection_interval_days"] > 0
    assert data["inspection_method"] in ("FIXED", "CONDITION_BASED")
    assert data.get("last_completed_at") is None or \
        is_iso8601_timestamp(data["last_completed_at"])
    assert data.get("last_result") in (None, "PASS", "FAIL")
    assert data.get("next_due_at") is None or is_iso8601_timestamp(data["next_due_at"])
    assert data["integrity_status"] in ("CURRENT", "DUE_SOON", "OVERDUE", "FAILED")


def assert_psid_document(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("system_id", ""))
    assert data["doc_type"] in ("PID", "PSV_CALC", "RELIEF_DESIGN")
    assert isinstance(data["revision_label"], str) and len(data["revision_label"]) > 0
    assert isinstance(data["content_uri"], str) and len(data["content_uri"]) > 0
    assert data["status"] in ("CURRENT", "UNDER_REVIEW", "SUPERSEDED")
    assert data.get("last_reaffirmed_at") is None or \
        is_iso8601_timestamp(data["last_reaffirmed_at"])


def assert_charge_adjustment(data: dict):
    """Append-only ledger entry: id + created_at only; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert is_valid_uuid(data.get("facility_id", ""))
    if data.get("system_id") is not None:
        assert is_valid_uuid(data["system_id"])
    assert data["adjustment_type"] in ("ADD", "REMOVE")
    assert isinstance(data["quantity_lbs"], (int, float))
    assert isinstance(data["rounded_lbs"], (int, float))
    assert_charge_precision(data["rounded_lbs"])
    assert isinstance(data["reason"], str)
    assert is_valid_uuid(data.get("posted_by_employee_id", ""))


def assert_inspection(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("equipment_id", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data["status"] in ("SCHEDULED", "OVERDUE", "COMPLETED")
    assert data.get("result") in (None, "PASS", "FAIL")
    assert data.get("completed_at") is None or \
        is_iso8601_timestamp(data["completed_at"])
    assert isinstance(data.get("completed_late", False), bool)


def assert_employee(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["employment_status"] in ("ACTIVE", "INACTIVE")


def assert_training_record(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data["topic"] in ("PSM_OVERVIEW", "AMMONIA_OPERATOR", "EMERGENCY_RESPONSE")
    assert is_iso8601_timestamp(data.get("completed_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["currency"] in ("CURRENT", "EXPIRING_SOON", "EXPIRED")


def assert_drill_event(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["drill_type"] in ("TABLETOP", "FIELD", "EVACUATION")
    assert is_iso8601_timestamp(data.get("scheduled_start_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end_at", ""))
    assert data["status"] in ("PLANNED", "CONDUCTED")
    assert data.get("attendee_employee_ids") is None or \
        isinstance(data["attendee_employee_ids"], list)
    assert data.get("conducted_at") is None or \
        is_iso8601_timestamp(data["conducted_at"])


def assert_incident(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    if data.get("equipment_id") is not None:
        assert is_valid_uuid(data["equipment_id"])
    assert data["severity"] in ("NEAR_MISS", "RECORDABLE", "REPORTABLE")
    assert isinstance(data["description"], str)
    assert data.get("reported_by_employee_id") is None or \
        is_valid_uuid(data["reported_by_employee_id"])
    assert data.get("investigator_employee_id") is None or \
        is_valid_uuid(data["investigator_employee_id"])
    assert data["status"] in (
        "REPORTED", "UNDER_INVESTIGATION", "ACTIONS_ASSIGNED", "CLOSED", "REOPENED")
    assert isinstance(data["pending_action_count"], int)
    assert isinstance(data["reopen_count"], int)
    assert data.get("source_leak_event_id") is None or \
        is_valid_uuid(data["source_leak_event_id"])


def assert_corrective_action(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("incident_id", ""))
    assert isinstance(data["description"], str)
    assert is_valid_uuid(data.get("assignee_employee_id", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data["status"] in ("OPEN", "COMPLETED", "VERIFIED")


def assert_compliance_audit(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert isinstance(data["lead_auditor"], str)
    assert data["origin"] in ("MANUAL", "AUTO_THRESHOLD")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CLOSED")


def assert_contractor(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["safety_score"], int)
    assert 0 <= data["safety_score"] <= 100
    assert data["qualification_status"] in ("PENDING", "QUALIFIED", "SUSPENDED", "EXPIRED")
    assert data.get("qualified_until") is None or \
        is_iso8601_timestamp(data["qualified_until"])


def assert_hot_work_permit(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("system_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert isinstance(data["work_description"], str)
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_until", ""))
    assert data["status"] in (
        "REQUESTED", "ISSUED", "IN_PROGRESS", "SUSPENDED", "CLOSED", "VOIDED",
        "EXPIRED")


def assert_leak_event(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("system_id", ""))
    assert isinstance(data["estimated_release_lbs"], (int, float))
    assert isinstance(data["source_description"], str)
    assert data["status"] in ("SUSPECTED", "CONFIRMED", "FALSE_ALARM")
    assert data.get("final_release_lbs") is None or \
        isinstance(data["final_release_lbs"], (int, float))
    assert data.get("confirmed_at") is None or \
        is_iso8601_timestamp(data["confirmed_at"])
    assert isinstance(data.get("notification_required", False), bool)
    assert data.get("notification_deadline_at") is None or \
        is_iso8601_timestamp(data["notification_deadline_at"])
    assert data["notification_status"] in (
        "NOT_REQUIRED", "PENDING", "OVERDUE", "NOTIFIED")
    assert data.get("notified_at") is None or \
        is_iso8601_timestamp(data["notified_at"])
    assert isinstance(data.get("late_notification", False), bool)
    assert data.get("auto_incident_id") is None or \
        is_valid_uuid(data["auto_incident_id"])


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_posture_band_consistent(data: dict):
    """compliance_posture must band posture_score: 0 COMPLIANT, 1..9 DEGRADED,
    >= 10 NONCOMPLIANT (PRD section 2.7)."""
    score = data["posture_score"]
    posture = data["compliance_posture"]
    if score == 0:
        assert posture == "COMPLIANT", f"score 0 must be COMPLIANT, got {posture}"
    elif score <= 9:
        assert posture == "DEGRADED", f"score {score} must be DEGRADED, got {posture}"
    else:
        assert posture == "NONCOMPLIANT", \
            f"score {score} must be NONCOMPLIANT, got {posture}"


def assert_charge_posture_consistent(data: dict):
    """charge_posture must track total_charge_lbs vs threshold_lbs (>=)."""
    if data["total_charge_lbs"] >= data["threshold_lbs"]:
        assert data["charge_posture"] == "AT_OR_ABOVE_THRESHOLD"
    else:
        assert data["charge_posture"] == "BELOW_THRESHOLD"
