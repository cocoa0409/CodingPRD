"""Entity assertions and domain invariant checkers.

These validate shape and PRD-declared invariants using the framework's generic
validators (is_valid_uuid, is_iso8601_timestamp) internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_CLASS_TYPES = ["CLASS_A", "CLASS_B", "CLASS_C", "TRAVEL_TRAILER", "FIFTH_WHEEL"]
_ACQUISITIONS = ["STOCK", "CONSIGNMENT", "TRADE_IN"]
_UNIT_STATUSES = ["AVAILABLE", "HELD", "SOLD", "CONSIGNMENT_RETURNED"]
_CREDIT_TIERS = ["PRIME", "STANDARD", "SUBPRIME"]
_SALE_STATUSES = ["DRAFT", "QUOTED", "PDI_PENDING", "WALKTHROUGH", "DELIVERED", "CANCELLED"]
_FINANCE_STATUSES = ["NONE", "CASH", "REQUESTED", "APPROVED", "DECLINED"]
_SO_STATUSES = ["OPEN", "IN_PROGRESS", "AWAITING_PARTS", "COMPLETED", "CANCELLED"]
_RES_STATUSES = ["RESERVED", "FULFILLED", "RELEASED"]
_PLAN_KINDS = ["FACTORY", "EXTENDED"]
_PLAN_STATUSES = ["ACTIVE", "EXHAUSTED", "CANCELLED"]
_APPT_KINDS = ["REPAIR", "PDI"]
_APPT_STATUSES = ["SCHEDULED", "CHECKED_IN", "CLOSED", "CANCELLED"]
_STORAGE_STATUSES = ["BOOKED", "ACTIVE", "RELEASED", "CANCELLED"]
_SEVERITIES = ["STOP_SALE", "ADVISORY"]
_CAMPAIGN_STATUSES = ["OPEN", "CLOSED"]
_REMEDY_STATUSES = ["PENDING", "CLEARED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_dealership(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["doc_fee_cents"], int) and data["doc_fee_cents"] >= 0
    assert isinstance(data["sales_tax_rate_bps"], int) and data["sales_tax_rate_bps"] >= 0
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert data["credit_tier"] in _CREDIT_TIERS


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) > 0
    assert isinstance(data["model_year"], int)
    assert data["class_type"] in _CLASS_TYPES
    assert data["acquisition"] in _ACQUISITIONS
    assert data["status"] in _UNIT_STATUSES
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["open_recall_count"], int) and data["open_recall_count"] >= 0


def assert_deal(data: dict):
    _assert_common(data)
    assert data["sale_status"] in _SALE_STATUSES
    assert data["finance_status"] in _FINANCE_STATUSES
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] >= 0
    assert isinstance(data["pdi_passed"], bool)


def assert_pdi_inspection(data: dict):
    _assert_common(data)
    assert data["result"] in ["PASS", "FAIL"]
    assert isinstance(data["defects_found"], int) and data["defects_found"] >= 0


def assert_service_bay(data: dict):
    _assert_common(data)
    assert data["bay_kind"] in ["REPAIR", "WASH_PDI"]
    assert isinstance(data["cleanup_buffer_minutes"], int) and data["cleanup_buffer_minutes"] >= 0


def assert_service_order(data: dict):
    _assert_common(data)
    assert data["status"] in _SO_STATUSES
    assert isinstance(data["is_warranty"], bool)
    assert isinstance(data["parts_subtotal_cents"], int) and data["parts_subtotal_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["covered_cents"], int) and data["covered_cents"] >= 0


def assert_part_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert isinstance(data["qty_reserved"], int) and data["qty_reserved"] >= 0
    assert isinstance(data["qty_available"], int) and data["qty_available"] >= 0
    # qty_available = qty_on_hand - qty_reserved, never negative (PRD §2.8).
    assert data["qty_available"] == data["qty_on_hand"] - data["qty_reserved"]


def assert_part_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in _RES_STATUSES
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0


def assert_warranty_plan(data: dict):
    _assert_common(data)
    assert data["plan_kind"] in _PLAN_KINDS
    assert data["status"] in _PLAN_STATUSES
    assert isinstance(data["coverage_cap_cents"], int) and data["coverage_cap_cents"] >= 0
    assert isinstance(data["consumed_cents"], int) and data["consumed_cents"] >= 0


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["appt_kind"] in _APPT_KINDS
    assert data["status"] in _APPT_STATUSES


def assert_storage_slot(data: dict):
    _assert_common(data)
    assert data["status"] in _STORAGE_STATUSES
    assert isinstance(data["winterized"], bool)
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0


def assert_recall_campaign(data: dict):
    _assert_common(data)
    assert data["severity"] in _SEVERITIES
    assert data["status"] in _CAMPAIGN_STATUSES


def assert_recall_remedy(data: dict):
    _assert_common(data)
    assert data["status"] in _REMEDY_STATUSES
