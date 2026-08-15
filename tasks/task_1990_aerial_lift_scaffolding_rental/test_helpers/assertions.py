"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
import re

from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _assert_common_fields(data: dict):
    """PRD §2.5: id (UUID), created_at / updated_at (ISO 8601), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}")


def _assert_iso_date(value, field):
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        f"{field} must be an ISO calendar date (YYYY-MM-DD), got {value!r}")


def assert_customer_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_equipment_class(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["class_code"], str) and data["class_code"]
    assert data["category"] in ("AERIAL_LIFT", "SCAFFOLD")
    assert isinstance(data["max_working_height_ft"], int) and data["max_working_height_ft"] > 0
    assert isinstance(data["min_rental_days"], int) and data["min_rental_days"] >= 1
    for rate in ("daily_rate_cents", "weekly_rate_cents", "monthly_rate_cents",
                 "replacement_value_cents"):
        assert isinstance(data[rate], int) and data[rate] >= 0, f"{rate} must be integer cents >= 0"


def assert_equipment_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("class_id", ""))
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["ansi_standard_ref"], str) and data["ansi_standard_ref"]
    assert data["status"] in ("AVAILABLE", "ON_RENT", "QUARANTINED", "LOST")
    _assert_iso_date(data.get("last_annual_inspection_date"), "last_annual_inspection_date")
    _assert_iso_date(data.get("next_inspection_due_date"), "next_inspection_due_date")


def assert_rental_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["jobsite_address"], str) and data["jobsite_address"]
    assert isinstance(data["damage_waiver_elected"], bool)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    for sub in ("rental_subtotal_cents", "logistics_subtotal_cents",
                "damage_subtotal_cents", "invoice_total_cents"):
        assert isinstance(data[sub], int), f"{sub} must be integer cents"
    if data["status"] == "CLOSED":
        assert is_iso8601_timestamp(data.get("closed_at", "")), (
            "closed_at must be stamped once the contract is CLOSED")
    else:
        assert data.get("closed_at") is None, "closed_at stays null until CLOSED"


def assert_rental_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("class_id", ""))
    assert data["status"] in ("RESERVED", "OUT_ON_RENT", "OFF_RENT", "RETURNED", "CANCELLED")
    _assert_iso_date(data.get("requested_start_date"), "requested_start_date")
    _assert_iso_date(data.get("requested_end_date"), "requested_end_date")
    assert isinstance(data["required_working_height_ft"], int) and data["required_working_height_ft"] > 0
    assert isinstance(data["segment_count"], int) and data["segment_count"] >= 0
    assert isinstance(data["accrued_charge_cents"], int) and data["accrued_charge_cents"] >= 0
    assert isinstance(data["provisional_charge_cents"], int)
    if data["status"] == "RETURNED":
        assert isinstance(data["final_charge_cents"], int)
    else:
        assert data.get("final_charge_cents") is None


def assert_delivery_trip(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert data["trip_type"] in ("DELIVERY", "PICKUP")
    assert data["status"] in ("SCHEDULED", "EN_ROUTE", "COMPLETED", "FAILED", "CANCELLED")
    assert isinstance(data["driver_id"], str) and data["driver_id"]
    assert is_iso8601_timestamp(data.get("planned_start_utc", ""))
    assert is_iso8601_timestamp(data.get("planned_end_utc", ""))
    assert isinstance(data["standby_minutes"], int) and data["standby_minutes"] >= 0
    assert isinstance(data["standby_charge_cents"], int) and data["standby_charge_cents"] >= 0
    assert isinstance(data["labor_charge_cents"], int) and data["labor_charge_cents"] >= 0
    if data["status"] == "COMPLETED":
        assert data["trip_fee_cents"] == 15000, "flat route fee is 15,000 cents per completed trip"
        assert is_iso8601_timestamp(data.get("completed_at", ""))


def assert_inspection_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["inspector_id"], str) and data["inspector_id"]
    _assert_iso_date(data.get("inspection_date"), "inspection_date")
    assert isinstance(data["ansi_standard_ref"], str) and data["ansi_standard_ref"]
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] in ("SUBMITTED", "CERTIFIED", "REJECTED")
    if data["status"] == "SUBMITTED":
        assert data.get("certified_by") is None
        assert data.get("certified_at") is None
    else:
        assert isinstance(data["certified_by"], str) and data["certified_by"]
        assert is_iso8601_timestamp(data.get("certified_at", ""))


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["claim_type"] in ("DAMAGE", "LOST", "STOLEN")
    assert isinstance(data["description"], str)
    assert data["status"] in ("OPEN", "ASSESSED", "CHARGED", "DISPUTED", "WAIVED")
    assert isinstance(data["reported_by"], str) and data["reported_by"]
    if data["status"] in ("CHARGED", "DISPUTED", "WAIVED"):
        assert isinstance(data["chargeback_cents"], int) and data["chargeback_cents"] >= 0
        assert isinstance(data["resolved_by"], str) and data["resolved_by"]


def assert_training_record(data: dict):
    """PRD §2.5: a training record carries only id + created_at — both
    updated_at and version are absent from it."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "training records carry no updated_at"
    assert "version" not in data, "training records carry no version"
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("class_id", ""))
    assert isinstance(data["trainee_name"], str) and data["trainee_name"]
    assert is_iso8601_timestamp(data.get("trained_at", ""))
    assert isinstance(data["trainer_id"], str) and data["trainer_id"]
    assert is_iso8601_timestamp(data.get("valid_until", ""))
    assert isinstance(data["is_valid"], bool)


def assert_invoice(data: dict):
    """PRD §3.9: invoice body carries contract_id, status, and four
    integer-cent figures."""
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    for field in ("rental_subtotal_cents", "logistics_subtotal_cents",
                  "damage_subtotal_cents", "invoice_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["invoice_total_cents"] == (
        data["rental_subtotal_cents"]
        + data["logistics_subtotal_cents"]
        + data["damage_subtotal_cents"]
    ), "invoice_total_cents must equal the sum of the three subtotals"
