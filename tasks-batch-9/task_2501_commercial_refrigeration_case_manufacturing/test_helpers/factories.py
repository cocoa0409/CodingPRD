"""Payload factories — one per creatable resource, input fields only.

Each factory returns the PRD-declared request body with sensible defaults and
accepts `**overrides` for any field a test needs to control.
"""

from typing import Any, Dict

from .constants import TEST_DEFAULTS


def _build(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    # An override of None means "omit this field entirely".
    return {k: v for k, v in payload.items() if v is not None}


def create_refrigerant_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 refrigerant blend."""
    return _build(
        {
            "refrigerant_code": TEST_DEFAULTS["REFRIGERANT_CODE"],
            "trade_name": TEST_DEFAULTS["REFRIGERANT_TRADE_NAME"],
            "gwp_100yr": TEST_DEFAULTS["REFRIGERANT_GWP"],
            "safety_class": "A1",
            "max_charge_grams": 999999,
            "allowed_system_types": ["REMOTE", "SELF_CONTAINED"],
        },
        overrides,
    )


def create_energy_standard_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 energy standard."""
    return _build(
        {
            "standard_code": TEST_DEFAULTS["STANDARD_CODE"],
            "effective_date": TEST_DEFAULTS["STANDARD_EFFECTIVE_DATE"],
            "max_gwp": TEST_DEFAULTS["STANDARD_MAX_GWP"],
            "limit_coefficient_a": TEST_DEFAULTS["STANDARD_COEFFICIENT_A"],
            "limit_constant_b": TEST_DEFAULTS["STANDARD_CONSTANT_B"],
            "temperature_class": "MT",
            "system_type_scope": "ANY",
        },
        overrides,
    )


def create_test_chamber_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 psychrometric test chamber."""
    return _build(
        {
            "chamber_code": TEST_DEFAULTS["CHAMBER_CODE"],
            "name": "Energy Lab Chamber 1",
            "supported_temperature_classes": ["HT", "MT", "LT"],
            "turnaround_hours": TEST_DEFAULTS["CHAMBER_TURNAROUND_HOURS"],
            "max_tda_sqft": TEST_DEFAULTS["CHAMBER_MAX_TDA_SQFT"],
        },
        overrides,
    )


def create_install_crew_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 install crew."""
    return _build(
        {
            "crew_code": TEST_DEFAULTS["CREW_CODE"],
            "contractor_name": TEST_DEFAULTS["CONTRACTOR_NAME"],
            "service_region_codes": ["OH", "IN"],
            "daily_case_capacity": TEST_DEFAULTS["DAILY_CASE_CAPACITY"],
        },
        overrides,
    )


def create_part_inventory_payload(case_model_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.1 depot stock row."""
    return _build(
        {
            "part_number": "CMP-8-OH",
            "description": "Compressor for MDL-MT-8",
            "case_model_id": case_model_id,
            "region_code": TEST_DEFAULTS["REGION_CODE"],
            "on_hand_qty": 5,
            "unit_cost_cents": 45000,
            "min_stock_qty": 2,
        },
        overrides,
    )


def create_case_model_payload(refrigerant_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.2 case model design — an 8 ft MT remote dairy multideck."""
    return _build(
        {
            "model_code": TEST_DEFAULTS["MODEL_CODE"],
            "application": "DAIRY_MULTIDECK",
            "temperature_class": "MT",
            "system_type": "REMOTE",
            "refrigerant_id": refrigerant_id,
            "nominal_length_ft": 8,
            "tda_sqft": TEST_DEFAULTS["MODEL_TDA_SQFT"],
            "charge_grams": TEST_DEFAULTS["MODEL_CHARGE_GRAMS"],
            "line_set_length_ft": TEST_DEFAULTS["MODEL_LINE_SET_LENGTH_FT"],
            "door_type": "OPEN",
            "glass_door_count": 0,
            "curtain_layers": 2,
            "discharge_velocity_mps": 0.55,
            "case_air_temp_c": 2.0,
            "ambient_dew_point_c": 15.5,
            "lighting_w_per_ft": 12.0,
            "fan_w_per_ft": 9.5,
            "defrost_cycles_per_day": 4,
        },
        overrides,
    )


def create_energy_test_payload(
    case_model_id: str,
    test_chamber_id: str,
    energy_standard_id: str,
    expected_case_model_version: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3 energy test scheduling."""
    return _build(
        {
            "case_model_id": case_model_id,
            "test_chamber_id": test_chamber_id,
            "energy_standard_id": energy_standard_id,
            "window_start": TEST_DEFAULTS["WINDOW_START"],
            "window_end": TEST_DEFAULTS["WINDOW_END"],
            "test_ambient_c": TEST_DEFAULTS["TEST_AMBIENT_C"],
            "store_ambient_c": TEST_DEFAULTS["STORE_AMBIENT_C"],
            "expected_case_model_version": expected_case_model_version,
        },
        overrides,
    )


def complete_energy_test_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3 metered completion."""
    return _build(
        {
            "measured_kwh_24h": TEST_DEFAULTS["MEASURED_KWH_24H"],
            "measured_defrost_cycles": TEST_DEFAULTS["MEASURED_DEFROST_CYCLES"],
        },
        overrides,
    )


def create_compliance_label_payload(
    case_model_id: str, energy_test_id: str, **overrides
) -> Dict[str, Any]:
    """PRD §3.4 label issuance."""
    return _build(
        {
            "case_model_id": case_model_id,
            "energy_test_id": energy_test_id,
            "label_code": TEST_DEFAULTS["LABEL_CODE"],
        },
        overrides,
    )


def create_store_plan_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.6 store plan."""
    return _build(
        {
            "banner_name": TEST_DEFAULTS["BANNER_NAME"],
            "store_number": TEST_DEFAULTS["STORE_NUMBER"],
            "region_code": TEST_DEFAULTS["REGION_CODE"],
            "remodel_window_start": TEST_DEFAULTS["REMODEL_WINDOW_START"],
            "remodel_window_end": TEST_DEFAULTS["REMODEL_WINDOW_END"],
            "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        },
        overrides,
    )


def create_store_plan_line_payload(case_model_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.6 configured line."""
    return _build(
        {
            "case_model_id": case_model_id,
            "length_ft": 8,
            "quantity": 1,
            "end_cap": "LEFT",
            "merchandising_options": ["LED_CANOPY", "NIGHT_CURTAIN"],
        },
        overrides,
    )


def create_shipment_payload(
    store_plan_id: str, expected_store_plan_version: int, **overrides
) -> Dict[str, Any]:
    """PRD §3.8 shipment creation."""
    return _build(
        {
            "store_plan_id": store_plan_id,
            "ship_date": TEST_DEFAULTS["SHIP_DATE"],
            "delivery_date": TEST_DEFAULTS["DELIVERY_DATE"],
            "carrier_code": TEST_DEFAULTS["CARRIER_CODE"],
            "expected_store_plan_version": expected_store_plan_version,
        },
        overrides,
    )


def create_install_booking_payload(
    shipment_id: str, install_crew_id: str, **overrides
) -> Dict[str, Any]:
    """PRD §3.8 install crew reservation."""
    return _build(
        {
            "shipment_id": shipment_id,
            "install_crew_id": install_crew_id,
            "start_date": TEST_DEFAULTS["BOOKING_START_DATE"],
            "end_date": TEST_DEFAULTS["BOOKING_END_DATE"],
            "cases_committed": 1,
        },
        overrides,
    )


def create_warranty_claim_payload(
    work_order_id: str, part_inventory_id: str, install_crew_id: str, **overrides
) -> Dict[str, Any]:
    """PRD §3.9 warranty claim."""
    return _build(
        {
            "work_order_id": work_order_id,
            "part_inventory_id": part_inventory_id,
            "install_crew_id": install_crew_id,
            "claim_type": "DOOR_GASKET",
            "reported_date": "2026-09-20",
            "requested_qty": 1,
            "estimated_cost_cents": 90000,
        },
        overrides,
    )


def qa_result_payload(result: str, **overrides) -> Dict[str, Any]:
    """PRD §3.7 final QA outcome."""
    return _build({"result": result}, overrides)


def engineering_change_payload(refrigerant_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.5 engineering change."""
    return _build(
        {
            "refrigerant_id": refrigerant_id,
            "charge_grams": 3900,
            "line_set_length_ft": TEST_DEFAULTS["MODEL_LINE_SET_LENGTH_FT"],
            "change_note": "Transition to a lower-GWP blend",
        },
        overrides,
    )
