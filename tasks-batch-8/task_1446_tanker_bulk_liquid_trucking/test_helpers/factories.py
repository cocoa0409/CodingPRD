"""Payload factories — one per entity, input fields only (PRD sections 3.1-3.8)."""

DEFAULTS = {
    "CUSTOMER_NAME": "Acme Chem",
    "CREDIT_LIMIT_CENTS": 1_000_000_000,
    "PRODUCT_NAME": "Diesel ULSD",
    "UNIT_NUMBER": "T-101",
    "CDL_NUMBER": "CDL-1",
    "BAY_CODE": "WB-1",
    "RACK_CODE": "R-1",
    "METER_ID": "M-1",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "compatibility_group": "PETROLEUM",
        "hazmat_class": "CLASS_3_FLAMMABLE",
        "packing_group": "II",
        "density_lb_per_gal": 7.0,
        "temp_coeff_per_degF": 0.0007,
        "placard_code": "UN1993",
    }
    defaults.update(overrides)
    return defaults


def create_compatibility_rule_payload(**overrides) -> dict:
    defaults = {
        "prior_group": "PETROLEUM",
        "next_group": "PETROLEUM",
        "required_wash_level": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_trailer_payload(**overrides) -> dict:
    defaults = {
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "capacity_gallons": 8000,
        "tare_weight_lb": 25000,
        "tare_steer_lb": 6000,
        "tare_drive_lb": 9000,
        "tare_trailer_lb": 10000,
        "steer_axle_rating_lb": 12000,
        "drive_axle_rating_lb": 34000,
        "trailer_axle_rating_lb": 34000,
        "gvwr_lb": 80000,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dana Roe",
        "cdl_number": DEFAULTS["CDL_NUMBER"],
        "tanker_endorsement": True,
        "hazmat_endorsement": True,
        "endorsement_expires_on": "2027-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_wash_bay_payload(**overrides) -> dict:
    defaults = {
        "bay_code": DEFAULTS["BAY_CODE"],
        "supported_wash_levels": ["FLUSH", "DETERGENT_WASH"],
        "cleanup_buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_wash_certificate_payload(trailer_id: str, wash_bay_id: str, **overrides) -> dict:
    defaults = {
        "trailer_id": trailer_id,
        "wash_bay_id": wash_bay_id,
        "wash_level": "FLUSH",
        "window_start": "2026-08-01T06:00:00Z",
        "window_end": "2026-08-01T07:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_loading_rack_payload(**overrides) -> dict:
    defaults = {
        "rack_code": DEFAULTS["RACK_CODE"],
        "terminal_name": "Baytown",
        "authorized_groups": ["PETROLEUM"],
        "open_hour": 6,
        "close_hour": 22,
        "meter_id": DEFAULTS["METER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(customer_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "ordered_gallons": 1000,
        "route_miles": 100,
        "rate_per_gal_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def plan_shipment_payload(trailer_id: str, driver_id: str, rack_id: str, **overrides) -> dict:
    defaults = {
        "trailer_id": trailer_id,
        "driver_id": driver_id,
        "rack_id": rack_id,
        "rack_window_start": "2026-08-02T10:00:00Z",
        "rack_window_end": "2026-08-02T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def close_meter_payload(**overrides) -> dict:
    defaults = {
        "meter_start_gal": 0,
        "meter_end_gal": 1000,
        "observed_temp_F": 60,
    }
    defaults.update(overrides)
    return defaults


def record_weights_payload(**overrides) -> dict:
    defaults = {
        "steer_lb": 6600,
        "drive_lb": 12500,
        "trailer_lb": 12900,
    }
    defaults.update(overrides)
    return defaults


def confirm_placards_payload(**overrides) -> dict:
    defaults = {"observed_placard_code": "UN1993"}
    defaults.update(overrides)
    return defaults


def close_delivery_ticket_payload(**overrides) -> dict:
    defaults = {
        "delivered_observed_gal": 1000,
        "delivered_temp_F": 60,
        "retain_sample_ml": 250,
    }
    defaults.update(overrides)
    return defaults


def create_spill_plan_payload(customer_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "equipment_checklist": ["pads", "boom"],
    }
    defaults.update(overrides)
    return defaults


def create_spill_incident_payload(**overrides) -> dict:
    defaults = {
        "occurred_at": "2026-08-02T11:00:00Z",
        "gallons_spilled": 5,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(customer_id: str, trailer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "trailer_id": trailer_id,
        "committed_loads_per_month": 5,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-12-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults
