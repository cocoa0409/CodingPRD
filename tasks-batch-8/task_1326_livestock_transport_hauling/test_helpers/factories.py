"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import (
    BREAK_QUALIFYING_MIN,
    BREAK_REQUIRED_AFTER_DRIVE_MIN,
    CYCLE_ON_DUTY_LIMIT_MIN,
    CYCLE_WINDOW_MIN,
    DEFAULT_CLOCK_ISO,
    DISPUTE_WINDOW_HOURS,
    DUTY_WINDOW_MIN,
    EXCESS_SHRINK_PENALTY_CENTS_PER_LB,
    FINE_BASE_CENTS,
    FINE_SEVERITY_MULT,
    HEAT_THRESHOLD_F,
    COLD_THRESHOLD_F,
    LONG_REST_MIN,
    MAX_CONFINEMENT_MIN,
    REST_UNLOAD_MIN,
    SESSION_DRIVE_LIMIT_MIN,
    SHIPPER_DEFAULT_SHRINK_PCT,
    SUSPENSION_CRITICAL_COUNT,
    WASHOUT_VALID_HOURS,
    BRAND_INSPECTION_VALID_HOURS,
    BACKHAUL_WINDOW_HOURS,
    BACKHAUL_DISCOUNT,
)

__all__ = [
    "create_shipper_payload",
    "create_driver_payload",
    "create_trailer_payload",
    "create_load_payload",
    "create_allocation_payload",
    "create_health_paper_payload",
    "create_brand_inspection_payload",
    "create_washout_payload",
    "create_weight_ticket_payload",
    "create_incident_payload",
    "create_duty_event_payload",
    "create_weather_hold_payload",
    "create_dispute_payload",
    "create_counter_payload",
    "unique_tag",
    "DEFAULT_CLOCK_ISO",
    "SESSION_DRIVE_LIMIT_MIN",
    "LONG_REST_MIN",
    "DUTY_WINDOW_MIN",
    "BREAK_REQUIRED_AFTER_DRIVE_MIN",
    "BREAK_QUALIFYING_MIN",
    "CYCLE_ON_DUTY_LIMIT_MIN",
    "CYCLE_WINDOW_MIN",
    "MAX_CONFINEMENT_MIN",
    "REST_UNLOAD_MIN",
    "WASHOUT_VALID_HOURS",
    "BRAND_INSPECTION_VALID_HOURS",
    "BACKHAUL_WINDOW_HOURS",
    "BACKHAUL_DISCOUNT",
    "EXCESS_SHRINK_PENALTY_CENTS_PER_LB",
    "DISPUTE_WINDOW_HOURS",
    "SHIPPER_DEFAULT_SHRINK_PCT",
    "FINE_BASE_CENTS",
    "FINE_SEVERITY_MULT",
    "SUSPENSION_CRITICAL_COUNT",
    "HEAT_THRESHOLD_F",
    "COLD_THRESHOLD_F",
]


def unique_tag(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_shipper_payload(**overrides) -> dict:
    defaults = {
        "name": f"Shipper-{uuid.uuid4().hex[:8]}",
        "contact_email": f"billing-{uuid.uuid4().hex[:6]}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {
        "name": f"Driver-{uuid.uuid4().hex[:8]}",
        "license_no": f"CDL-{uuid.uuid4().hex[:10]}",
    }
    defaults.update(overrides)
    return defaults


def create_trailer_payload(**overrides) -> dict:
    defaults = {
        "trailer_no": f"T-{uuid.uuid4().hex[:8]}",
        "max_gross_weight_lb": 50000,
        "compartments": [
            {"compartment_index": 1, "max_head_count": 40, "max_weight_lb": 45000},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(**overrides) -> dict:
    defaults = {
        "species": "CATTLE",
        "declared_head_count": 40,
        "declared_weight_lb": 40000,
        "origin": "Guymon OK",
        "destination": "Dodge City KS",
        "planned_departure_at": "2026-08-02T08:00:00Z",
        "planned_duration_hours": 10,
        "rate_per_loaded_mile_cents": 300,
        "loaded_miles": 500,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(**overrides) -> dict:
    defaults = {
        "head_count": 40,
        "avg_weight_lb": 1000,
        "expected_load_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_health_paper_payload(**overrides) -> dict:
    defaults = {
        "cert_number": f"CVI-{uuid.uuid4().hex[:8]}",
        "species": "CATTLE",
        "head_count_listed": 40,
        "issued_at": "2026-07-30T00:00:00Z",
        "expires_at": "2026-08-29T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_brand_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_no": f"BI-{uuid.uuid4().hex[:8]}",
        "inspected_at": "2026-08-01T06:30:00Z",
        "brand_owner": "Ranchco",
        "head_count_inspected": 40,
    }
    defaults.update(overrides)
    return defaults


def create_washout_payload(**overrides) -> dict:
    defaults = {
        "washed_at": "2026-08-01T00:30:00Z",
        "method": "HIGH_PRESSURE",
    }
    defaults.update(overrides)
    return defaults


def create_weight_ticket_payload(**overrides) -> dict:
    defaults = {
        "ticket_type": "DELIVERY",
        "gross_lb": 46000,
        "tare_lb": 6000,
        "weighed_at": "2026-08-02T15:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "incident_type": "INJURY",
        "severity": "MINOR",
        "head_count_affected": 1,
        "occurred_at": "2026-08-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_duty_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "DUTY_ON",
        "occurred_at": "2026-08-02T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_weather_hold_payload(**overrides) -> dict:
    defaults = {
        "hold_type": "HEAT",
        "temperature_f": 96,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "disputed_weight_lb": 39000,
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(**overrides) -> dict:
    defaults = {
        "counter_weight_lb": 38500,
        "expected_settlement_version": 1,
    }
    defaults.update(overrides)
    return defaults
