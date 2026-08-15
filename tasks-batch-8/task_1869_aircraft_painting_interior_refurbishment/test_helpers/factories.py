"""Payload factories — one per creatable entity, input fields only (PRD §4)."""
from .constants import FIXTURE


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": FIXTURE["CUSTOMER_NAME"],
        "contact_email": FIXTURE["CUSTOMER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "tail_number": FIXTURE["TAIL_NUMBER"],
        "model": FIXTURE["AIRCRAFT_MODEL"],
        "max_delta_lbs": FIXTURE["MAX_DELTA_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "aircraft_id": None,
        "customer_id": None,
        "base_price_cents": FIXTURE["BASE_PRICE_CENTS"],
        "daily_penalty_rate_cents": FIXTURE["DAILY_PENALTY_RATE_CENTS"],
        "penalty_cap_pct": FIXTURE["PENALTY_CAP_PCT"],
        "contractual_delivery_date": FIXTURE["CONTRACTUAL_DELIVERY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_paint_scheme_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "drawing_ref": FIXTURE["DRAWING_REF"],
        "painted_area_sqft": FIXTURE["PAINTED_AREA_SQFT"],
        "coat_count": FIXTURE["COAT_COUNT"],
        "stripe_pct": FIXTURE["STRIPE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_surface_assessment_payload(**overrides) -> dict:
    defaults = {"program_id": None}
    defaults.update(overrides)
    return defaults


def decide_assessment_payload(**overrides) -> dict:
    defaults = {"decision": "STRIP", "corrosion_severity": "NONE"}
    defaults.update(overrides)
    return defaults


def create_discovery_item_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "description": "Discovery work item",
    }
    defaults.update(overrides)
    return defaults


def estimate_discovery_payload(**overrides) -> dict:
    defaults = {"est_cost_cents": 250000, "est_hours": 40}
    defaults.update(overrides)
    return defaults


def complete_discovery_payload(**overrides) -> dict:
    defaults = {"actual_cost_cents": 250000}
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "delta_price_cents": 600000,
        "delta_days": 0,
        "description": "Scope change",
    }
    defaults.update(overrides)
    return defaults


def create_hangar_bay_payload(**overrides) -> dict:
    defaults = {
        "name": FIXTURE["BAY_NAME"],
        "daily_rate_cents": FIXTURE["BAY_DAILY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_hangar_slot_payload(**overrides) -> dict:
    defaults = {
        "bay_id": None,
        "program_id": None,
        "start_at": FIXTURE["SLOT_START"],
        "end_at": FIXTURE["SLOT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_paint_booth_payload(**overrides) -> dict:
    defaults = {
        "name": FIXTURE["BOOTH_NAME"],
        "hourly_rate_cents": FIXTURE["BOOTH_HOURLY_RATE_CENTS"],
        "cure_buffer_hours": FIXTURE["BOOTH_CURE_BUFFER_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_booth_booking_payload(**overrides) -> dict:
    defaults = {
        "booth_id": None,
        "program_id": None,
        "start_at": FIXTURE["BOOTH_WINDOW_START"],
        "end_at": FIXTURE["BOOTH_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_soft_good_lot_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "description": "Seat covers",
        "material": "Leather",
        "quantity": 8,
        "estimated_weight_lbs": 96.0,
    }
    defaults.update(overrides)
    return defaults


def record_burn_test_payload(**overrides) -> dict:
    defaults = {
        "test_method": "VERTICAL_12S",
        "result": "PASS",
        "lab_name": FIXTURE["LAB_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_weight_record_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "scheme_id": None,
        "variant": "FINAL",
        "removal_weight_lbs": 100.0,
        "installed_weight_lbs": 108.0,
    }
    defaults.update(overrides)
    return defaults


def create_quality_inspection_payload(**overrides) -> dict:
    defaults = {"program_id": None, "inspection_type": "PAINT"}
    defaults.update(overrides)
    return defaults


def record_inspection_result_payload(**overrides) -> dict:
    defaults = {"result": "PASS", "major_defects": 0, "minor_defects": 0}
    defaults.update(overrides)
    return defaults


def create_delay_event_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "category": "CUSTOMER_CAUSED",
        "impact_days": 3,
        "reason": "Schedule impact",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {"program_id": None, "kind": "DEPOSIT"}
    defaults.update(overrides)
    return defaults
