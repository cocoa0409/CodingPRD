"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_owner(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["phone"], str)
    assert isinstance(data["approval_cap_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["version"], int)


def assert_aircraft(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("owner_id", "")), "owner_id must be valid UUID"
    assert isinstance(data["tail_number"], str) and len(data["tail_number"]) > 0
    assert isinstance(data["make_model"], str)
    assert isinstance(data["total_time_hours"], (int, float))
    assert data["airworthiness_posture"] in ("AIRWORTHY", "RESTRICTED", "GROUNDED")
    assert isinstance(data["version"], int)


def assert_mechanic(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["certificate_number"], str) and len(data["certificate_number"]) > 0
    assert data["certificate_class"] in ("AP", "IA")
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["version"], int)


def assert_hangar_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["hangar_code"], str) and len(data["hangar_code"]) > 0
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be valid UUID"
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert isinstance(data["daily_rate_cents"], int)
    assert data["status"] in ("RESERVED", "OCCUPIED", "RELEASED", "CANCELLED")
    assert isinstance(data["version"], int)


def assert_work_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be valid UUID"
    assert is_valid_uuid(data.get("hangar_slot_id", "")), "hangar_slot_id must be valid UUID"
    assert is_valid_uuid(data.get("opened_by_mechanic_id", "")), (
        "opened_by_mechanic_id must be valid UUID"
    )
    assert data["scope_type"] in ("ANNUAL", "HUNDRED_HOUR", "UNSCHEDULED")
    assert data["pricing_mode"] in ("HOURLY", "FLAT_RATE")
    assert data["status"] in (
        "DRAFT",
        "SCHEDULED",
        "IN_PROGRESS",
        "INSPECTION_COMPLETE",
        "AWAITING_OWNER_APPROVAL",
        "APPROVED",
        "WORK_IN_PROGRESS",
        "READY_FOR_RTS",
        "RETURNED_TO_SERVICE",
        "CLOSED",
        "CANCELLED",
    )
    assert isinstance(data["open_discrepancy_count"], int)
    assert isinstance(data["verified_discrepancy_count"], int)
    assert isinstance(data["labor_hours_tenths"], int)
    assert isinstance(data["version"], int)


def assert_checklist_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ChecklistItem must not carry updated_at"
    assert "version" not in data, "ChecklistItem must not carry version"
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be valid UUID"
    assert isinstance(data["item_code"], str) and len(data["item_code"]) > 0
    assert isinstance(data["description"], str)
    assert isinstance(data["flat_rate_cents"], int)
    assert data["result"] in ("PENDING", "PASS", "FAIL", "NA")


def assert_discrepancy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be valid UUID"
    assert isinstance(data["description"], str)
    assert data["severity"] in ("AIRWORTHINESS", "NON_AIRWORTHINESS")
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in (
        "OPEN",
        "PENDING_OWNER_DECISION",
        "APPROVED",
        "DEFERRED",
        "REJECTED",
        "RECTIFIED",
        "VERIFIED",
    )
    assert isinstance(data["requires_owner_decision"], bool)
    assert isinstance(data["version"], int)


def assert_directive(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be valid UUID"
    assert data["directive_type"] in ("AD", "SB")
    assert isinstance(data["reference_number"], str) and len(data["reference_number"]) > 0
    assert isinstance(data["description"], str)
    assert data["compliance_status"] in (
        "PENDING_EVALUATION",
        "APPLICABLE_OPEN",
        "COMPLIED",
        "NOT_APPLICABLE",
    )
    assert isinstance(data["version"], int)


def assert_part(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("discrepancy_id", "")), "discrepancy_id must be valid UUID"
    assert isinstance(data["part_number"], str) and len(data["part_number"]) > 0
    assert data["condition"] in ("NEW", "OVERHAUL", "SERVICEABLE")
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("REQUESTED", "SOURCED", "RECEIVED", "INSTALLED", "RETURNED")
    assert isinstance(data["version"], int)


def assert_labor_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "LaborEntry must not carry updated_at"
    assert "version" not in data, "LaborEntry must not carry version"
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be valid UUID"
    assert is_valid_uuid(data.get("mechanic_id", "")), "mechanic_id must be valid UUID"
    assert isinstance(data["duration_tenths"], int)
    assert isinstance(data["notes"], str)
    assert data["status"] in ("POSTED", "VOIDED")


def assert_logbook_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "LogbookEntry must not carry updated_at"
    assert "version" not in data, "LogbookEntry must not carry version"
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be valid UUID"
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be valid UUID"
    assert data["entry_type"] in ("INSPECTION_SIGNOFF", "REPAIR_RECORD", "RTS_STATEMENT")
    assert isinstance(data["narrative"], str)
    assert is_valid_uuid(data.get("signed_by_mechanic_id", "")), (
        "signed_by_mechanic_id must be valid UUID"
    )
    assert is_iso8601_timestamp(data.get("signed_at", "")), "signed_at must be ISO 8601"


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be valid UUID"
    for field in (
        "labor_charge_cents",
        "parts_charge_cents",
        "shop_supplies_cents",
        "hangar_fee_cents",
        "tax_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be int cents"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOIDED")
    assert isinstance(data["version"], int)
