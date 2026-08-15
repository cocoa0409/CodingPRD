"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Pacific Harvest Ltd",
    "COUNTRY_CODE": "JP",
    "FACILITY_REGISTRATION_NUMBER": "FRN-0001",
    "EVAL_PERIOD_START": "2024-01-01T00:00:00Z",
    "EVAL_PERIOD_END": "2024-12-31T00:00:00Z",
    "EVAL_SCORE": 90,
    "ENTRY_NUMBER": "E-0001",
    "SPECIES_DECLARED": "TUNA",
    "TRANSPORT_MODE": "VESSEL",
    "SCHEDULED_ARRIVAL": "2026-08-10T00:00:00Z",
    "PORT_CODE": "USLAX",
    "GOODS_VALUE_CENTS": 100000,
    "FREIGHT_COST_CENTS": 5000,
    "DUTY_RATE_PCT": 0.0,
    "TOTAL_WEIGHT_KG": 100,
    "VESSEL_NAME": "FV Pacific",
    "HARVEST_DATE": "2026-07-20T00:00:00Z",
    "CATCH_AREA_CODE": "FAO77",
    "HARVEST_COUNTRY_CODE": "US",
    "PRODUCTION_METHOD": "WILD",
    "GRADE": "A",
    "QUANTITY_RECEIVED_KG": 100,
    "RECEIVING_TEMP_C": 1.0,
    "SAMPLE_SIZE": 3,
    "TARGET_SPECIES": "COD",
    "PRODUCT_FORM": "FILLET",
    "QUANTITY_KG": 10,
    "INTERVAL_START": "2026-07-25T10:00:00Z",
    "INTERVAL_END": "2026-07-25T11:00:00Z",
    "CORE_TEMP_C": -21.0,
    "AVG_TEMP_C": -20.0,
    "TEMP_SOURCE": "CONTINUOUS_MONITOR",
    "MEASURED_AT": "2026-07-25T10:00:00Z",
    "MARKET_NAME": "Pacific Cod",
    "SCIENTIFIC_NAME": "Gadus macrocephalus",
    "LABEL_SPECIES": "COD",
    "LABEL_COO": "US",
    "NET_WEIGHT_KG": 10,
    "RESOLUTION_NOTE": "resolved after investigation",
    "RECALL_REASON": "compliance recall",
}


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "facility_registration_number": DEFAULTS["FACILITY_REGISTRATION_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_evaluation_payload(**overrides) -> dict:
    defaults = {
        "supplier_id": None,
        "expected_supplier_version": 1,
        "period_start": DEFAULTS["EVAL_PERIOD_START"],
        "period_end": DEFAULTS["EVAL_PERIOD_END"],
        "hazard_analysis_score": DEFAULTS["EVAL_SCORE"],
        "record_review_score": DEFAULTS["EVAL_SCORE"],
        "performance_score": DEFAULTS["EVAL_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_import_entry_payload(**overrides) -> dict:
    defaults = {
        "supplier_id": None,
        "entry_number": DEFAULTS["ENTRY_NUMBER"],
        "species_declared": DEFAULTS["SPECIES_DECLARED"],
        "transport_mode": DEFAULTS["TRANSPORT_MODE"],
        "scheduled_arrival": DEFAULTS["SCHEDULED_ARRIVAL"],
        "port_code": DEFAULTS["PORT_CODE"],
        "goods_value_cents": DEFAULTS["GOODS_VALUE_CENTS"],
        "freight_cost_cents": DEFAULTS["FREIGHT_COST_CENTS"],
        "duty_rate_pct": DEFAULTS["DUTY_RATE_PCT"],
        "total_weight_kg": DEFAULTS["TOTAL_WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_receipt_lot_payload(**overrides) -> dict:
    defaults = {
        "import_entry_id": None,
        "vessel_name": DEFAULTS["VESSEL_NAME"],
        "harvest_date": DEFAULTS["HARVEST_DATE"],
        "catch_area_code": DEFAULTS["CATCH_AREA_CODE"],
        "harvest_country_code": DEFAULTS["HARVEST_COUNTRY_CODE"],
        "production_method": DEFAULTS["PRODUCTION_METHOD"],
        "species_declared": DEFAULTS["SPECIES_DECLARED"],
        "grade": DEFAULTS["GRADE"],
        "quantity_received_kg": DEFAULTS["QUANTITY_RECEIVED_KG"],
        "receiving_temp_c": DEFAULTS["RECEIVING_TEMP_C"],
    }
    defaults.update(overrides)
    return defaults


def create_species_verification_payload(**overrides) -> dict:
    defaults = {
        "receipt_lot_id": None,
        "test_method": "SENSORY",
        "sample_size": DEFAULTS["SAMPLE_SIZE"],
        "verified_species": DEFAULTS["SPECIES_DECLARED"],
    }
    defaults.update(overrides)
    return defaults


def create_processing_batch_payload(**overrides) -> dict:
    defaults = {
        "target_species": DEFAULTS["TARGET_SPECIES"],
        "product_form": DEFAULTS["PRODUCT_FORM"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_input_payload(**overrides) -> dict:
    defaults = {
        "receipt_lot_id": None,
        "quantity_kg": DEFAULTS["QUANTITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_complete_batch_payload(**overrides) -> dict:
    defaults = {
        "expected_batch_version": 1,
        "actual_output_kg": 0,
        "trim_waste_kg": 0,
        "other_waste_kg": 0,
    }
    defaults.update(overrides)
    return defaults


def create_temperature_log_payload(**overrides) -> dict:
    defaults = {
        "interval_start": DEFAULTS["INTERVAL_START"],
        "interval_end": DEFAULTS["INTERVAL_END"],
        "core_temp_c": DEFAULTS["CORE_TEMP_C"],
        "avg_temp_c": DEFAULTS["AVG_TEMP_C"],
        "source": DEFAULTS["TEMP_SOURCE"],
    }
    defaults.update(overrides)
    return defaults


def create_haccp_record_payload(**overrides) -> dict:
    defaults = {
        "hazard_type": "HISTAMINE",
        "phase": "SCREENING",
        "measured_value": 30.0,
        "measured_at": DEFAULTS["MEASURED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_payload(**overrides) -> dict:
    defaults = {
        "source_type": "MANUAL",
        "reason": "manual audit finding",
    }
    defaults.update(overrides)
    return defaults


def create_product_label_payload(**overrides) -> dict:
    defaults = {
        "market_name": DEFAULTS["MARKET_NAME"],
        "scientific_name": DEFAULTS["SCIENTIFIC_NAME"],
        "species": DEFAULTS["LABEL_SPECIES"],
        "production_method": DEFAULTS["PRODUCTION_METHOD"],
        "country_of_origin": DEFAULTS["LABEL_COO"],
    }
    defaults.update(overrides)
    return defaults


def create_finished_lot_payload(**overrides) -> dict:
    defaults = {
        "processing_batch_id": None,
        "net_weight_kg": DEFAULTS["NET_WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults
