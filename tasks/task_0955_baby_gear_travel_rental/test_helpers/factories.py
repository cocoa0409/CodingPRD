"""Payload factories — one per entity, input fields only (PRD section 3)."""
import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": f"customer-{_suffix()}@example.com",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_catalog_item_payload(**overrides) -> dict:
    defaults = {
        "name": f"Deluxe Crib {_suffix()}",
        "category": "CRIB",
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "deposit_amount_cents": TEST_DEFAULTS["DEPOSIT_AMOUNT_CENTS"],
        "weight_kg": TEST_DEFAULTS["WEIGHT_KG"],
        "cleaning_turnaround_hours": TEST_DEFAULTS["CLEANING_TURNAROUND_HOURS"],
        "deep_clean_every_cycles": TEST_DEFAULTS["DEEP_CLEAN_EVERY_CYCLES"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(catalog_item_id: str, **overrides) -> dict:
    defaults = {
        "catalog_item_id": catalog_item_id,
        "serial_number": f"SN-{_suffix()}",
        "condition_grade": "A",
    }
    defaults.update(overrides)
    return defaults


def create_hotel_partner_payload(**overrides) -> dict:
    defaults = {
        "name": f"Grand Hotel {_suffix()}",
        "zone_code": TEST_DEFAULTS["ZONE"],
        "commission_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_plan_payload(**overrides) -> dict:
    defaults = {
        "code": f"PLAN-{_suffix()}",
        "pricing_model": "PER_DAY",
        "rate_value": 200,
        "deductible_cents": 500,
        "coverage_cap_cents": 10000,
        "covered_severities": ["MINOR"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(lines, **overrides) -> dict:
    defaults = {
        "delivery_address": "1 Main St",
        "zone_code": TEST_DEFAULTS["ZONE"],
        "start_date": TEST_DEFAULTS["START_DATE"],
        "end_date": TEST_DEFAULTS["END_DATE"],
        "lines": lines,
    }
    for optional_key in ("hotel_partner_id", "insurance_plan_id"):
        if overrides.get(optional_key) is not None:
            defaults[optional_key] = overrides.pop(optional_key)
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_date": TEST_DEFAULTS["START_DATE"],
        "zone_code": TEST_DEFAULTS["ZONE"],
        "vehicle_capacity_kg": TEST_DEFAULTS["VEHICLE_CAPACITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(reservation_id: str, stop_type: str, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "stop_type": stop_type,
        "address": "1 Main St",
        "time_window_start": "2026-06-10T08:00:00Z",
        "time_window_end": "2026-06-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(catalog_item_id: str, **overrides) -> dict:
    defaults = {
        "catalog_item_id": catalog_item_id,
        "recall_code": f"RC-{_suffix()}",
        "severity": "MANDATORY",
        "description": "manufacturer safety defect",
    }
    defaults.update(overrides)
    return defaults


def create_cleaning_ticket_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "ticket_type": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(reservation_line_id: str, **overrides) -> dict:
    defaults = {
        "reservation_line_id": reservation_line_id,
        "severity": "MINOR",
        "repair_cost_cents": 5000,
        "description": "damage found on inspection",
    }
    defaults.update(overrides)
    return defaults
