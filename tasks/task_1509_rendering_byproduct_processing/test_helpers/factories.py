"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "PLANT_NAME": "Plant A",
    "LOCATION": "Dallas TX",
    "COOKER_CAPACITY": 2,
    "STANDARD_COST_CENTS_PER_LB": 38,
    "EFFECTIVE_FROM": "2026-08-01",
    "EFFECTIVE_TO": "2026-12-31",
    "PERMIT_NUMBER": "P-1",
    "ODOR_EVENT_THRESHOLD": 5,
    "EMISSION_LIMIT_PPM": 5.0,
    "PERMIT_EXPIRES_ON": "2027-01-31",
    "SUPPLIER_NAME": "Sup A",
    "SUPPLIER_TYPE": "FARM",
    "AGREEMENT_REF": "AGR-1",
    "PICKUP_BASE_FEE_CENTS": 10000,
    "PER_LB_FEE_CENTS": 2,
    "MILEAGE_RATE_CENTS": 100,
    "VEHICLE_TAG": "V1",
    "VEHICLE_CAPACITY_LBS": 100000,
    "ROUTE_CODE": "R1",
    "SERVICE_DATE": "2026-08-10",
    "DEPARTURE": "2026-08-10T06:00:00Z",
    "RETURN": "2026-08-10T18:00:00Z",
    "WINDOW_START": "2026-08-10T08:00:00Z",
    "WINDOW_END": "2026-08-10T09:00:00Z",
    "EST_WEIGHT_LBS": 5000,
    "EST_MILES": 10,
    "BATCH_WEIGHT_LBS": 5000,
    "TEMPERATURE_F": 60.0,
    "RECEIVED_AT": "2026-08-03T08:00:00Z",
    "COOK_START": "2026-08-04T06:00:00Z",
    "COOK_END": "2026-08-04T09:00:00Z",
    "CUSTOMER_NAME": "Cust A",
    "BASE_PRICE_CENTS_PER_LB": 50,
    "VOLUME_COMMITMENT_LBS": 1000,
    "MARGIN_FLOOR_PCT": 15.0,
    "ORDER_QUANTITY_LBS": 100,
    "SHIP_DATE": "2026-08-20",
    "REPORTED_AT": "2026-08-05T09:00:00Z",
    "LOCATION_DESCRIPTION": "Gate",
    "WASHED_AT": "2026-08-05T09:00:00Z",
    "DETERGENT_PPM": 800.0,
}


def create_plant_payload(**overrides) -> dict:
    payload = {
        "plant_name": DEFAULTS["PLANT_NAME"],
        "location": DEFAULTS["LOCATION"],
        "cooker_capacity": DEFAULTS["COOKER_CAPACITY"],
        "standard_cost_cents_per_lb": DEFAULTS["STANDARD_COST_CENTS_PER_LB"],
    }
    payload.update(overrides)
    return payload


def create_permit_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "permit_number": DEFAULTS["PERMIT_NUMBER"],
        "odor_event_threshold": DEFAULTS["ODOR_EVENT_THRESHOLD"],
        "emission_limit_ppm": DEFAULTS["EMISSION_LIMIT_PPM"],
        "expires_on": DEFAULTS["PERMIT_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_odor_event_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "reported_at": DEFAULTS["REPORTED_AT"],
        "location_description": DEFAULTS["LOCATION_DESCRIPTION"],
        "severity": "LOW",
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "supplier_name": DEFAULTS["SUPPLIER_NAME"],
        "supplier_type": DEFAULTS["SUPPLIER_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(supplier_id, plant_id, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "plant_id": plant_id,
        "agreement_ref": DEFAULTS["AGREEMENT_REF"],
        "species_scope": ["BOVINE"],
        "prohibited_material_policy": "SORT_AND_RETURN",
        "accepts_dead_stock": False,
        "pickup_base_fee_cents": DEFAULTS["PICKUP_BASE_FEE_CENTS"],
        "per_lb_fee_cents": DEFAULTS["PER_LB_FEE_CENTS"],
        "mileage_rate_cents": DEFAULTS["MILEAGE_RATE_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "vehicle_tag": DEFAULTS["VEHICLE_TAG"],
        "capacity_lbs": DEFAULTS["VEHICLE_CAPACITY_LBS"],
        "duty_class": "RAW_MATERIAL",
    }
    payload.update(overrides)
    return payload


def create_wash_ticket_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "wash_type": "STANDARD",
        "washed_at": DEFAULTS["WASHED_AT"],
        "detergent_ppm": DEFAULTS["DETERGENT_PPM"],
        "result": "PASS",
    }
    payload.update(overrides)
    return payload


def create_route_payload(plant_id, vehicle_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "vehicle_id": vehicle_id,
        "route_code": DEFAULTS["ROUTE_CODE"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "scheduled_departure": DEFAULTS["DEPARTURE"],
        "scheduled_return": DEFAULTS["RETURN"],
    }
    payload.update(overrides)
    return payload


def create_stop_payload(
    route_id, supplier_id, agreement_id, plant_id, expected_route_version, **overrides
) -> dict:
    payload = {
        "route_id": route_id,
        "supplier_id": supplier_id,
        "agreement_id": agreement_id,
        "plant_id": plant_id,
        "sequence_no": 1,
        "scheduled_window_start": DEFAULTS["WINDOW_START"],
        "scheduled_window_end": DEFAULTS["WINDOW_END"],
        "estimated_weight_lbs": DEFAULTS["EST_WEIGHT_LBS"],
        "estimated_distance_miles": DEFAULTS["EST_MILES"],
        "species_tag": "BOVINE",
        "is_dead_stock": False,
        "expected_route_version": expected_route_version,
    }
    payload.update(overrides)
    return payload


def create_batch_payload(plant_id, supplier_id, agreement_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "supplier_id": supplier_id,
        "agreement_id": agreement_id,
        "species": "BOVINE",
        "weight_lbs": DEFAULTS["BATCH_WEIGHT_LBS"],
        "temperature_f": DEFAULTS["TEMPERATURE_F"],
        "received_at": DEFAULTS["RECEIVED_AT"],
    }
    payload.update(overrides)
    return payload


def create_cook_run_payload(plant_id, planned_inputs, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "cooker_line": 1,
        "recipe": "RUMINANT_RENDER",
        "planned_inputs": planned_inputs,
        "cook_start": DEFAULTS["COOK_START"],
        "cook_end": DEFAULTS["COOK_END"],
    }
    payload.update(overrides)
    return payload


def create_contract_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "product_type": "TALLOW",
        "spec_max_moisture_pct": 0.5,
        "spec_max_ffa_pct": 4.0,
        "spec_min_protein_pct": 0,
        "pricing_mode": "FIXED",
        "base_price_cents_per_lb": DEFAULTS["BASE_PRICE_CENTS_PER_LB"],
        "volume_commitment_lbs": DEFAULTS["VOLUME_COMMITMENT_LBS"],
        "tier_discounts": [],
        "margin_floor_pct": DEFAULTS["MARGIN_FLOOR_PCT"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_order_payload(contract_id, plant_id, expected_contract_version, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "plant_id": plant_id,
        "quantity_lbs": DEFAULTS["ORDER_QUANTITY_LBS"],
        "requested_ship_date": DEFAULTS["SHIP_DATE"],
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def create_price_index_entry_payload(plant_id, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "index_product": "TALLOW",
        "effective_date": "2026-08-01",
        "price_cents_per_lb": 40,
        "source": "JACOBSEN",
    }
    payload.update(overrides)
    return payload
