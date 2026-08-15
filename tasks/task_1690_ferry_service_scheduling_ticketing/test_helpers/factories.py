"""Payload factories — one per entity, input fields only (per PRD §3/§4)."""
import uuid

DEFAULTS = {
    "ROUTE_CODE": "SEA-BI",
    "ORIGIN_TERMINAL": "Seattle",
    "DESTINATION_TERMINAL": "Bainbridge",
    "CROSSING_MINUTES": 35,
    "TURNAROUND_MINUTES": 15,
    "VESSEL_DECK_FEET": 200,
    "VESSEL_PASSENGER_CAPACITY": 600,
    "CREW_CLASS": "MEDIUM",
    "SEASON": "OFF_PEAK",
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_TO": "2026-11-01T00:00:00Z",
    "PASSENGER_STANDARD_CENTS": 1000,
    "PASSENGER_RESIDENT_CENTS": 800,
    "PASSENGER_COMMUTER_CENTS": 600,
    "VEHICLE_STANDARD_BASE_CENTS": 2000,
    "VEHICLE_OVERSIZE_BASE_CENTS": 4000,
    "VEHICLE_OVERLENGTH_PER_FOOT_CENTS": 100,
    "DEPARTURE_TIME": "2026-09-01T10:00:00Z",
    "FARE_CLASS": "STANDARD",
    "CREDENTIAL_CLASS": "CAPTAIN",
    "PRIORITY_CLASS": "STANDARD",
}


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": _uniq(DEFAULTS["ROUTE_CODE"]),
        "origin_terminal": DEFAULTS["ORIGIN_TERMINAL"],
        "destination_terminal": DEFAULTS["DESTINATION_TERMINAL"],
        "crossing_minutes": DEFAULTS["CROSSING_MINUTES"],
        "turnaround_minutes": DEFAULTS["TURNAROUND_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "vessel_name": _uniq("MV"),
        "vehicle_deck_linear_feet": DEFAULTS["VESSEL_DECK_FEET"],
        "passenger_capacity": DEFAULTS["VESSEL_PASSENGER_CAPACITY"],
        "crew_class": DEFAULTS["CREW_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_fare_schedule_payload(**overrides) -> dict:
    defaults = {
        "season": DEFAULTS["SEASON"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
        "passenger_standard_cents": DEFAULTS["PASSENGER_STANDARD_CENTS"],
        "passenger_resident_cents": DEFAULTS["PASSENGER_RESIDENT_CENTS"],
        "passenger_commuter_cents": DEFAULTS["PASSENGER_COMMUTER_CENTS"],
        "vehicle_standard_base_cents": DEFAULTS["VEHICLE_STANDARD_BASE_CENTS"],
        "vehicle_oversize_base_cents": DEFAULTS["VEHICLE_OVERSIZE_BASE_CENTS"],
        "vehicle_overlength_per_foot_cents": DEFAULTS["VEHICLE_OVERLENGTH_PER_FOOT_CENTS"],
        "fuel_surcharge_cents": 0,
        "expected_route_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_sailing_payload(**overrides) -> dict:
    defaults = {
        "vessel_id": None,
        "departure_time": DEFAULTS["DEPARTURE_TIME"],
        "season": DEFAULTS["SEASON"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Pat"),
        "email": f"{_uniq('pat')}@example.com",
        "fare_class": DEFAULTS["FARE_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "passenger_count": 1,
        "has_vehicle": False,
    }
    defaults.update(overrides)
    return defaults


def create_standby_entry_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "has_vehicle": False,
        "passenger_count": 1,
        "priority_class": DEFAULTS["PRIORITY_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Crew"),
        "credential_class": DEFAULTS["CREDENTIAL_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(**overrides) -> dict:
    defaults = {
        "crew_member_id": None,
        "shift_start": "2026-09-01T08:00:00Z",
        "shift_end": "2026-09-01T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults
