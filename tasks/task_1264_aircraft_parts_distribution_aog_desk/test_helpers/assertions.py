"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    """Primary business resources carry id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["priority_tier"] in ("STANDARD", "PRIORITY", "PLATINUM")
    assert isinstance(data["core_returns_settled_180d"], int)
    assert isinstance(data["core_returns_on_time_180d"], int)
    assert isinstance(data["warranty_fraud_flags"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_part(data: dict):
    _assert_common_fields(data, "PartMaster")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["rotable"], bool)
    assert data["hazmat_class"] in ("NONE", "CLASS_2", "CLASS_3", "CLASS_9")
    assert data["export_control_code"] in ("EAR99", "EAR9X610", "ITAR")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["core_value_cents"], int)
    assert isinstance(data["warranty_months"], int) and data["warranty_months"] > 0
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0


def assert_inventory_unit(data: dict):
    _assert_common_fields(data, "InventoryUnit")
    assert isinstance(data["part_id"], str)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["condition"] in ("NEW", "OVERHAULED", "SERVICEABLE", "AS_REMOVED")
    assert data["trace_doc_level"] in (
        "TRACE_MISSING", "TEARDOWN_REPORT", "FAA_8130", "EASA_FORM1", "DUAL_RELEASE",
    )
    assert data["status"] in (
        "AVAILABLE", "RESERVED", "ALLOCATED", "SHIPPED", "SOLD", "ON_LOAN",
        "UNDER_INSPECTION", "QUARANTINED", "SCRAPPED",
    )


def assert_aog_request(data: dict):
    _assert_common_fields(data, "AogRequest")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["aircraft_tail"], str)
    assert isinstance(data["airport_code"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["condition_acceptable"], list) and data["condition_acceptable"]
    assert data["min_trace_doc"] in (
        "TRACE_MISSING", "TEARDOWN_REPORT", "FAA_8130", "EASA_FORM1", "DUAL_RELEASE",
    )
    assert isinstance(data["escalated"], bool)
    assert data["status"] in (
        "OPEN", "QUOTED", "FULFILLING", "FULFILLED", "CLOSED", "CANCELLED",
    )


def assert_quote(data: dict):
    _assert_common_fields(data, "Quote")
    assert isinstance(data["aog_request_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["lines"], list) and data["lines"]
    assert isinstance(data["validity_hours"], int) and data["validity_hours"] >= 1
    assert data["freight_mode"] in ("STANDARD", "HOT_SHOT", "CHARTER")
    assert isinstance(data["distance_km"], int) and data["distance_km"] >= 1
    assert isinstance(data["chargeable_weight_kg"], int) and data["chargeable_weight_kg"] >= 1
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in (
        "DRAFT", "ISSUED", "ACCEPTED", "REJECTED", "EXPIRED", "CANCELLED",
    )
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["handling_fee_cents"], int)
    assert isinstance(data["tier_fee_cents"], int)
    assert isinstance(data["freight_cost_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["max_penalty_cents"], int)


def assert_sales_order(data: dict):
    _assert_common_fields(data, "SalesOrder")
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["fulfillment_status"] in (
        "PENDING_ALLOCATION", "ALLOCATED", "SHIPPED", "DELIVERED", "CLOSED",
    )
    assert data["compliance_status"] in (
        "PENDING_SCREENING", "CLEARED", "EXPORT_HELD", "BLOCKED",
    )
    assert data["payment_status"] in ("UNBILLED", "INVOICED", "PAID")
    assert isinstance(data["invoiced_cents"], int)


def assert_order_line(data: dict):
    _assert_common_fields(data, "OrderLine")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["part_id"], str)
    assert data["quantity"] == 1
    assert data["sale_type"] in ("OUTRIGHT", "EXCHANGE", "LOAN", "LEASE")
    assert data["condition_required"] in ("NEW", "OVERHAULED", "SERVICEABLE", "AS_REMOVED")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["allocation_status"] in ("PENDING", "ALLOCATED")


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert isinstance(data["order_id"], str)
    assert data["status"] in (
        "DRAFT", "TENDERED", "IN_TRANSIT", "DELIVERED", "EXCEPTION",
    )
    assert isinstance(data["freight_cost_cents"], int)


def assert_charter_slot(data: dict):
    _assert_common_fields(data, "CharterSlot")
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert isinstance(data["home_base"], str) and data["home_base"]
    assert data["status"] in ("OPEN", "BOOKED", "RELEASED")


def assert_core_return(data: dict):
    _assert_common_fields(data, "CoreReturn")
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["core_value_cents"], int)
    assert isinstance(data["days_overdue"], int) and data["days_overdue"] >= 0
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["penalty_retained_cents"], int)
    assert isinstance(data["forfeited_cents"], int)
    assert isinstance(data["penalty_waived_cents"], int)
    assert data["status"] in ("OPEN", "OVERDUE", "RECEIVED", "SETTLED")


def assert_loan_agreement(data: dict):
    _assert_common_fields(data, "LoanAgreement")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["unit_id"], str)
    assert data["loan_type"] in ("LOAN", "LEASE")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert isinstance(data["billed_cents"], int) and data["billed_cents"] >= 0
    assert data["status"] in (
        "ACTIVE", "OVERDUE", "RETURNED", "DAMAGE_REVIEW", "SETTLED",
    )


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["order_line_id"], str)
    assert data["fault_category"] in ("DOA", "PREMATURE_FAILURE", "COSMETIC")
    assert isinstance(data["months_in_service"], int) and data["months_in_service"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "APPROVED", "CREDIT_ISSUED", "REJECTED",
    )


def assert_return_authorization(data: dict):
    _assert_common_fields(data, "ReturnAuthorization")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["days_since_delivery"], int)
    assert isinstance(data["restock_fee_cents"], int)
    assert isinstance(data["credit_cents"], int)
    assert data["status"] in ("APPROVED", "RECEIVED", "SETTLED")


def assert_ledger_entry(data: dict):
    """Append-only entry: id + created_at present; updated_at/version absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "LedgerEntry.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only ledger entries must not expose updated_at"
    assert "version" not in data, "append-only ledger entries must not expose version"
    assert data["entry_type"] in (
        "INVOICE_DEBIT", "CORE_DEPOSIT_DEBIT", "FREIGHT_DEBIT", "LOAN_DEBIT",
        "LEASE_DEBIT", "CORE_REFUND_CREDIT", "WARRANTY_CREDIT", "RESTOCK_CREDIT",
        "WAIVER_CREDIT", "PAYMENT_CREDIT", "MANUAL_DEBIT", "MANUAL_CREDIT",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["reference_type"] in (
        "SALES_ORDER", "SHIPMENT", "CORE_RETURN", "LOAN_AGREEMENT",
        "WARRANTY_CLAIM", "RETURN_AUTH", "CUSTOMER",
    )
    assert isinstance(data["reference_id"], str) and data["reference_id"]


def assert_core_return_waterfall_invariant(data: dict):
    """PRD §3.6: at settlement the deposit equals refund + penalty retained + forfeiture."""
    assert data["core_value_cents"] == (
        data["refunded_cents"]
        + data["penalty_retained_cents"]
        + data["forfeited_cents"]
    ), (
        f"waterfall invariant broken: {data['core_value_cents']} != "
        f"{data['refunded_cents']} + {data['penalty_retained_cents']} + "
        f"{data['forfeited_cents']}"
    )
