"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MODEL_CODE": "M-DEFAULT",
    "CATEGORY": "CHAIR",
    "BASE_FABRIC_YARDS": 3.0,
    "BASE_PRICE_CENTS": 50000,
    "FLAMMABILITY_STANDARD": "TB117_2013",
    "FABRIC_CODE": "FAB-DEFAULT",
    "ORIGIN": "PLANT",
    "GRADE": "A",
    "NOMINAL_WIDTH_INCHES": 54.0,
    "DEALER_CODE": "DLR-001",
    "DEALER_NAME": "Blue Ridge Furniture",
    "CREDIT_LIMIT_CENTS": 100000000,
    "SAMPLE_ALLOWANCE_CENTS": 5000000,
    "ORDER_NUMBER": "ORD-DEFAULT",
    "SHIP_TO_STATE": "NC",
    "DELIVERY_METHOD": "LTL_FREIGHT",
    "FABRIC_SOURCE": "PLANT_STOCK",
    "FINISH_CODE": "ESPRESSO",
    "QUANTITY": 1,
    "EXPECTED_YARDS": 30.0,
    "CELL_CODE": "C-CUT",
    "CELL_TYPE": "CUTTING",
    "OPERATION": "CUT",
    "COMPONENT_CODE": "FRAME",
    "SOURCE_TYPE": "DOMESTIC",
    "UNIT_SERIAL": "U-DEFAULT",
    "SAMPLE_VALUE_CENTS": 10000,
    "DUE_BACK_DAYS": 30,
    "CARRIER_NAME": "Averitt",
    "LABEL_LOT_NUMBER": "LBL-1",
}


def create_product_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": DEFAULTS["MODEL_CODE"],
        "category": DEFAULTS["CATEGORY"],
        "base_fabric_yards": DEFAULTS["BASE_FABRIC_YARDS"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "requires_pattern_match": False,
        "flammability_standard": DEFAULTS["FLAMMABILITY_STANDARD"],
        "required_component_codes": [],
        "option_rules": [
            {
                "fabric_grade": "A",
                "finish_code": "ANY",
                "allowed": True,
                "surcharge_pct": 0.0,
                "lead_time_adder_days": 0,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_fabric_spec_payload(**overrides) -> dict:
    defaults = {
        "fabric_code": DEFAULTS["FABRIC_CODE"],
        "origin": DEFAULTS["ORIGIN"],
        "grade": DEFAULTS["GRADE"],
        "nominal_width_inches": DEFAULTS["NOMINAL_WIDTH_INCHES"],
        "price_per_yard_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_dealer_account_payload(**overrides) -> dict:
    defaults = {
        "dealer_code": DEFAULTS["DEALER_CODE"],
        "name": DEFAULTS["DEALER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "sample_allowance_cents": DEFAULTS["SAMPLE_ALLOWANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_order_payload(**overrides) -> dict:
    defaults = {
        "order_number": DEFAULTS["ORDER_NUMBER"],
        "dealer_id": "",
        "ship_to_state": DEFAULTS["SHIP_TO_STATE"],
        "delivery_method": DEFAULTS["DELIVERY_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {
        "order_id": "",
        "model_id": "",
        "fabric_spec_id": "",
        "fabric_source": DEFAULTS["FABRIC_SOURCE"],
        "finish_code": DEFAULTS["FINISH_CODE"],
        "quantity": DEFAULTS["QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_material_lot_payload(**overrides) -> dict:
    defaults = {
        "fabric_spec_id": "",
        "expected_yards": DEFAULTS["EXPECTED_YARDS"],
    }
    defaults.update(overrides)
    return defaults


def create_cell_payload(**overrides) -> dict:
    defaults = {
        "cell_code": DEFAULTS["CELL_CODE"],
        "cell_type": DEFAULTS["CELL_TYPE"],
        "capacity_slots": 1,
        "certifications": [],
    }
    defaults.update(overrides)
    return defaults


def create_cell_booking_payload(**overrides) -> dict:
    defaults = {
        "cell_id": "",
        "order_line_id": "",
        "operation": DEFAULTS["OPERATION"],
        "start_at": "2026-06-01T08:00:00Z",
        "end_at": "2026-06-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_certificate_payload(**overrides) -> dict:
    defaults = {
        "order_id": "",
        "standard": DEFAULTS["FLAMMABILITY_STANDARD"],
        "label_lot_number": DEFAULTS["LABEL_LOT_NUMBER"],
        "label_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_supply_requisition_payload(**overrides) -> dict:
    defaults = {
        "order_line_id": "",
        "component_code": DEFAULTS["COMPONENT_CODE"],
        "quantity": 1,
        "source_type": DEFAULTS["SOURCE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_showroom_sample_payload(**overrides) -> dict:
    defaults = {
        "dealer_id": "",
        "model_id": "",
        "unit_serial": DEFAULTS["UNIT_SERIAL"],
        "sample_value_cents": DEFAULTS["SAMPLE_VALUE_CENTS"],
        "due_back_days": DEFAULTS["DUE_BACK_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "order_id": "",
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "weight_lb": 100.0,
        "length_in": 40.0,
        "width_in": 30.0,
        "height_in": 30.0,
        "declared_value_cents": 0,
        "piece_count": 1,
    }
    defaults.update(overrides)
    return defaults
