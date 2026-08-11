"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from . import constants as C


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Green Acres",
        "billing_email": "g1@farm.test",
        "rate_per_acre_cents": 1200,
        "credit_limit_cents": 2000000,
    }
    defaults.update(overrides)
    return defaults


def create_field_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "label": "North 40",
        "crop": "CORN",
        "acres": 100,
        "buffer_clearance_ft": 300,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "name": "WeedOut",
        "epa_registration_no": "EPA-100-1",
        "category": "HERBICIDE",
        "rei_hours": 24,
        "max_wind_mph": 10,
        "min_temp_f": 40,
        "max_temp_f": 85,
        "required_buffer_ft": 100,
        "unit_cost_cents": 5000,
        "markup_pct": 10,
    }
    defaults.update(overrides)
    return defaults


def create_product_p2_payload(**overrides) -> dict:
    defaults = {
        "name": "FungiStop",
        "epa_registration_no": "EPA-200-2",
        "category": "FUNGICIDE",
        "rei_hours": 48,
        "max_wind_mph": 15,
        "min_temp_f": 50,
        "max_temp_f": 90,
        "required_buffer_ft": 0,
        "unit_cost_cents": 2500,
        "markup_pct": 20,
    }
    defaults.update(overrides)
    return defaults


def create_compatibility_rule_payload(product_a_id: str, product_b_id: str,
                                      verdict: str, **overrides) -> dict:
    defaults = {
        "product_a_id": product_a_id,
        "product_b_id": product_b_id,
        "verdict": verdict,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(field_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "field_id": field_id,
        "season_year": 2026,
        "valid_from": C.RX_VALID_FROM,
        "valid_to": C.RX_VALID_TO,
        "carrier_gpa": 12,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_applicator_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Ann Applicator",
        "license_no": "L-100",
        "license_expires_on": C.LICENSE_EXPIRES_FAR,
        "license_categories": ["HERBICIDE", "FUNGICIDE"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "unit_label": "Sprayer-1",
        "tank_capacity_gal": 400,
    }
    defaults.update(overrides)
    return defaults


def create_calibration_record_payload(equipment_id: str, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "target_gpa": 20.0,
        "measured_gpa": 20.5,
    }
    defaults.update(overrides)
    return defaults


def create_weather_observation_payload(**overrides) -> dict:
    defaults = {
        "observed_at": C.WEATHER_OBSERVED_AT,
        "wind_mph": 8,
        "temp_f": 65,
        "inversion_present": False,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id: str, field_id: str,
                              prescription_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "field_id": field_id,
        "prescription_id": prescription_id,
        "acres_to_treat": 100,
    }
    defaults.update(overrides)
    return defaults


def schedule_work_order_payload(applicator_id: str, equipment_id: str, **overrides) -> dict:
    defaults = {
        "applicator_id": applicator_id,
        "equipment_id": equipment_id,
        "scheduled_start": C.WO_SCHEDULED_START,
        "scheduled_end": C.WO_SCHEDULED_END,
    }
    defaults.update(overrides)
    return defaults


def create_rinsate_record_payload(work_order_id: str, kind: str,
                                  volume_gal: float, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "kind": kind,
        "volume_gal": volume_gal,
    }
    defaults.update(overrides)
    return defaults


def create_drift_complaint_payload(work_order_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "description": "Spray drift observed on neighboring property",
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults
