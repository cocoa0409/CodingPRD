"""Entity shape assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentStatus,
    CancelReasonCode,
    CarrierPickupStatus,
    EligibilityScoreBasis,
    NodeAction,
    NodeStatus,
    NotificationChannel,
    NotificationType,
    OrderFulfillmentStatus,
    OrderLineStatus,
    OrderRoutingStatus,
    PackageClass,
    PackageType,
    RejectReasonCode,
    RoutingRunInitiatedBy,
    RoutingRunMode,
    RoutingRunStatus,
    ServiceLevel,
    WindowStatus,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def _assert_common_fields(data: dict, entity: str) -> None:
    """id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def _assert_immutable_row_fields(data: dict, entity: str) -> None:
    """Rows the PRD declares immutable expose id + created_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert "version" not in data, f"{entity} must not expose a version"
    assert "updated_at" not in data, f"{entity} must not expose updated_at"


# ------------------------------------------------------------------ Store


def assert_store(data: dict) -> None:
    _assert_common_fields(data, "Store")
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert 1 <= data["origin_zone"] <= 8
    assert data["daily_unit_capacity"] >= 1
    assert data["units_committed_epoch"] >= 0
    assert data["staffed_labor_minutes"] >= 1
    assert data["reserved_labor_minutes"] >= 0
    assert data["labor_standard_minutes_per_order"] > 0
    assert data["pick_labor_minutes_per_unit"] > 0
    assert data["labor_rate_cents_per_minute"] >= 1
    assert 0 <= data["cutoff_utc_minutes"] <= 1439
    assert isinstance(data["hazmat_certified"], bool)
    assert data["node_status"] in _values(NodeStatus)
    assert data["eligibility_score_basis"] in _values(EligibilityScoreBasis)
    assert 0 <= data["eligibility_score"] <= 100
    assert 0 <= data["review_score"] <= 100
    assert data["consecutive_breach_windows"] >= 0
    assert data["reactivation_count"] >= 0
    assert data["deactivated_at_epoch"] is None or data["deactivated_at_epoch"] >= 1


# -------------------------------------------------------------------- Sku


def assert_sku(data: dict) -> None:
    _assert_common_fields(data, "Sku")
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert data["unit_weight_grams"] >= 1
    assert data["unit_price_cents"] >= 0
    assert data["package_class"] in _values(PackageClass)
    assert isinstance(data["hazmat_flag"], bool)


# --------------------------------------------------------- StoreInventory


def assert_store_inventory(data: dict) -> None:
    _assert_common_fields(data, "StoreInventory")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["sku_id"])
    assert data["on_hand_units"] >= 0
    assert data["reserved_units"] >= 0
    assert data["safety_stock_units"] >= 0
    assert data["available_to_promise_units"] >= 0
    assert data["last_adjustment_reason"] is None or isinstance(
        data["last_adjustment_reason"], str
    )
    assert_available_to_promise_consistent(data)


def assert_available_to_promise_consistent(data: dict) -> None:
    """available_to_promise_units is on_hand minus reserved minus safety, floored at 0."""
    expected = max(
        0,
        data["on_hand_units"] - data["reserved_units"] - data["safety_stock_units"],
    )
    assert data["available_to_promise_units"] == expected, (
        "available_to_promise_units should be "
        f"max(0, {data['on_hand_units']} - {data['reserved_units']} - "
        f"{data['safety_stock_units']}) = {expected}, got "
        f"{data['available_to_promise_units']}"
    )


# -------------------------------------------------------- PackagingSupply


def assert_packaging_supply(data: dict) -> None:
    _assert_common_fields(data, "PackagingSupply")
    assert is_valid_uuid(data["store_id"])
    assert data["package_type"] in _values(PackageType)
    assert data["on_hand_units"] >= 0
    assert data["reorder_point_units"] >= 0
    assert isinstance(data["reorder_flag"], bool)
    assert data["lifetime_consumed_units"] >= 0
    assert data["reorder_flag"] == (
        data["on_hand_units"] <= data["reorder_point_units"]
    ), "reorder_flag is on_hand_units <= reorder_point_units"


# ----------------------------------------------------------- CarrierPickup


def assert_carrier_pickup(data: dict) -> None:
    _assert_common_fields(data, "CarrierPickup")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["parcel_capacity"] >= 1
    assert 0 <= data["reserved_parcels"] <= data["parcel_capacity"]
    assert data["status"] in _values(CarrierPickupStatus)


# ----------------------------------------------------------- CustomerOrder


def assert_customer_order(data: dict) -> None:
    _assert_common_fields(data, "CustomerOrder")
    assert isinstance(data["order_code"], str) and data["order_code"]
    assert isinstance(data["customer_ref"], str) and data["customer_ref"]
    assert 1 <= data["destination_zone"] <= 8
    assert data["service_level"] in _values(ServiceLevel)
    assert is_iso8601_timestamp(data["promised_ship_by_utc"])
    assert data["routing_status"] in _values(OrderRoutingStatus)
    assert data["fulfillment_status"] in _values(OrderFulfillmentStatus)
    for counter in (
        "total_units",
        "shipped_units",
        "unassigned_units",
        "dc_fallback_units",
        "split_count",
        "reroute_attempt_count",
        "provisional_cost_cents",
        "dc_baseline_cost_cents",
        "cost_index_bps",
    ):
        assert data[counter] >= 0, f"CustomerOrder.{counter} must not be negative"
    assert data["final_cost_cents"] is None or data["final_cost_cents"] >= 0


# --------------------------------------------------------------- OrderLine


def assert_order_line(data: dict) -> None:
    _assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["sku_id"])
    assert data["quantity"] >= 1
    assert data["unit_price_cents"] >= 0
    assert data["line_status"] in _values(OrderLineStatus)
    assert_order_line_units_conserved(data)


def assert_order_line_units_conserved(data: dict) -> None:
    """Every demand unit sits in exactly one bucket."""
    total = (
        data["open_units"]
        + data["assigned_units"]
        + data["shipped_units"]
        + data["cancelled_units"]
        + data["dc_fallback_units"]
    )
    assert total == data["quantity"], (
        "open + assigned + shipped + cancelled + dc_fallback must equal quantity: "
        f"{total} != {data['quantity']}"
    )


# -------------------------------------------------------------- RoutingRun


def assert_routing_run(data: dict) -> None:
    _assert_common_fields(data, "RoutingRun")
    assert is_valid_uuid(data["order_id"])
    assert data["mode"] in _values(RoutingRunMode)
    assert data["initiated_by"] in _values(RoutingRunInitiatedBy)
    assert isinstance(data["excluded_store_ids"], list)
    assert data["status"] in _values(RoutingRunStatus)
    for counter in (
        "candidate_count",
        "selected_store_count",
        "planned_split_count",
        "projected_cost_cents",
        "projected_dc_cost_cents",
        "projected_cost_index_bps",
        "unfulfillable_units",
    ):
        assert data[counter] >= 0
    assert isinstance(data["guardrail_overridden"], bool)


# -------------------------------------------------------- RoutingCandidate


def assert_routing_candidate(data: dict) -> None:
    _assert_immutable_row_fields(data, "RoutingCandidate")
    assert is_valid_uuid(data["routing_run_id"])
    assert is_valid_uuid(data["store_id"])
    assert data["iteration"] >= 1
    assert isinstance(data["eligible"], bool)
    assert isinstance(data["selected"], bool)
    assert data["coverage_units"] >= 0
    assert data["coverage_ratio"] >= 0
    assert data["cost_estimate_cents"] >= 0
    assert data["delivery_days"] >= 0
    assert data["assigned_units"] >= 0


# --------------------------------------------------- FulfillmentAssignment


def assert_fulfillment_assignment(data: dict) -> None:
    _assert_common_fields(data, "FulfillmentAssignment")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["routing_run_id"])
    assert data["epoch"] >= 1
    assert data["status"] in _values(AssignmentStatus)
    assert data["assigned_units"] >= 1
    assert data["picked_units"] >= 0
    assert data["shortfall_units"] >= 0
    assert data["labor_minutes_reserved"] >= 0
    assert data["derived_package_type"] in _values(PackageType)
    assert data["package_type"] is None or data["package_type"] in _values(PackageType)
    assert is_iso8601_timestamp(data["pick_deadline_utc"])
    assert data["reroute_generation"] >= 0
    assert data["reject_reason_code"] is None or data["reject_reason_code"] in _values(
        RejectReasonCode
    )
    assert data["cancel_reason_code"] is None or data["cancel_reason_code"] in _values(
        CancelReasonCode
    )


# ----------------------------------------------------------- AssignmentLine


def assert_assignment_line(data: dict) -> None:
    _assert_immutable_row_fields(data, "AssignmentLine")
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert data["units_assigned"] >= 1
    assert data["units_picked"] >= 0
    assert data["units_cancelled"] >= 0


# ---------------------------------------------------- NodePerformanceWindow


def assert_node_performance_window(data: dict) -> None:
    _assert_common_fields(data, "NodePerformanceWindow")
    assert is_valid_uuid(data["store_id"])
    assert data["epoch"] >= 1
    assert data["status"] in _values(WindowStatus)
    assert is_iso8601_timestamp(data["opened_at_utc"])
    assert data["closed_at_utc"] is None or is_iso8601_timestamp(data["closed_at_utc"])
    assert isinstance(data["breach_flags"], list)
    assert isinstance(data["breached"], bool)
    assert data["breached"] == (len(data["breach_flags"]) > 0), (
        "breached is true exactly when breach_flags is non-empty"
    )
    assert data["node_action"] in _values(NodeAction)
    assert isinstance(data["cost_disadvantaged"], bool)


# ---------------------------------------------------- CustomerNotification


def assert_customer_notification(data: dict) -> None:
    _assert_immutable_row_fields(data, "CustomerNotification")
    assert is_valid_uuid(data["order_id"])
    assert data["assignment_id"] is None or is_valid_uuid(data["assignment_id"])
    assert data["notification_type"] in _values(NotificationType)
    assert data["channel"] in _values(NotificationChannel)
    assert data["units_affected"] >= 0
    assert isinstance(data["body_summary"], str)
    assert is_iso8601_timestamp(data["sent_at_utc"])


# ------------------------------------------------------ cost comparison read


def assert_cost_comparison(data: dict) -> None:
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["parcel_count"] >= 0
    for field in (
        "component_sum_cents",
        "split_penalty_cents",
        "reroute_overhead_cents",
        "pre_fee_subtotal_cents",
        "network_fee_cents",
        "store_cost_cents",
        "dc_baseline_cost_cents",
        "cost_index_bps",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
    assert data["pre_fee_subtotal_cents"] == (
        data["component_sum_cents"]
        + data["split_penalty_cents"]
        + data["reroute_overhead_cents"]
    ), "pre_fee_subtotal_cents is the component sum plus split penalty plus reroute overhead"
    assert data["store_cost_cents"] == (
        data["pre_fee_subtotal_cents"] + data["network_fee_cents"]
    ), "store_cost_cents is the pre-fee subtotal plus the network fee"
    assert data["savings_vs_dc_cents"] == (
        data["dc_baseline_cost_cents"] - data["store_cost_cents"]
    ), "savings_vs_dc_cents is the DC baseline minus the store cost"


# ------------------------------------------------------ conserved quantities


def assert_reserved_units_conserved(inventory: dict, open_assignments: list) -> None:
    """A row's reserved_units equals the units still reserved by its node's
    non-terminal assignments."""
    expected = sum(a["assigned_units"] - a["picked_units"] for a in open_assignments)
    assert inventory["reserved_units"] == expected, (
        f"reserved_units {inventory['reserved_units']} != {expected}"
    )


def assert_pickup_parcels_conserved(pickup: dict, shipped_assignments: list) -> None:
    assert pickup["reserved_parcels"] == len(shipped_assignments), (
        f"reserved_parcels {pickup['reserved_parcels']} != "
        f"{len(shipped_assignments)} shipped assignments"
    )
