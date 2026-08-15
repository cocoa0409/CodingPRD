"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """Standard system-managed fields: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_light_fields(data: dict, entity: str):
    """Lighter resources carry only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_supplier(data: dict):
    _assert_common_fields(data, "Supplier")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["establishment_number"], str) and data["establishment_number"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["allocation_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD"]
    assert isinstance(data["outstanding_exposure_cents"], int)
    assert data["outstanding_exposure_cents"] >= 0, \
        "exposure is floored at zero (PRD §2.10)"


def assert_warehouse(data: dict):
    _assert_common_fields(data, "Warehouse")
    assert isinstance(data["name"], str) and data["name"]
    assert data["zone"] in ["CHILLER", "FROZEN"]
    assert isinstance(data["capacity_lbs"], int)
    assert isinstance(data["occupied_lbs"], (int, float))
    assert data["occupied_lbs"] >= 0


def assert_product(data: dict):
    _assert_light_fields(data, "Product")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["kind"] in ["CARCASS", "PRIMAL", "SUBPRIMAL"]
    assert data["species"] in ["BEEF", "PORK"]
    assert isinstance(data["shelf_life_days"], int)
    assert isinstance(data["required_temp_max_f"], (int, float))


def assert_yield_spec(data: dict):
    _assert_light_fields(data, "YieldSpec")
    assert is_valid_uuid(data.get("carcass_product_id", "")), \
        "YieldSpec.carcass_product_id must be a UUID"
    assert is_valid_uuid(data.get("output_product_id", "")), \
        "YieldSpec.output_product_id must be a UUID"
    assert isinstance(data["expected_yield_pct"], (int, float))
    assert isinstance(data["min_yield_pct"], (int, float))
    assert isinstance(data["max_yield_pct"], (int, float))


def assert_price_sheet(data: dict):
    _assert_common_fields(data, "PriceSheet")
    assert isinstance(data["week_start_date"], str) and data["week_start_date"]
    assert data["status"] in ["DRAFT", "PUBLISHED", "CLOSED", "SUPERSEDED", "DISCARDED"]


def assert_price_sheet_line(data: dict):
    _assert_common_fields(data, "PriceSheetLine")
    assert is_valid_uuid(data.get("price_sheet_id", "")), \
        "PriceSheetLine.price_sheet_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), \
        "PriceSheetLine.product_id must be a UUID"
    assert isinstance(data["price_per_lb_cents"], int)
    assert isinstance(data["weekly_supply_lbs"], int)
    assert isinstance(data["allocated_lbs"], (int, float))
    assert data["allocated_lbs"] >= 0


def assert_purchase_order(data: dict):
    _assert_common_fields(data, "PurchaseOrder")
    assert isinstance(data["po_number"], str) and data["po_number"]
    assert is_valid_uuid(data.get("supplier_id", "")), "PO.supplier_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "PO.product_id must be a UUID"
    assert isinstance(data["ordered_weight_lbs"], (int, float))
    assert isinstance(data["contract_price_per_cwt_cents"], int)
    assert data["status"] in ["BOOKED", "RECEIVED", "GRADED", "CANCELLED"]


def assert_inventory_lot(data: dict):
    _assert_common_fields(data, "InventoryLot")
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert is_valid_uuid(data.get("product_id", "")), "Lot.product_id must be a UUID"
    assert is_valid_uuid(data.get("warehouse_id", "")), "Lot.warehouse_id must be a UUID"
    assert isinstance(data["received_weight_lbs"], (int, float))
    assert isinstance(data["current_weight_lbs"], (int, float))
    assert data["current_weight_lbs"] >= 0
    assert isinstance(data["age_days"], int)
    assert data["age_days"] >= 0
    assert data["usda_grade"] in [
        "UNGRADED", "PRIME", "CHOICE", "SELECT", "STANDARD", "NO_ROLL",
    ]
    assert data["status"] in [
        "IN_INSPECTION", "AVAILABLE", "QUARANTINED", "DEPLETED", "EXPIRED",
    ]


def assert_fabrication_batch(data: dict):
    _assert_common_fields(data, "FabricationBatch")
    assert is_valid_uuid(data.get("input_lot_id", "")), \
        "FabricationBatch.input_lot_id must be a UUID"
    assert isinstance(data["loss_lbs"], (int, float))
    assert isinstance(data["outputs"], list)
    assert isinstance(data["total_output_weight_lbs"], (int, float))
    assert isinstance(data["yield_efficiency_pct"], (int, float))
    assert data["status"] in ["DRAFT", "POSTED", "VOIDED"]


def assert_forward_contract(data: dict):
    _assert_common_fields(data, "ForwardContract")
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert is_valid_uuid(data.get("customer_id", "")), \
        "ForwardContract.customer_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), \
        "ForwardContract.product_id must be a UUID"
    assert isinstance(data["committed_lbs"], int)
    assert isinstance(data["fixed_price_per_lb_cents"], int)
    assert isinstance(data["delivery_week_start"], str)
    assert isinstance(data["delivered_lbs"], (int, float))
    assert isinstance(data["earmarked_lbs"], (int, float))
    assert isinstance(data["amendment_round"], int)
    assert data["status"] in ["OPEN", "SETTLED", "DEFAULTED", "CANCELLED"]


def assert_allocation(data: dict):
    _assert_common_fields(data, "Allocation")
    assert is_valid_uuid(data.get("customer_id", "")), \
        "Allocation.customer_id must be a UUID"
    assert is_valid_uuid(data.get("price_sheet_line_id", "")), \
        "Allocation.price_sheet_line_id must be a UUID"
    assert isinstance(data["requested_lbs"], (int, float))
    assert isinstance(data["allocated_lbs"], (int, float))
    assert data["status"] in [
        "REQUESTED", "CONFIRMED", "SHORTFALL", "SHIPPED", "CANCELLED",
    ]


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert is_valid_uuid(data.get("allocation_id", "")), \
        "Shipment.allocation_id must be a UUID"
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["trailer_temp_setpoint_f"], (int, float))
    assert isinstance(data["shipped_lbs"], (int, float))
    assert data["temp_compliance"] in ["UNKNOWN", "COMPLIANT", "BREACHED"]
    assert data["status"] in [
        "STAGING", "IN_TRANSIT", "DELIVERED", "REJECTED_AT_RECEIVING",
    ]


def assert_temperature_reading(data: dict):
    _assert_light_fields(data, "TemperatureReading")
    assert is_valid_uuid(data.get("shipment_id", "")), \
        "TemperatureReading.shipment_id must be a UUID"
    assert isinstance(data["reading_f"], (int, float))
    assert isinstance(data["recorded_at"], str) and data["recorded_at"]


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert is_valid_uuid(data.get("shipment_id", "")), \
        "Claim.shipment_id must be a UUID"
    assert data["claim_type"] in [
        "TEMPERATURE_ABUSE", "SPEC_NONCONFORMANCE", "WEIGHT_SHORTAGE",
        "QUALITY_DEFECT",
    ]
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["provisional_credit_cents"], int)
    assert isinstance(data["offer_round"], int)
    assert data["status"] in [
        "FILED", "OFFER_MADE", "COUNTERED", "SETTLED_PAID", "SETTLED_DENIED",
        "WITHDRAWN",
    ]


def assert_inspection_certificate(data: dict):
    _assert_light_fields(data, "InspectionCertificate")
    assert is_valid_uuid(data.get("lot_id", "")), "Certificate.lot_id must be a UUID"
    assert data["certificate_type"] in ["USDA_GRADE", "USDA_INSPECTION", "COA"]
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert isinstance(data["issued_by"], str) and data["issued_by"]
    assert isinstance(data["issue_date"], str) and data["issue_date"]
    assert data["status"] in ["VALID", "REVOKED"]


def assert_exposure_report(data: dict):
    assert is_valid_uuid(data.get("product_id", "")), \
        "exposure.product_id must be a UUID"
    assert isinstance(data["week_start"], str) and data["week_start"]
    for field in ("physical_lbs", "inbound_lbs", "forward_lbs", "spot_lbs",
                  "exposure_lbs"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert isinstance(data["exposure_value_cents"], int), \
        "exposure_value_cents must be integer cents"
