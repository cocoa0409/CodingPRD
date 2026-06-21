"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides so individual tests
can control just the fields they care about.
"""


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "customer@example.com",
        "full_name": "Test Customer",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "make": "TOYOTA",
        "model": "CAMRY",
        "model_year": 2022,
        "oe_tire_size": "235/45R18",
        "rim_diameter_in": 18,
        "tpms_type": "DIRECT",
    }
    defaults.update(overrides)
    return defaults


def create_tire_model_payload(**overrides) -> dict:
    defaults = {
        "brand": "MICHELIN",
        "model_name": "PRIMACY",
        "size_token": "235/45R18",
        "load_index": 94,
        "speed_rating": "V",
        "unit_price_cents": 14999,
        "mileage_warranty_miles": 60000,
        "original_tread_32nds": 10,
        "stock_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_fitment_rule_payload(vehicle_id, tire_model_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "tire_model_id": tire_model_id,
        "fitment_grade": "OE_EXACT",
    }
    defaults.update(overrides)
    return defaults


def create_service_bay_payload(**overrides) -> dict:
    defaults = {
        "bay_name": "Bay-1",
        "alignment_capable": False,
        "turnover_buffer_min": 15,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
    }
    defaults.update(overrides)
    return defaults


def create_tire_line_payload(tire_model_id, expected_work_order_version,
                             quantity=4, road_hazard_opted=False, **overrides) -> dict:
    defaults = {
        "line_type": "TIRE",
        "tire_model_id": tire_model_id,
        "quantity": quantity,
        "road_hazard_opted": road_hazard_opted,
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_service_line_payload(line_type, expected_work_order_version,
                                quantity=1, **overrides) -> dict:
    defaults = {
        "line_type": line_type,
        "quantity": quantity,
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(work_order_id, service_bay_id, scheduled_start,
                               scheduled_end, expected_service_bay_version, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "service_bay_id": service_bay_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_service_bay_version": expected_service_bay_version,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(work_order_line_id, tire_model_id,
                                 requested_quantity=4, **overrides) -> dict:
    defaults = {
        "work_order_line_id": work_order_line_id,
        "tire_model_id": tire_model_id,
        "requested_quantity": requested_quantity,
    }
    defaults.update(overrides)
    return defaults


def create_mileage_claim_payload(work_order_line_id, tire_model_id,
                                 measured_tread_32nds=2, miles_driven=10000,
                                 payout_method="REFUND", claim_quantity=4, **overrides) -> dict:
    defaults = {
        "work_order_line_id": work_order_line_id,
        "tire_model_id": tire_model_id,
        "measured_tread_32nds": measured_tread_32nds,
        "miles_driven": miles_driven,
        "payout_method": payout_method,
        "claim_quantity": claim_quantity,
    }
    defaults.update(overrides)
    return defaults
