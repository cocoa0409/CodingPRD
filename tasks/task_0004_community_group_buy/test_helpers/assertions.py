"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict, entity_label: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_minimal_fields(data: dict, entity_label: str = "entity"):
    """For common_fields: false entities (ConsolidationBatch, RiskAlert) — only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"


def assert_community(data: dict):
    _assert_common_fields(data, "Community")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["status"] in ("ACTIVE", "FROZEN")


def assert_group_leader(data: dict):
    _assert_common_fields(data, "GroupLeader")
    assert isinstance(data["community_id"], str)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["tier"], int) and 1 <= data["tier"] <= 3
    assert data["status"] in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED", "DEACTIVATED")
    # parent_leader_id may be null
    assert "parent_leader_id" in data
    assert isinstance(data.get("chronic_risk_score", 0), (int, float))
    assert isinstance(data.get("acute_risk_score", 0), (int, float))
    assert isinstance(data.get("collusion_audit_count", 0), int)
    assert isinstance(data.get("lifetime_settled_orders", 0), int)


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["community_id"], str)
    assert isinstance(data["display_name"], str)
    assert data["status"] in ("ACTIVE", "RISK_HOLD", "BLOCKED")
    assert isinstance(data.get("lifetime_completed_orders", 0), int)


def assert_supplier(data: dict):
    _assert_common_fields(data, "Supplier")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_warehouse(data: dict):
    _assert_common_fields(data, "Warehouse")
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["region_code"], str)
    assert isinstance(data["cold_chain_capable"], bool)
    assert isinstance(data["handling_periods"], int) and data["handling_periods"] >= 1
    assert isinstance(data["cold_handling_periods"], int) and data["cold_handling_periods"] >= 1
    assert data["status"] in ("ACTIVE", "DISABLED")


def assert_flash_campaign(data: dict):
    _assert_common_fields(data, "FlashCampaign")
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["sku"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["total_stock"], int) and data["total_stock"] > 0
    assert isinstance(data["locked_units"], int)
    assert isinstance(data["allocated_units"], int)
    assert isinstance(data["remaining_units"], int)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "EXHAUSTED")
    # Inventory invariant
    assert data["locked_units"] + data["allocated_units"] + data["remaining_units"] == data["total_stock"], (
        f"flash inventory: {data['locked_units']}+{data['allocated_units']}+{data['remaining_units']} != {data['total_stock']}"
    )


def assert_group_buy_campaign(data: dict):
    _assert_common_fields(data, "GroupBuyCampaign")
    assert isinstance(data["leader_id"], str)
    assert isinstance(data["community_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["sku"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["discount_tiers"], list)
    assert isinstance(data["opens_at_period"], int)
    assert isinstance(data["deadline_period"], int)
    assert data["status"] in ("FORMING", "EXTENDED", "SUCCEEDED", "FAILED", "CLOSED")
    assert isinstance(data["participant_count"], int) and data["participant_count"] >= 0
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= 1


def assert_order(data: dict):
    _assert_common_fields(data, "Order")
    assert data["campaign_kind"] in ("GROUP_BUY", "FLASH")
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["line_items"], list) and len(data["line_items"]) > 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert data["payment_status"] in (
        "PENDING_PAY", "PAID", "SETTLED", "REFUND_PENDING",
        "REFUNDED", "PARTIALLY_REFUNDED",
    )
    assert data["fulfillment_status"] in (
        "NOT_PLANNED", "PLANNED", "DISPATCHED", "AT_PICKUP",
        "PICKED_UP", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data.get("refunded_amount_cents", 0), int)


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["warehouse_id"], str)
    assert isinstance(data["pickup_point_id"], str)
    assert isinstance(data["line_units"], list)
    assert isinstance(data["cold_chain_segment"], bool)
    assert data["status"] in (
        "PLANNED", "DISPATCHED", "AT_PICKUP", "MIS_PICK",
        "RECONCILED", "DELIVERED", "CANCELLED",
    )


def assert_pickup_point(data: dict):
    _assert_common_fields(data, "PickupPoint")
    assert isinstance(data["community_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["capacity_packages"], int) and data["capacity_packages"] >= 1
    assert isinstance(data["cold_storage_capable"], bool)
    assert isinstance(data["held_package_count"], int) and data["held_package_count"] >= 0
    assert data["status"] in ("ACTIVE", "DISABLED")


def assert_consolidation_batch(data: dict):
    _assert_minimal_fields(data, "ConsolidationBatch")
    assert "updated_at" not in data, "ConsolidationBatch must NOT expose updated_at"
    assert "version" not in data, "ConsolidationBatch must NOT expose version"
    assert isinstance(data["pickup_point_id"], str)
    assert isinstance(data["window_start_period"], int)
    assert isinstance(data["window_end_period"], int)
    assert data["window_end_period"] >= data["window_start_period"]
    assert isinstance(data["shipment_ids"], list)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_after_sales_case(data: dict):
    _assert_common_fields(data, "AfterSalesCase")
    assert isinstance(data["order_id"], str)
    assert data["case_type"] in ("REFUND_ONLY", "RETURN_AND_REFUND", "PARTIAL_COMPENSATION")
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "ARBITRATION",
        "RESOLVED_REFUND_ONLY", "RESOLVED_RETURN_REFUND",
        "RESOLVED_PARTIAL_COMPENSATION", "REJECTED",
    )
    assert isinstance(data["evidence_round"], int) and 0 <= data["evidence_round"] <= 2


def assert_commission_entry(data: dict):
    _assert_common_fields(data, "CommissionEntry")
    assert isinstance(data["leader_id"], str)
    assert isinstance(data["order_id"], str)
    assert data["leader_role"] in ("PRIMARY", "SECONDARY", "UPSTREAM")
    assert isinstance(data["gross_rebate_cents"], int) and data["gross_rebate_cents"] >= 0
    assert isinstance(data["tax_withholding_cents"], int) and data["tax_withholding_cents"] >= 0
    assert isinstance(data["net_rebate_cents"], int)
    assert isinstance(data["payout_target_period_index"], int)
    assert data["status"] in ("PENDING", "SETTLED", "PENDING_CLAWBACK", "CLAWED_BACK")


def assert_payout(data: dict):
    _assert_common_fields(data, "Payout")
    assert isinstance(data["leader_id"], str)
    assert isinstance(data["target_period_index"], int)
    assert isinstance(data["bundled_entry_ids"], list)
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "MATURED", "RELEASED", "CANCELLED")


def assert_risk_alert(data: dict):
    _assert_minimal_fields(data, "RiskAlert")
    assert "updated_at" not in data, "RiskAlert must NOT expose updated_at"
    assert "version" not in data, "RiskAlert must NOT expose version"
    assert data["alert_type"] in ("BOT_ORDER", "FAKE_GROUP_BUY", "LEADER_SUPPLIER_COLLUSION")
    assert data["target_kind"] in ("CUSTOMER", "GROUP_LEADER", "SUPPLIER", "ORDER")
    assert isinstance(data["target_id"], str)
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "CONFIRMED", "DISMISSED")


def assert_pickup_summary(data: dict):
    assert isinstance(data["held_package_count"], int) and data["held_package_count"] >= 0
    assert isinstance(data["capacity_packages"], int) and data["capacity_packages"] >= 1
    assert isinstance(data["load_factor"], (int, float))
    assert data["load_state"] in ("HEALTHY", "ELEVATED", "FULL")


def assert_flash_inventory_invariant(fc: dict):
    """locked + allocated + remaining == total_stock"""
    total = fc["locked_units"] + fc["allocated_units"] + fc["remaining_units"]
    assert total == fc["total_stock"], (
        f"flash inventory invariant violated: "
        f"{fc['locked_units']}+{fc['allocated_units']}+{fc['remaining_units']} = {total} != total_stock={fc['total_stock']}"
    )
