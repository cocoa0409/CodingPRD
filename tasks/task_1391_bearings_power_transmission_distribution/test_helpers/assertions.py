"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from datetime import datetime
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp (with or without fractional digits / Z)."""
    if ts is None:
        raise AssertionError("timestamp must not be None")
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["description"], str)
    assert data["family"] in ["BEARING", "GEARBOX", "BELT", "CHAIN", "SEAL"]
    assert isinstance(data["list_price_cents"], int)
    assert data["status"] in ["ACTIVE", "PHASEOUT", "OBSOLETE"]
    assert "last_price_change_at" in data
    assert "superseded_by_id" in data


def assert_interchange_record(data: dict):
    # Immutable record: only id + created_at from the common set (PRD §2.4)
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "interchange record must not carry updated_at"
    assert "version" not in data, "interchange record must not carry version"
    assert isinstance(data["competitor_part_number"], str)
    assert isinstance(data["product_id"], str)
    assert data["interchange_class"] in ["EXACT", "DIMENSIONAL", "FUNCTIONAL"]
    assert isinstance(data["min_shaft_diameter_mm"], (int, float))
    assert isinstance(data["max_shaft_diameter_mm"], (int, float))
    assert isinstance(data["requires_engineering_review"], bool)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_status"] in ["GOOD", "HOLD"]
    assert isinstance(data["open_receivables_cents"], int)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["family"] in ["BEARING", "GEARBOX", "BELT", "CHAIN", "SEAL"]
    assert data["price_basis"] in ["LIST_LESS", "CONTRACT_FIXED"]
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]
    assert isinstance(data["lag_protection_days"], int)


def assert_branch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["timezone_offset_hours"], int)
    assert 0 <= data["business_open_hour"] <= 23
    assert 0 <= data["business_close_hour"] <= 23
    assert isinstance(data["expedite_cutoff_hour"], int)
    assert isinstance(data["after_hours_fee_cents"], int)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_branch_stock(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["branch_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert isinstance(data["factory_lead_time_days"], int)
    assert_stock_quantities_consistent(data)


def assert_stock_quantities_consistent(data: dict):
    """PRD §2.8: available_qty equals on_hand_qty minus reserved_qty."""
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty {data['available_qty']} != on_hand {data['on_hand_qty']} "
        f"- reserved {data['reserved_qty']}"
    )


def assert_price_file(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["new_list_price_cents"], int)
    assert is_iso8601_timestamp(data.get("effective_at", ""))
    assert isinstance(data.get("published_by"), str)
    assert data["status"] in ["PENDING", "EFFECTIVE", "SUPERSEDED", "CANCELLED"]


def assert_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["branch_id"], str)
    assert data["price_variant"] in ["ORDER_DATE", "SHIP_DATE"]
    assert data["fulfillment_status"] in [
        "DRAFT", "CONFIRMED", "FULLY_SOURCED", "PARTIALLY_SHIPPED",
        "SHIPPED", "CLOSED", "CANCELLED",
    ]
    assert data["billing_status"] in ["UNBILLED", "INVOICED", "PARTIALLY_PAID", "PAID"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["expedite_fees_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert_order_totals_consistent(data)


def assert_order_totals_consistent(data: dict):
    """PRD §3.4: total_cents is subtotal plus fees."""
    assert data["total_cents"] == data["subtotal_cents"] + data["expedite_fees_cents"], (
        f"total {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"+ fees {data['expedite_fees_cents']}"
    )


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["expedite_tier"] in ["NONE", "STANDARD", "RUSH", "EMERGENCY"]
    assert data["sourcing_status"] in [
        "PENDING_SOURCING", "STOCK_RESERVED", "FACTORY_ORDERED",
        "FACTORY_RECEIVED", "ALLOCATED", "SHIPPED", "CANCELLED",
    ]
    assert isinstance(data["expedite_fee_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["price_protection_applied"], bool)


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["branch_stock_id"], str)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in ["ACTIVE", "CONSUMED", "RELEASED", "EXPIRED", "PREEMPTED"]


def assert_call_out(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["branch_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["call_out_fee_cents"], int)
    assert isinstance(data["parts_amount_cents"], int)
    assert isinstance(data["total_charge_cents"], int)
    assert isinstance(data["preempted_reservation_ids"], list)
    assert data["status"] in [
        "REQUESTED", "DISPATCHED", "FULFILLED", "STOCK_UNAVAILABLE", "CANCELLED",
    ]


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["branch_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["consigned_qty"], int)
    assert isinstance(data["consumed_qty"], int)
    assert isinstance(data["remaining_qty"], int)
    assert isinstance(data["pinned_unit_price_cents"], int)
    assert data["billing_variant"] in ["CONSUMPTION_FIFO", "MONTHLY_SNAPSHOT"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert_agreement_quantities_consistent(data)


def assert_agreement_quantities_consistent(data: dict):
    """PRD §3.5: remaining_qty equals consigned_qty minus consumed_qty."""
    assert data["remaining_qty"] == data["consigned_qty"] - data["consumed_qty"], (
        f"remaining {data['remaining_qty']} != consigned {data['consigned_qty']} "
        f"- consumed {data['consumed_qty']}"
    )


def assert_consumption(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["offset_applied_cents"], int)
    assert data["status"] in ["REPORTED", "INVOICED", "DISPUTED", "CREDITED"]


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data.get("filed_by"), str)
    assert data["failure_mode"] in [
        "FATIGUE", "CONTAMINATION", "MISALIGNMENT", "LUBRICATION", "BRINELLING", "OTHER",
    ]
    assert isinstance(data["operating_hours"], int) and data["operating_hours"] >= 0
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["verdict"] in ["NONE", "CONFIRMED_DEFECT", "MISAPPLICATION", "WEAR_OUT"]
    assert isinstance(data["credit_amount_cents"], int)
    assert data["status"] in ["SUBMITTED", "UNDER_ANALYSIS", "APPROVED", "DENIED", "CREDIT_ISSUED"]


def assert_return_authorization(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["branch_id"], str)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["condition"] in ["SURPLUS", "OBSOLETE"]
    assert isinstance(data["original_unit_price_cents"], int)
    assert isinstance(data.get("requested_by"), str)
    assert isinstance(data["eligible_credit_cents"], int)
    assert isinstance(data["write_down_cents"], int)
    assert isinstance(data["offset_applied_cents"], int)
    assert isinstance(data["credit_memo_cents"], int)
    assert isinstance(data["received_qty"], int)
    assert data["status"] in [
        "REQUESTED", "APPROVED", "REJECTED", "RECEIVED", "CREDIT_ISSUED", "EXPIRED",
    ]


def assert_service_shop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capabilities"], list)
    assert isinstance(data["region"], str)
    assert isinstance(data["labor_rate_cents"], int)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["warranty_claim_id"], str)
    assert isinstance(data["service_shop_id"], str)
    assert isinstance(data["region"], str)
    assert isinstance(data["referral_fee_cents"], int)
    assert isinstance(data["declined_shop_ids"], list)
    assert data["status"] in ["OPEN", "ACCEPTED", "DECLINED", "COMPLETED"]


def assert_return_credit_conservation(data: dict):
    """PRD §3.8: eligible == write_down + offset_applied + credit_memo."""
    total = data["write_down_cents"] + data["offset_applied_cents"] + data["credit_memo_cents"]
    assert data["eligible_credit_cents"] == total, (
        f"conservation violated: eligible {data['eligible_credit_cents']} != "
        f"{data['write_down_cents']} + {data['offset_applied_cents']} + {data['credit_memo_cents']}"
    )
