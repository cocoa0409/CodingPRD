"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version, present on versioned entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["billing_email"], str)
    assert data["standing"] in ("GOOD", "HOLD")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["shift_start_minute"], int)
    assert isinstance(data["shift_end_minute"], int)
    assert data["shift_end_minute"] > data["shift_start_minute"]
    assert isinstance(data["certified_for_wells"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["address"], str)
    assert isinstance(data["county_code"], str)
    assert isinstance(data["service_minutes"], int)
    assert data["service_minutes"] >= 15
    assert data["compliance_status"] in ("UNKNOWN", "COMPLIANT", "CONDITIONAL", "NON_COMPLIANT")
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100


def assert_asset(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert data["asset_type"] in ("SEPTIC_TANK", "WELL")
    assert isinstance(data["capacity_gallons"], int)
    assert data["capacity_gallons"] > 0
    assert isinstance(data["install_year"], int)
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")


def assert_service_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["frequency_months"], int)
    assert 1 <= data["frequency_months"] <= 120
    assert isinstance(data["estimated_gallons"], int)
    assert data["estimated_gallons"] > 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert data["work_type"] in ("PUMPING", "INSPECTION", "EMERGENCY", "REPAIR")
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["window_start_minute"], int)
    assert isinstance(data["emergency_surcharge_applies"], bool)
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED"
    )
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID")
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["final_cost_cents"], int)
    assert isinstance(data["invoice_total_cents"], int)


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["technician_id"], str)
    assert isinstance(data["route_date"], str)
    assert data["status"] in ("OPEN", "LOCKED")
    assert isinstance(data["assigned_stop_count"], int)
    assert data["assigned_stop_count"] >= 0
    assert isinstance(data["booked_minutes"], int)
    assert data["booked_minutes"] >= 0
    assert isinstance(data["optimized_sequence"], list)


def assert_inspection_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert data.get("result") in (None, "PASS", "CONDITIONAL", "FAIL")
    assert isinstance(data["defect_count"], int)
    assert data["defect_count"] >= 0
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_permit_filing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["inspection_report_id"], str)
    assert isinstance(data["site_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["submission_count"], int)
    assert data["submission_count"] >= 0


def assert_repair_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["part_name"], str)
    assert isinstance(data["quantity"], int)
    assert data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] >= 0
    assert isinstance(data["tax_rate_bps"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_reminder(data: dict):
    """Reminder is an append-only event: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["site_id"], str)
    assert data["reminder_type"] in ("PUMP_DUE", "COMPLIANCE_OVERDUE")
    assert data["status"] in ("PENDING", "ACKNOWLEDGED", "DISMISSED")
