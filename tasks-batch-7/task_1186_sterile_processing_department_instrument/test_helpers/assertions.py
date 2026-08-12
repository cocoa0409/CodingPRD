"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Datetime values are compared as *instants* (parsed), never as raw strings:
the PRD pins the arithmetic of every deadline/expiry, but only
created_at/updated_at carry a mandated three-fractional-digit rendering, so
string equality on computed datetimes would over-constrain the serializer.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp ('Z' or offset, optional fractional digits)."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 timestamps denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_tray_template(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["specialty"], str)
    assert data["packaging_type"] in ("WRAPPED", "RIGID_CONTAINER")
    assert isinstance(data["instrument_requirements"], list)
    assert len(data["instrument_requirements"]) >= 1
    for line in data["instrument_requirements"]:
        assert isinstance(line["instrument_type"], str) and line["instrument_type"]
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1
    assert isinstance(data["assembly_minutes"], int)


def assert_tray(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("template_id", "")), "template_id must be a UUID"
    assert isinstance(data["label"], str) and data["label"]
    assert data["status"] in (
        "AWAITING_DECONTAMINATION", "IN_DECONTAMINATION", "DECONTAMINATED",
        "IN_ASSEMBLY", "ASSEMBLED", "IN_LOAD", "STERILE", "IN_USE",
        "QUARANTINED", "DISCARDED",
    )
    assert "current_load_id" in data
    assert "sterility_expires_at" in data
    assert "quarantine_reason" in data
    assert isinstance(data["cycles_completed"], int) and data["cycles_completed"] >= 0


def assert_assembly_verification(data: dict):
    """Immutable audit record (PRD §2.5): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "audit records carry no updated_at"
    assert "version" not in data, "audit records carry no version"
    assert is_valid_uuid(data.get("tray_id", "")), "tray_id must be a UUID"
    assert isinstance(data.get("technician_id"), str) and data["technician_id"]
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["instrument_type"], str)
        assert isinstance(line["counted_qty"], int) and line["counted_qty"] >= 0
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["mismatch_count"], int) and data["mismatch_count"] >= 0


def assert_instrument(data: dict):
    _assert_common(data)
    assert isinstance(data["instrument_type"], str) and data["instrument_type"]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["max_cycles"], int) and data["max_cycles"] >= 1
    assert isinstance(data["usage_cycles"], int) and data["usage_cycles"] >= 0
    assert isinstance(data["replacement_cost_cents"], int)
    assert data["replacement_cost_cents"] > 0
    assert data["criticality"] in ("ROUTINE", "CRITICAL")
    assert data["status"] in (
        "IN_SERVICE", "FLAGGED_FOR_REPAIR", "OUT_FOR_REPAIR", "RETIRED"
    )
    assert isinstance(data["repair_count"], int) and data["repair_count"] >= 0
    assert "assigned_tray_id" in data


def assert_repair_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    assert data["status"] in ("OPEN", "SENT", "CLOSED_FIXED", "CLOSED_CONDEMNED")
    if data["status"] in ("CLOSED_FIXED", "CLOSED_CONDEMNED"):
        assert data.get("outcome") in ("FIXED", "CONDEMNED")
        assert data.get("recommended_outcome") in ("FIXED", "CONDEMNED")
        assert isinstance(data.get("outcome_overridden"), bool)


def assert_sterilizer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["method"] in ("STEAM_GRAVITY", "STEAM_PREVAC", "LOW_TEMP_H2O2")
    assert isinstance(data["chamber_capacity"], int) and data["chamber_capacity"] >= 1
    assert isinstance(data["cycle_minutes"], int) and data["cycle_minutes"] >= 1
    assert 1 <= data["required_certification_level"] <= 3
    assert data["status"] in ("IDLE", "RUNNING")


def assert_sterilization_load(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sterilizer_id", "")), "sterilizer_id must be a UUID"
    assert isinstance(data.get("operator_id"), str) and data["operator_id"]
    assert is_iso8601_timestamp(data.get("planned_start_at", ""))
    assert data["status"] in (
        "LOADING", "RUNNING", "COMPLETED", "RELEASED",
        "FAILED_CYCLE", "FAILED_BI", "RECALLED", "ABORTED",
    )
    assert isinstance(data["tray_count"], int) and data["tray_count"] >= 0
    assert "total_chargeback_cents" in data
    if data["total_chargeback_cents"] is not None:
        assert isinstance(data["total_chargeback_cents"], int)


def assert_biological_indicator(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("load_id", "")), "load_id must be a UUID"
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert data["status"] in ("INCUBATING", "RESULT_RECORDED")
    assert data["result"] in ("PENDING", "NEGATIVE", "POSITIVE")
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"


def assert_or_case(data: dict):
    _assert_common(data)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["surgeon"], str)
    assert is_iso8601_timestamp(data.get("scheduled_start_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end_at", ""))
    assert data["priority"] in ("ELECTIVE", "URGENT", "EMERGENCY")
    assert data["status"] in (
        "SCHEDULED", "TRAYS_RESERVED", "AT_RISK",
        "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )


def assert_tray_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert is_valid_uuid(data.get("tray_id", "")), "tray_id must be a UUID"
    assert data["status"] in ("RESERVED", "USED", "RELEASED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("reserved_at", ""))


def assert_iuss_exception(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tray_id", "")), "tray_id must be a UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data["justification"], str) and len(data["justification"]) >= 20
    assert isinstance(data.get("logged_by_id"), str) and data["logged_by_id"]
    assert is_iso8601_timestamp(data.get("logged_at", ""))
    assert data["status"] in ("DOCUMENTED", "REVIEWED")


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert 1 <= data["certification_level"] <= 3
    assert isinstance(data["certified_methods"], list)
    assert len(data["certified_methods"]) >= 1
    for m in data["certified_methods"]:
        assert m in ("STEAM_GRAVITY", "STEAM_PREVAC", "LOW_TEMP_H2O2")
    assert is_iso8601_timestamp(data.get("certification_expires_at", ""))
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CERTIFICATION_EXPIRED")
    assert data["competency_score"] >= 0, "competency score floored at 0"
    assert data["competency_score_lifetime"] >= 0


def assert_loaner_set(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor"], str) and data["vendor"]
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data["tray_count"], int) and data["tray_count"] >= 1
    assert is_iso8601_timestamp(data.get("due_by", "")), "due_by must be ISO 8601"
    assert isinstance(data["received_late"], bool)
    assert data["status"] in (
        "BOOKED", "RECEIVED", "LATE_RECEIVED", "READY", "IN_USE", "RETURNED"
    )


def assert_competency_invariants(technician: dict):
    """Domain invariants that must hold for any technician read (PRD §3.8)."""
    assert 0 <= technician["competency_score"] <= 100
    assert 0 <= technician["competency_score_lifetime"] <= 100
    assert technician["competency_score_lifetime"] <= technician["competency_score"], (
        "lifetime counts every event at full weight, so it is lower-or-equal "
        "than the rolling score for identical history"
    )
