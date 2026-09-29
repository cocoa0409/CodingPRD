"""Entity assertions and domain invariant checkers for the allocation API."""
from typing import List, Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

PROGRAM_STATUSES = ["PLANNING", "ACTIVE", "LOCKED", "CLOSED"]
STORE_STATUSES = ["ACTIVE", "REMODEL", "CLOSING", "CLOSED"]
RECEIPT_STATUSES = ["STAGED", "ALLOCATING", "ALLOCATED", "CLOSED"]
RUN_STATUSES = ["DRAFT", "PROPOSED", "COMMITTED", "RECALLED", "CANCELLED"]
LINE_STATUSES = ["PENDING", "SHIPPED", "RECEIVED"]
STOCK_STATUSES = ["STOCKOUT", "LOW", "IN_STOCK", "OVERSTOCK"]
ASSORTMENT_STATUSES = ["EXITED", "COMPLETE", "SIZE_OUT_RISK", "BROKEN"]
TRANSFER_STATUSES = [
    "PROPOSED",
    "APPROVED",
    "REJECTED",
    "EXPIRED",
    "DISPATCHED",
    "RECEIVED",
    "CANCELLED",
]
ITEM_LIFECYCLE_STATES = [
    "ACTIVE",
    "SIZE_OUT_WATCH",
    "BROKEN",
    "CONSOLIDATION_PENDING",
    "MARKDOWN",
]
PROMO_STATUSES = ["DRAFT", "SCHEDULED", "ACTIVE", "ENDED", "CANCELLED"]
ACTION_STATUSES = ["PENDING", "EXECUTED", "CANCELLED", "SUPERSEDED"]
ITEM_CLASSES = ["APPAREL_TOP", "APPAREL_BOTTOM", "FOOTWEAR", "ACCESSORY"]


def assert_mutable_common_fields(data: dict):
    """Every mutable entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_common_fields(data: dict):
    """Append-only entities carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_size_array(size_array, field_name: str = "size array"):
    """Every size-keyed array is a list of {size_code, units} objects."""
    assert isinstance(size_array, list), f"{field_name} must be a list"
    for entry in size_array:
        assert isinstance(entry.get("size_code"), str) and entry["size_code"], (
            f"{field_name} entries need a size_code"
        )
        assert isinstance(entry.get("units"), int) and entry["units"] >= 0, (
            f"{field_name} entries need non-negative integer units"
        )


def assert_program(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in PROGRAM_STATUSES, f"unexpected status {data['status']!r}"
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert isinstance(data["banner_code"], str) and data["banner_code"]
    assert isinstance(data["transfer_min_ratio_bp"], int)
    assert data["scorecard_basis"] in ["SIMPLE_AVERAGE", "UNIT_WEIGHTED"]


def assert_store(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in STORE_STATUSES, f"unexpected status {data['status']!r}"
    assert data["grade"] in ["A", "B", "C", "D"], f"unexpected grade {data['grade']!r}"
    assert isinstance(data["grade_index_bp"], int)
    assert isinstance(data["cluster_code"], str) and data["cluster_code"]
    assert_cost_precision(data["freight_flat_usd"])
    assert isinstance(data["historical_sell_through_bp"], int)


def assert_fixture_plan(data: dict):
    assert_mutable_common_fields(data)
    assert data["item_class"] in ITEM_CLASSES
    assert is_iso8601_timestamp(data["effective_from"])
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 0
    assert data["capacity_units"] == (
        data["fixture_count"] * data["facings_per_fixture"] * data["units_per_facing"]
    ), "capacity_units must equal fixture_count x facings_per_fixture x units_per_facing"
    assert isinstance(data["presentation_min_units"], int)


def assert_size_profile(data: dict):
    """SizeProfile is append-only: no updated_at, no version."""
    assert_append_only_common_fields(data)
    assert data["item_class"] in ITEM_CLASSES
    assert isinstance(data["size_curve"], list) and data["size_curve"]
    total = 0
    for entry in data["size_curve"]:
        assert isinstance(entry["size_code"], str) and entry["size_code"]
        assert isinstance(entry["share_bp"], int) and entry["share_bp"] >= 1
        total += entry["share_bp"]
    assert total == 10000, f"share_bp values must sum to exactly 10000, got {total}"
    assert data["size_count"] == len(data["size_curve"])
    assert isinstance(data["core_size_count"], int)
    assert 0 <= data["core_size_count"] <= data["size_count"]


def assert_item(data: dict):
    assert_mutable_common_fields(data)
    assert data["item_class"] in ITEM_CLASSES
    assert data["item_type"] in ["BASIC", "SEASONAL", "FASHION"]
    assert data["replenishment_model"] in ["MIN_MAX", "DEMAND_DRIVEN", "PUSH"]
    assert data["lifecycle_state"] in ITEM_LIFECYCLE_STATES
    assert_cost_precision(data["unit_cost_usd"])
    assert_cost_precision(data["retail_price_usd"])
    assert isinstance(data["broken_store_count"], int)
    assert isinstance(data["size_out_store_count"], int)


def assert_store_position(data: dict):
    assert_mutable_common_fields(data)
    assert data["stock_status"] in STOCK_STATUSES
    assert data["assortment_status"] in ASSORTMENT_STATUSES
    assert_size_array(data["size_on_hand"], "size_on_hand")
    for field in (
        "on_hand_units",
        "on_order_units",
        "in_transit_units",
        "reserved_out_units",
        "min_units",
        "max_units",
        "weekly_forecast_units",
        "trailing_4wk_sales_units",
        "broken_size_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert data["available_units"] == data["on_hand_units"] - data["reserved_out_units"], (
        "available_units must equal on_hand_units minus reserved_out_units"
    )
    assert isinstance(data["consolidated_out"], bool)


def assert_receipt(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in RECEIPT_STATUSES
    assert_size_array(data["size_received"], "size_received")
    assert isinstance(data["units_received"], int) and data["units_received"] >= 1
    assert data["units_committed"] + data["units_unallocated"] == data["units_received"], (
        "units_committed plus units_unallocated must equal units_received"
    )


def assert_allocation_run(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in RUN_STATUSES
    assert data["method"] in ["MIN_MAX_TOPUP", "DEMAND_DRIVEN", "PUSH_SIZE_PROFILE"]
    assert data["need_basis"] in ["FORWARD_LOOKING", "HISTORICAL_SELL_THROUGH"]
    for field in (
        "units_proposed",
        "units_committed",
        "unallocated_remainder_units",
        "eligible_store_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_allocation_line(data: dict):
    assert_mutable_common_fields(data)
    assert data["fulfillment_status"] in LINE_STATUSES
    assert_size_array(data["size_breakdown"], "size_breakdown")
    for field in (
        "need_units",
        "units_proposed",
        "units_allocated",
        "capacity_capped_units",
        "presentation_gap_units",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert sum(e["units"] for e in data["size_breakdown"]) == data["units_proposed"], (
        "size_breakdown units must sum to units_proposed"
    )


def assert_promo_event(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in PROMO_STATUSES
    assert data["scope"] in ["PROGRAM", "CLUSTER", "STORE"]
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert isinstance(data["lift_factor_bp"], int) and data["lift_factor_bp"] >= 1


def assert_transfer_recommendation(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in TRANSFER_STATUSES
    assert data["source_reason"] in ["REBALANCE", "CONSOLIDATION"]
    assert data["from_store_id"] != data["to_store_id"], (
        "a recommendation may never move units from a store to itself"
    )
    assert_size_array(data["size_split"], "size_split")
    for money in ("freight_cost_usd", "handling_fee_usd", "landed_cost_usd", "benefit_usd"):
        assert_cost_precision(data[money])
    assert data["landed_cost_usd"] == round(
        data["freight_cost_usd"] + data["handling_fee_usd"], 2
    ), "landed_cost_usd must equal freight_cost_usd plus handling_fee_usd"
    assert isinstance(data["benefit_ratio_bp"], int)
    assert is_iso8601_timestamp(data["expires_at"])
    assert sum(e["units"] for e in data["size_split"]) == data["units"], (
        "size_split units must sum to the recommendation's units"
    )


def assert_assortment_action(data: dict):
    assert_mutable_common_fields(data)
    assert data["status"] in ACTION_STATUSES
    assert data["trigger_reason"] in ["SIZE_OUT", "BROKEN_ASSORTMENT"]
    assert data["action_type"] in ["CONSOLIDATION", "MARKDOWN"]
    assert is_iso8601_timestamp(data["detected_at"])
    if data["action_type"] == "MARKDOWN":
        assert data["consolidation_target_store_id"] is None, (
            "a MARKDOWN action leaves consolidation_target_store_id null"
        )
    assert isinstance(data["units_at_detection"], int)


def assert_performance_snapshot(data: dict):
    """PerformanceSnapshot is append-only: no updated_at, no version."""
    assert_append_only_common_fields(data)
    assert data["basis"] in ["SIMPLE_AVERAGE", "UNIT_WEIGHTED"]
    assert is_iso8601_timestamp(data["as_of_date"])
    for field in (
        "store_count",
        "included_position_count",
        "in_stock_pct_bp",
        "sell_through_pct_bp",
        "allocation_accuracy_bp",
    ):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_no_mutable_common_fields(data: dict):
    """Append-only entities must expose neither updated_at nor version."""
    assert "updated_at" not in data, (
        "an append-only entity must not expose updated_at"
    )
    assert "version" not in data, "an append-only entity must not expose version"


def assert_network_on_hand(positions: List[dict], expected_total: int):
    """Sum of on_hand_units across the supplied positions."""
    total = sum(p["on_hand_units"] for p in positions)
    assert total == expected_total, (
        f"network on-hand must be {expected_total}, got {total}"
    )


def assert_receipt_ledger_balances(receipt: dict, lines_committed_units: int):
    """The receipt ledger must reconcile to the committed line units."""
    assert receipt["units_committed"] == lines_committed_units, (
        f"units_committed {receipt['units_committed']} must equal the committed "
        f"line total {lines_committed_units}"
    )
    assert (
        receipt["units_committed"] + receipt["units_unallocated"]
        == receipt["units_received"]
    ), "the receipt ledger must never drift from units_received"
