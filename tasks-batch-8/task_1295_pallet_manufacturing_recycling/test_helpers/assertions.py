"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), \
            f"{entity}.version must be int"


def assert_pallet_spec(data: dict):
    _assert_common_fields(data, "PalletSpec")
    assert isinstance(data["spec_code"], str) and data["spec_code"]
    assert data["length_in"] > 0 and data["width_in"] > 0
    assert data["height_in"] > 0
    assert isinstance(data["board_count"], int) and data["board_count"] >= 5
    assert data["lumber_species"] in ["PINE", "OAK", "MIXED"]
    assert isinstance(data["board_feet_per_pallet"], (int, float))
    assert isinstance(data["unit_cube_cuft"], (int, float))
    assert isinstance(data["requires_heat_treatment_default"], bool)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_lumber_index(data: dict):
    """Immutable market-data row: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), \
        "LumberPriceIndex.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "LumberPriceIndex.created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable index row must not carry updated_at"
    assert "version" not in data, "immutable index row must not carry version"
    assert data["species"] in ["PINE", "OAK", "MIXED"]
    assert isinstance(data["price_per_mbf_cents"], int)
    assert data["price_per_mbf_cents"] >= 0
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))


def assert_seasonal_index(data: dict):
    """Immutable market-data band: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), \
        "SeasonalPriceIndex.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "SeasonalPriceIndex.created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable band must not carry updated_at"
    assert "version" not in data, "immutable band must not carry version"
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert isinstance(data["multiplier_bp"], int)
    assert 5000 <= data["multiplier_bp"] <= 20000


def assert_core_batch(data: dict):
    _assert_common_fields(data, "CorePurchaseBatch")
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["agreed_unit_price_cents"], int)
    assert isinstance(data["manifest_count"], int) and data["manifest_count"] > 0
    assert isinstance(data["estimated_grade_mix"], dict)
    assert isinstance(data["received_count"], int)
    assert data["status"] in ["RECEIVING", "SORTING", "AUDIT", "CLOSED"]


def assert_core_unit(data: dict):
    _assert_common_fields(data, "CoreUnit")
    assert data["grade"] in ["UNSORTED", "A", "B", "SCRAP"]
    assert data["species"] in ["PINE", "OAK", "MIXED"]
    assert isinstance(data["repair_cycle_count"], int)
    assert data["processing_status"] in [
        "YARD", "IN_REPAIR", "REPAIRED", "GRINDING_QUEUED", "GROUND",
    ]


def assert_repair_work_order(data: dict):
    _assert_common_fields(data, "RepairWorkOrder")
    assert data["target_grade"] in ["A", "B"]
    assert isinstance(data["labor_minutes_estimate"], int)
    assert data["labor_minutes_estimate"] > 0
    assert data["status"] in ["OPEN", "IN_PROGRESS", "COMPLETED", "ABORTED"]


def assert_inventory_lot(data: dict):
    _assert_common_fields(data, "InventoryLot")
    assert data["origin_type"] in ["NEW_BUILD", "RECYCLED_REPAIR"]
    assert isinstance(data["quantity_total"], int) and data["quantity_total"] > 0
    assert isinstance(data["quantity_available"], int)
    assert data["quality_grade"] in ["NEW", "A", "B"]
    assert data["heat_treat_status"] in [
        "NOT_REQUIRED", "PENDING_HT", "HT_CERTIFIED",
    ]
    assert data["status"] in ["AVAILABLE", "DEPLETED", "QUARANTINED"]


def assert_ht_run(data: dict):
    _assert_common_fields(data, "HeatTreatmentRun")
    assert isinstance(data["chamber_code"], str) and data["chamber_code"]
    assert data["species_profile"] in ["PINE", "OAK", "MIXED"]
    assert isinstance(data["capacity_pallets"], int)
    assert data["capacity_pallets"] > 0
    assert isinstance(data["loaded_pallets"], int)
    assert data["status"] in ["STAGING", "RUNNING", "COMPLETED", "FAILED"]


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["pool_credit_balance_cents"], int)
    assert isinstance(data["pool_units_outstanding"], int)
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]


def assert_sales_order(data: dict):
    _assert_common_fields(data, "SalesOrder")
    assert isinstance(data["customer_id"], str)
    assert data["payment_status"] in ["UNPAID", "PAID", "CREDIT_SETTLED"]
    assert data["fulfillment_status"] in [
        "DRAFT", "CONFIRMED", "ALLOCATED", "SHIPPED", "DELIVERED", "CANCELLED",
    ]


def assert_order_line(data: dict):
    _assert_common_fields(data, "OrderLine")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["spec_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["quality_grade_requested"] in ["NEW", "A", "B"]
    assert isinstance(data["unit_price_cents"], int)
    assert data["status"] in ["OPEN", "ALLOCATED", "FULFILLED", "CANCELLED"]


def assert_pool_return(data: dict):
    _assert_common_fields(data, "PoolReturn")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["returned_count"], int) and data["returned_count"] > 0
    assert data["grade_on_return"] in ["A", "B", "SCRAP"]
    assert data["status"] in ["LOGGED", "GRADED", "CREDITED", "DISPUTED"]


def assert_delivery_route(data: dict):
    _assert_common_fields(data, "DeliveryRoute")
    assert data["trailer_cube_capacity_cuft"] > 0
    assert isinstance(data["cube_used_cuft"], (int, float))
    assert data["planned_miles"] > 0
    assert data["status"] in ["PLAN", "DISPATCHED", "CLOSED", "CANCELLED"]


def assert_route_stop(data: dict):
    _assert_common_fields(data, "RouteStop")
    assert isinstance(data["route_id"], str)
    assert isinstance(data["stop_sequence"], int) and data["stop_sequence"] >= 1
    assert data["stop_type"] in ["DELIVERY", "PICKUP", "MIXED"]
    assert data["status"] in ["SCHEDULED", "ARRIVED", "COMPLETED", "SKIPPED"]


def assert_grinding_batch(data: dict):
    _assert_common_fields(data, "GrindingBatch")
    assert isinstance(data["input_core_ids"], list)
    assert isinstance(data["input_count"], int)
    assert data["status"] in ["QUEUED", "GRINDING", "COMPLETED"]
