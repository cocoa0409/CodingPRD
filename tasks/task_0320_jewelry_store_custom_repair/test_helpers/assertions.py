"""Entity assertions and domain invariant checkers.

Field names are exact PRD field names. Payment and CreditLedgerEntry are
append-only (PRD §2.4) so their assertions never demand version / updated_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields for full (non-append-only) resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def _assert_append_only(data: dict):
    """Common fields for append-only resources (PRD §2.4): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["phone"], str)
    assert isinstance(data["store_credit_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["title"], str)
    assert data["metal_karat"] in ("K14", "K18", "K24")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["latest_appraised_value_cents"] is None or isinstance(
        data["latest_appraised_value_cents"], int
    )
    assert data["status"] in ("IN_STOCK", "RESERVED", "SOLD", "IN_REPAIR")


def assert_workbench(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["status"] == "ACTIVE"


def assert_appraisal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("inventory_item_id", ""))
    assert isinstance(data["appraiser_name"], str) and len(data["appraiser_name"]) > 0
    assert isinstance(data["market_value_cents"], int) and data["market_value_cents"] > 0
    assert isinstance(data["replacement_value_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "VOID")
    assert data["document_number"] is None or isinstance(data["document_number"], str)


def assert_custom_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["estimated_materials_cents"], int)
    assert isinstance(data["design_fee_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in (
        "DRAFT", "QUOTED", "DEPOSIT_PAID", "IN_DESIGN", "DESIGN_REVIEW",
        "APPROVED", "IN_PRODUCTION", "READY", "COMPLETED", "CANCELLED",
    )


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["repair_kind"] in (
        "RESIZE", "STONE_RESET", "POLISH", "CLASP_REPAIR", "WARRANTY"
    )
    assert isinstance(data["parts_cents"], int) and data["parts_cents"] >= 0
    assert isinstance(data["labor_cents"], int) and data["labor_cents"] >= 0
    assert isinstance(data["rush_surcharge_cents"], int) and data["rush_surcharge_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["rush"], bool)
    assert data["status"] in (
        "INTAKE", "ASSESSED", "AWAITING_PARTS", "IN_REPAIR",
        "QC", "READY", "PICKED_UP", "CANCELLED",
    )


def assert_layaway_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("inventory_item_id", ""))
    assert isinstance(data["installment_count"], int)
    assert isinstance(data["paid_to_date_cents"], int)
    assert data["status"] in (
        "PENDING", "ACTIVE", "PAID_IN_FULL", "FULFILLED", "CANCELLED"
    )


def assert_trade_in_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["metal_karat"] in ("K14", "K18", "K24")
    assert data["condition"] in ("EXCELLENT", "GOOD", "FAIR")
    assert isinstance(data["metal_value_cents"], int)
    assert isinstance(data["buyback_credit_cents"], int)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED")


def assert_special_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["vendor_name"], str)
    assert isinstance(data["quoted_price_cents"], int) and data["quoted_price_cents"] > 0
    assert isinstance(data["deposit_required_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
    assert data["status"] in (
        "REQUESTED", "PLACED", "ARRIVED", "DELIVERED", "CANCELLED"
    )


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("inventory_item_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "RESOLVED")


def assert_payment(data: dict):
    _assert_append_only(data)
    assert data["target_type"] in ("CUSTOM_ORDER", "LAYAWAY", "SPECIAL_ORDER")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["outcome"] == "SUCCEEDED"
    # Append-only: must NOT expose version / updated_at.
    assert "version" not in data, "Payment is append-only and carries no version"
    assert "updated_at" not in data, "Payment is append-only and carries no updated_at"


def assert_ledger_entry(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["reason"] in ("TRADE_IN", "LAYAWAY_REFUND", "PURCHASE", "MANUAL_ADJUSTMENT")
    assert "version" not in data, "CreditLedgerEntry is append-only and carries no version"
    assert "updated_at" not in data, "CreditLedgerEntry is append-only and carries no updated_at"
