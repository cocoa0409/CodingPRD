"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. CallEvent is append-only: it must NOT
expose updated_at or version (PRD common-resource-properties section).
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso8601_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    The PRD pins the *instant* a server-assigned or request-echoed timestamp
    denotes (e.g. received_at is stamped from the logical clock), while the
    three-fractional-digit string format is required only for created_at /
    updated_at / api_request_timestamp. Tests therefore compare instants
    through this parser rather than raw strings.
    """
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_fleet_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert isinstance(data["per_call_authorization_limit_cents"], int)
    assert isinstance(data["monthly_spend_cap_cents"], int)
    assert isinstance(data["payment_terms_days"], int)
    assert isinstance(data["month_to_date_spend_cents"], int)
    assert data["effective_discount_tier"] in ("STANDARD", "GOLD", "PLATINUM")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data["suspension_reason"] in ("NONE", "ADMIN", "CREDIT_HOLD")


def assert_rate_card(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    for field in ("labor_rate_standard_cents", "labor_rate_master_cents",
                  "after_hours_multiplier_bp", "travel_free_miles",
                  "travel_per_mile_cents", "travel_time_per_minute_cents",
                  "emergency_callout_fee_cents", "parts_tax_rate_bp"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["year"], int)
    assert isinstance(data["odometer_miles"], int)
    assert data["roadworthiness"] in ("ROADWORTHY", "OUT_OF_SERVICE")


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["certifications"], list)
    assert data["labor_rate_class"] in ("STANDARD", "MASTER")
    assert data["status"] in ("OFF_DUTY", "AVAILABLE", "ON_BREAK", "ON_DISPATCH")


def assert_service_call(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["caller_name"], str) and data["caller_name"]
    assert isinstance(data["caller_phone"], str) and data["caller_phone"]
    assert isinstance(data["breakdown_location_text"], str)
    assert isinstance(data["distance_miles_from_depot"], int)
    assert data["symptom_category"] in (
        "ENGINE_NO_START", "OVERHEAT", "BRAKE_FAULT", "AIR_LEAK", "ELECTRICAL",
        "LIGHTING", "TIRE_BLOWOUT", "HVAC_ISSUE", "OTHER")
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["after_hours"], bool)
    assert data["status"] in (
        "RECEIVED", "TRIAGED", "DISPATCHED", "EN_ROUTE", "ON_SITE", "DIAGNOSED",
        "REPAIR_IN_PROGRESS", "REPAIR_COMPLETED", "TOW_IN_PROGRESS", "TOWED",
        "INVOICED", "CLOSED", "REOPENED", "CANCELLED")
    assert data["resolution_path"] in ("PENDING", "ON_SITE_REPAIR", "TOW_REQUIRED")
    assert data["hold_reason"] in ("NONE", "FLEET_CREDIT_HOLD")
    assert isinstance(data["is_comeback"], bool)
    assert isinstance(data["reopened_count"], int)


def assert_dispatch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_call_id"], str)
    assert isinstance(data["technician_id"], str)
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert isinstance(data["planned_travel_miles"], int)
    assert data["status"] in (
        "PROPOSED", "ACCEPTED", "REJECTED", "EN_ROUTE", "ON_SITE", "COMPLETED",
        "RELEASED", "EXPIRED", "SUPERSEDED")


def assert_van_stock_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["technician_id"], str)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["part_class"] in (
        "ENGINE", "COOLING", "BRAKE", "AIR_SYSTEM", "ELECTRICAL", "LIGHTING",
        "TIRE", "HVAC", "FILTERS")
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["unit_retail_cents"], int)
    assert isinstance(data["reorder_point"], int)
    assert isinstance(data["restock_pending"], bool)


def assert_work_estimate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_call_id"], str)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["requires_fleet_approval"], bool)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "EXPIRED")


def assert_part_usage(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_call_id"], str)
    assert isinstance(data["van_stock_item_id"], str)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["charge_type"] in ("CUSTOMER_PAY", "SHOP_GUARANTEE")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["line_total_cents"] == data["qty"] * data["unit_price_cents"], (
        "line_total_cents must be the exact integer-cent product of qty and "
        "unit price")
    assert data["status"] in ("POSTED", "RETURNED")
    assert is_iso8601_timestamp(data["posted_at"])


def assert_tow_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_call_id"], str)
    assert isinstance(data["tow_provider_name"], str)
    assert isinstance(data["tow_unit_id"], str)
    assert is_iso8601_timestamp(data["pickup_window_start_at"])
    assert is_iso8601_timestamp(data["pickup_window_end_at"])
    assert isinstance(data["tow_fee_cents"], int)
    assert data["status"] in ("REQUESTED", "HOOKED", "DELIVERED", "CANCELLED")


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_call_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert data["claim_type"] in (
        "OEM_BASE", "OEM_POWERTRAIN", "EXTENDED_SERVICE_CONTRACT")
    assert isinstance(data["oem_value_cents"], int)
    assert isinstance(data["appeal_count"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "DENIED", "APPEALED", "SETTLED")


def assert_inspection_defect(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert data["source"] in (
        "ROADSIDE_DOT_INSPECTION", "ANNUAL_INSPECTION", "DRIVER_REPORT")
    assert isinstance(data["defect_code"], str) and data["defect_code"]
    assert data["severity"] in ("OOS", "NON_OOS")
    assert is_iso8601_timestamp(data["discovered_at"])
    assert is_iso8601_timestamp(data["correction_deadline_at"])
    assert data["status"] in (
        "OPEN", "REPAIR_SCHEDULED", "CORRECTED", "VERIFIED",
        "VERIFICATION_FAILED", "ESCALATED")
    assert isinstance(data["escalation_count"], int)


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_call_id"], str)
    assert isinstance(data["invoice_number"], str) and \
        data["invoice_number"].startswith("INV-")
    assert data["issue_status"] in ("DRAFT", "ISSUED", "VOID")
    assert data["payment_status"] in (
        "UNPAID", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF")
    for field in ("labor_amount_cents", "travel_miles_billable",
                  "travel_amount_cents", "travel_time_amount_cents",
                  "callout_fee_cents", "parts_subtotal_cents",
                  "tow_charge_cents", "discount_cents", "tax_cents",
                  "warranty_offset_cents", "total_cents", "amount_paid_cents",
                  "outstanding_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["discount_tier"] in ("STANDARD", "GOLD", "PLATINUM")
    assert data["outstanding_cents"] == data["total_cents"] - data["amount_paid_cents"], (
        "outstanding_cents must equal total_cents minus amount_paid_cents")
    assert data["total_cents"] >= 0


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["method"] in ("CHECK", "CARD", "ACH", "FLEET_ACCOUNT")
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["allocation_json"], dict)
    assert data["status"] in ("POSTED", "VOID")


def assert_repeat_failure_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["original_service_call_id"], str)
    assert isinstance(data["new_service_call_id"], str)
    assert isinstance(data["window_days"], int)
    assert isinstance(data["miles_since_repair"], int)
    assert data["charge_policy"] in ("NO_CHARGE", "REDUCED", "FULL")
    assert data["status"] in (
        "OPEN", "UNDER_REVIEW", "CONFIRMED_COMEBACK", "REJECTED", "RESOLVED")


def assert_restock_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["van_stock_item_id"], str)
    assert isinstance(data["technician_id"], str)
    assert data["source"] in ("AUTO_LOW_STOCK", "MANUAL")
    assert isinstance(data["qty_requested"], int) and data["qty_requested"] >= 1
    assert data["status"] in ("PENDING", "APPROVED", "FULFILLED", "REJECTED")


def assert_call_event(data: dict):
    """CallEvent is append-only: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data["service_call_id"], str)
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert "updated_at" not in data, "append-only events must not expose updated_at"
    assert "version" not in data, "append-only events must not expose version"
