"""Entity assertions and domain invariant checkers for the EVS API."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value):
    """Parse an ISO 8601 timestamp string to an aware datetime (UTC)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual, expected):
    """Assert two ISO 8601 timestamps denote the same instant.

    PRD §2.4 fixes *which instants* the server stamps and §2.2/§2.5 fix the
    three-fractional-digit output format; this helper compares the instant
    itself so the assertion is about the PRD rule, not a serialization guess.
    """
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(
        data.get("version"), int
    ), f"{label}.version must be an integer"


def _assert_append_only(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_unit(data: dict):
    _assert_common(data, "Unit")
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["outbreak_posture"] in ("NORMAL", "OUTBREAK")
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0


def assert_bed(data: dict):
    _assert_common(data, "Bed")
    assert is_valid_uuid(data.get("unit_id", "")), "Bed.unit_id must be a UUID"
    assert isinstance(data["bed_code"], str) and data["bed_code"]
    assert data["bed_kind"] in ("STANDARD", "ISOLATION", "ICU")
    assert data["bed_status"] in (
        "VACANT_DIRTY",
        "CLEAN_IN_PROGRESS",
        "AWAITING_VERIFICATION",
        "READY",
        "OCCUPIED",
        "OUT_OF_SERVICE",
    )


def assert_placement_demand(data: dict):
    _assert_common(data, "PlacementDemand")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["required_bed_kind"] in ("STANDARD", "ISOLATION", "ICU")
    assert data["urgency_tier"] in ("STAT", "URGENT", "STANDARD")
    assert is_iso8601_timestamp(data.get("needed_by", ""))
    assert data["status"] in ("OPEN", "MATCHED", "FULFILLED", "EXPIRED", "CANCELLED")


def assert_clean_request(data: dict):
    _assert_common(data, "CleanRequest")
    assert is_valid_uuid(data.get("bed_id", ""))
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["clean_type"] in ("ROUTINE", "ISOLATION", "TERMINAL")
    assert data["status"] in (
        "QUEUED",
        "ASSIGNED",
        "IN_PROGRESS",
        "PENDING_QA",
        "NEEDS_RECLEAN",
        "VERIFIED",
        "CANCELLED",
    )
    assert data["priority_tier"] in ("STAT", "URGENT", "STANDARD")
    assert isinstance(data["sla_target_minutes"], int)
    assert data["sla_target_minutes"] > 0
    assert is_iso8601_timestamp(data.get("sla_due_at", ""))
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["pinned_base_minutes"], int)
    assert isinstance(data["pinned_outbreak_multiplier_bps"], int)
    assert isinstance(data["pinned_with_outbreak"], bool)
    assert isinstance(data["reclean_count"], int) and data["reclean_count"] >= 0
    assert isinstance(data["supply_reserved"], bool)


def assert_staff_member(data: dict):
    _assert_common(data, "StaffMember")
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) > 0
    assert all(c in ("CLEAN", "AUDIT") for c in data["capabilities"])
    assert isinstance(data["certifications"], list)
    assert all(c in ("ISO_CERT", "TERMINAL_CERT") for c in data["certifications"])
    assert data["shift_status"] in ("OFF_SHIFT", "ON_SHIFT", "ON_BREAK")
    assert isinstance(data["active_clean_count"], int)
    assert isinstance(data["completed_clean_count"], int)
    assert isinstance(data["qa_fail_count"], int)
    assert isinstance(data["shift_seconds_today"], int)
    assert isinstance(data["stat_eligible"], bool)


def assert_quality_audit(data: dict):
    _assert_common(data, "QualityAudit")
    assert is_valid_uuid(data.get("clean_request_id", ""))
    assert is_valid_uuid(data.get("auditor_id", ""))
    assert data["audit_method"] in ("ATP_SWAB", "FLUORESCENT_MARKER")
    assert data["result"] in ("PASS", "FAIL")
    assert data["audit_status"] in ("SUBMITTED", "VOIDED")
    assert isinstance(data["created_ops_run_index"], int)


def assert_supply_item(data: dict):
    _assert_common(data, "SupplyItem")
    assert data["item_code"] in ("DISINFECTANT", "PPE_PACK", "CLOTH", "SEALANT")
    assert isinstance(data["on_hand_quantity"], int)
    assert isinstance(data["reserved_quantity"], int)
    assert isinstance(data["reorder_threshold"], int)
    assert data["stock_status"] in ("LOW", "STOCKED")


def assert_supply_ledger_entry(data: dict):
    _assert_append_only(data, "SupplyLedgerEntry")
    assert is_valid_uuid(data.get("supply_item_id", ""))
    assert data["entry_type"] in ("RESTOCK", "CONSUME", "RECOUNT_ADJUSTMENT")
    assert isinstance(data["quantity_delta"], int)


def assert_outbreak_event(data: dict):
    _assert_common(data, "OutbreakEvent")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["pathogen_class"] in ("C_DIFF", "MRSA", "NOROVIRUS", "OTHER")
    assert data["status"] in ("DECLARED", "ACTIVE", "LIFTED", "CANCELLED")


def assert_bed_ready_notification(data: dict):
    _assert_common(data, "BedReadyNotification")
    assert is_valid_uuid(data.get("bed_id", ""))
    assert is_valid_uuid(data.get("demand_id", ""))
    assert data["status"] in ("SENT", "ACKNOWLEDGED", "RETRACTED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("sent_at", ""))


def assert_maintenance_window(data: dict):
    _assert_common(data, "MaintenanceWindow")
    assert is_valid_uuid(data.get("bed_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in ("SCHEDULED", "ACTIVE", "CLOSED", "CANCELLED")


def assert_clean_standard(data: dict):
    _assert_common(data, "CleanStandard")
    assert data["clean_type"] in ("ROUTINE", "ISOLATION", "TERMINAL")
    assert isinstance(data["base_minutes"], int) and data["base_minutes"] > 0
    assert isinstance(data["outbreak_multiplier_bps"], int)
    assert data["outbreak_multiplier_bps"] >= 10000
    assert isinstance(data["atp_rlu_threshold"], int)
    assert data["atp_rlu_threshold"] > 0


def assert_turnaround_snapshot(data: dict):
    _assert_append_only(data, "TurnaroundSnapshot")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data["verified_count"], int) and data["verified_count"] >= 0
    assert isinstance(data["sla_breach_count"], int) and data["sla_breach_count"] >= 0
