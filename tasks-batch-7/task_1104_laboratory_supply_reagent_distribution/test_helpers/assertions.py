"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    CustomerStatus,
    ExcursionSeverity,
    ExcursionStatus,
    HazardClass,
    JobStatus,
    KitStatus,
    LotStatus,
    OrderLineStatus,
    OrderStatus,
    ProductStatus,
    RecallStatus,
    ReservationStatus,
    RotationPolicy,
    ShipmentStatus,
    StandingOrderStatus,
    WarehouseStatus,
    ZoneClass,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_warehouse(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["hazmat_certified"], bool)
    assert data["status"] in [s.value for s in WarehouseStatus]


def assert_storage_zone(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("warehouse_id", ""))
    assert data["zone_class"] in [z.value for z in ZoneClass]
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert data["rotation_policy"] in [r.value for r in RotationPolicy]
    assert isinstance(data["occupied_units"], int) and data["occupied_units"] >= 0


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["storage_requirement"] in [z.value for z in ZoneClass]
    assert data["hazard_class"] in [h.value for h in HazardClass]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["requires_cold_chain"], bool)
    assert isinstance(data["shelf_life_days"], int) and data["shelf_life_days"] > 0
    assert data["status"] in [s.value for s in ProductStatus]


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("warehouse_id", ""))
    assert is_valid_uuid(data.get("storage_zone_id", ""))
    assert isinstance(data["lot_sequence_number"], int) and data["lot_sequence_number"] >= 1
    assert isinstance(data["quantity_received"], int) and data["quantity_received"] > 0
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["quantity_reserved"], int) and data["quantity_reserved"] >= 0
    assert isinstance(data["quantity_consumed"], int) and data["quantity_consumed"] >= 0
    assert isinstance(data["adjustment_total"], int)
    assert isinstance(data["expiry_date"], str) and len(data["expiry_date"]) == 10
    assert data["status"] in [s.value for s in LotStatus]


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert data["hazmat_endorsement"] in ["NONE", "LIMITED", "FULL"]
    assert isinstance(data["cold_chain_certified"], bool)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in [s.value for s in CustomerStatus]


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("warehouse_id", ""))
    assert data["shipping_service"] in ["STANDARD", "EXPRESS", "PRIORITY_OVERNIGHT"]
    assert data["status"] in [s.value for s in OrderStatus]


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["fulfillment_mode"] in ["ANY", "SEQUENTIAL"]
    assert isinstance(data["allocated_quantity"], int) and data["allocated_quantity"] >= 0
    assert data["status"] in [s.value for s in OrderLineStatus]


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in [s.value for s in ReservationStatus]


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["coolant_type"] in ["NONE", "GEL_PACK", "DRY_ICE"]
    assert isinstance(data["coolant_units"], int) and data["coolant_units"] >= 0
    assert isinstance(data["declared_weight_grams"], int) and data["declared_weight_grams"] > 0
    assert data["status"] in [s.value for s in ShipmentStatus]


def assert_excursion(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert data["severity"] in [s.value for s in ExcursionSeverity]
    assert isinstance(data["provisional_credit_cents"], int)
    assert data["status"] in [s.value for s in ExcursionStatus]


def assert_standing_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("warehouse_id", ""))
    assert isinstance(data["quantity_per_run"], int) and data["quantity_per_run"] > 0
    assert isinstance(data["interval_days"], int) and data["interval_days"] > 0
    assert isinstance(data["generated_order_count"], int)
    assert data["status"] in [s.value for s in StandingOrderStatus]


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["ceiling_quantity"], int) and data["ceiling_quantity"] > 0
    assert isinstance(data["stocked_quantity"], int)
    assert isinstance(data["consumed_quantity"], int)
    assert isinstance(data["contract_unit_price_cents"], int)
    assert data["status"] in [s.value for s in AgreementStatus]


def assert_consumption_record(data: dict):
    """ConsumptionRecord is immutable: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ConsumptionRecord must not expose version"
    assert "updated_at" not in data, "ConsumptionRecord must not expose updated_at"
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["charge_cents"], int)


def assert_recall(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["scope_type"] in ["LOT_RANGE", "PRODUCT_ALL"]
    assert data["severity_class"] in ["CLASS_I", "CLASS_II", "CLASS_III"]
    assert data["status"] in [s.value for s in RecallStatus]


def assert_kit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["components"], list)
    assert data["status"] in [s.value for s in KitStatus]


def assert_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("kit_id", ""))
    assert is_valid_uuid(data.get("warehouse_id", ""))
    assert isinstance(data["quantity_to_build"], int) and data["quantity_to_build"] > 0
    assert isinstance(data["kits_built"], int) and data["kits_built"] >= 0
    assert data["status"] in [s.value for s in JobStatus]


def assert_lot_quantity_conservation(lot: dict):
    """Physical-unit invariant: on_hand + reserved + consumed == received + adjustments."""
    assert (
        lot["quantity_on_hand"] + lot["quantity_reserved"] + lot["quantity_consumed"]
        == lot["quantity_received"] + lot["adjustment_total"]
    ), f"lot quantity conservation violated: {lot}"
