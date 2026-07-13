"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    TEST_DEFAULTS,
    ROUTE_START,
    ROUTE_END,
    CREDENTIAL_VALID_UNTIL,
)


def create_rate_card_payload(**overrides) -> dict:
    payload = {
        "name": "Standard Courier Rates",
        "per_stop_fee_cents": TEST_DEFAULTS["PER_STOP_FEE_CENTS"],
        "per_mile_rate_cents": TEST_DEFAULTS["PER_MILE_RATE_CENTS"],
        "stat_surcharge_pct": TEST_DEFAULTS["STAT_SURCHARGE_PCT"],
        "stat_surcharge_cap_cents": TEST_DEFAULTS["STAT_SURCHARGE_CAP_CENTS"],
        "temp_handling_fee_cents": TEST_DEFAULTS["TEMP_HANDLING_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_lab_client_payload(**overrides) -> dict:
    payload = {
        "name": "Northside Reference Lab",
        "budget_cents": TEST_DEFAULTS["LAB_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_driver_payload(**overrides) -> dict:
    payload = {
        "name": "Dana Courier",
        "credential_type": "STANDARD",
        "credential_expiry": CREDENTIAL_VALID_UNTIL,
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(**overrides) -> dict:
    payload = {
        "plate": "MED-001",
        "has_refrigeration": True,
        "sanitation_buffer_minutes": TEST_DEFAULTS["SANITATION_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_route_template_payload(lab_client_id, rate_card_id, **overrides) -> dict:
    payload = {
        "lab_client_id": lab_client_id,
        "rate_card_id": rate_card_id,
        "cadence": "WEEKDAYS",
        "default_run_type": "SCHEDULED",
        "stop_specs": [
            {"sequence": 1, "address": "A", "stop_kind": "PICKUP", "planned_leg_miles": 2.5},
            {"sequence": 2, "address": "B", "stop_kind": "DROPOFF", "planned_leg_miles": 3.5},
        ],
    }
    payload.update(overrides)
    return payload


def create_route_payload(lab_client_id, rate_card_id, **overrides) -> dict:
    payload = {
        "lab_client_id": lab_client_id,
        "rate_card_id": rate_card_id,
        "run_type": "SCHEDULED",
        "scheduled_start": ROUTE_START,
        "scheduled_end": ROUTE_END,
        "planned_total_miles": TEST_DEFAULTS["PLANNED_TOTAL_MILES"],
    }
    payload.update(overrides)
    return payload


def create_stop_payload(**overrides) -> dict:
    payload = {
        "sequence": 1,
        "address": "A",
        "stop_kind": "PICKUP",
        "planned_leg_miles": 2.5,
    }
    payload.update(overrides)
    return payload


def create_specimen_payload(pickup_stop_id, dropoff_stop_id, **overrides) -> dict:
    payload = {
        "pickup_stop_id": pickup_stop_id,
        "dropoff_stop_id": dropoff_stop_id,
        "specimen_type": "BLOOD",
        "temp_requirement": "REFRIGERATED",
        "required_temp_min_c": 2,
        "required_temp_max_c": 8,
    }
    payload.update(overrides)
    return payload


def assign_route_payload(driver_id, vehicle_id, **overrides) -> dict:
    payload = {"driver_id": driver_id, "vehicle_id": vehicle_id}
    payload.update(overrides)
    return payload


def scan_payload(specimen_id, scan_type, temp_reading_c, leg_miles, **overrides) -> dict:
    payload = {
        "specimen_id": specimen_id,
        "scan_type": scan_type,
        "temp_reading_c": temp_reading_c,
        "leg_miles": leg_miles,
    }
    payload.update(overrides)
    return payload


def credential_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def billing_payload(expected_route_version, **overrides) -> dict:
    payload = {"expected_route_version": expected_route_version}
    payload.update(overrides)
    return payload
