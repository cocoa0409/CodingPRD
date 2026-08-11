"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_BIRTH_DATE,
    TEST_DEFAULTS,
)


def create_community_payload(**overrides) -> dict:
    """Community create payload (PRD §3.1); only `name` is required."""
    defaults = {"name": "Test Community"}
    defaults.update(overrides)
    return defaults


def create_permit_holder_payload(community_id: str, **overrides) -> dict:
    """PermitHolder self-registration payload (PRD §3.2)."""
    defaults = {
        "community_id": community_id,
        "full_name": "Test Holder",
        "birth_date": DEFAULT_BIRTH_DATE,
        "driver_license_class": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(holder_id: str, **overrides) -> dict:
    """Vehicle create payload (PRD §3.3). Defaults to a minimal GOLF_CART."""
    defaults = {
        "holder_id": holder_id,
        "vehicle_type": "GOLF_CART",
        "seat_count": 4,
        "has_headlights": True,
        "has_brake_lights": True,
        "has_turn_signals": False,
        "has_horn": False,
        "has_windshield": False,
        "has_seatbelts": False,
        "has_reflectors": False,
        "mirror_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_full_equipment_lsv_payload(holder_id: str, **overrides) -> dict:
    """LSV with all 8 equipment items present and 6 seats (PRD §3.3)."""
    defaults = {
        "holder_id": holder_id,
        "vehicle_type": "LSV",
        "seat_count": 6,
        "has_headlights": True,
        "has_brake_lights": True,
        "has_turn_signals": True,
        "has_horn": True,
        "has_windshield": True,
        "has_seatbelts": True,
        "has_reflectors": True,
        "mirror_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(vehicle_id: str, holder_id: str, **overrides) -> dict:
    """Registration create payload (PRD §3.3)."""
    defaults = {
        "vehicle_id": vehicle_id,
        "holder_id": holder_id,
        "registration_year": TEST_DEFAULTS["REGISTRATION_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(registration_id: str, **overrides) -> dict:
    """Inspection schedule payload (PRD §3.4)."""
    defaults = {
        "registration_id": registration_id,
        "scheduled_at": "2026-05-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def finalize_inspection_payload(score: int = 90, **overrides) -> dict:
    """Inspection finalize payload: uniform component scores (PRD §3.4)."""
    defaults = {
        "headlights_score": score,
        "brake_lights_score": score,
        "turn_signals_score": score,
        "horn_score": score,
        "mirrors_score": score,
        "windshield_score": score,
        "seatbelts_score": score,
        "reflectors_score": score,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(holder_id: str, vehicle_id: str, **overrides) -> dict:
    """Insurance policy create payload (PRD §3.5)."""
    defaults = {
        "holder_id": holder_id,
        "vehicle_id": vehicle_id,
        "provider_name": "Test Provider",
        "policy_number": "POL-001",
        "liability_coverage_cents": TEST_DEFAULTS["POLICY_COVERAGE_CENTS"],
        "effective_date": TEST_DEFAULTS["POLICY_EFFECTIVE_DATE"],
        "expiry_date": TEST_DEFAULTS["POLICY_EXPIRY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(community_id: str, **overrides) -> dict:
    """Route create payload (PRD §3.7)."""
    defaults = {
        "community_id": community_id,
        "name": "Main Street",
        "route_type": "STREET",
        "allowed_vehicle_class": "LSV_ALLOWED",
    }
    defaults.update(overrides)
    return defaults


def create_route_pass_payload(route_id: str, registration_id: str, holder_id: str,
                              **overrides) -> dict:
    """Route pass booking payload (PRD §3.7)."""
    defaults = {
        "route_id": route_id,
        "registration_id": registration_id,
        "holder_id": holder_id,
        "start_at": "2026-06-01T10:00:00Z",
        "end_at": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_charging_station_payload(community_id: str, **overrides) -> dict:
    """Charging station create payload (PRD §3.8)."""
    defaults = {
        "community_id": community_id,
        "name": "Station A",
        "slot_count": 2,
        "rate_cents_per_min": TEST_DEFAULTS["STATION_RATE_CENTS_PER_MIN"],
    }
    defaults.update(overrides)
    return defaults


def create_charging_reservation_payload(station_id: str, holder_id: str, **overrides) -> dict:
    """Charging reservation booking payload (PRD §3.8)."""
    defaults = {
        "station_id": station_id,
        "holder_id": holder_id,
        "slot_index": 0,
        "start_at": "2026-06-01T10:00:00Z",
        "end_at": "2026-06-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fleet_vehicle_payload(community_id: str, station_id: str, **overrides) -> dict:
    """Fleet vehicle create payload (PRD §3.8)."""
    defaults = {
        "community_id": community_id,
        "station_id": station_id,
        "label": "Fleet-1",
    }
    defaults.update(overrides)
    return defaults


def create_fleet_dispatch_payload(vehicle_id: str, holder_id: str, **overrides) -> dict:
    """Fleet dispatch booking payload (PRD §3.8)."""
    defaults = {
        "vehicle_id": vehicle_id,
        "holder_id": holder_id,
        "shift_start": "2026-06-01T10:00:00Z",
        "shift_end": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(holder_id: str, **overrides) -> dict:
    """Violation filing payload (PRD §3.9)."""
    defaults = {
        "holder_id": holder_id,
        "violation_code": "PARKING_VIOLATION",
        "points_assessed": 4,
        "fine_cents": 3000,
        "occurred_at": "2026-04-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def wallet_deposit_payload(amount_cents: int, expected_permit_holder_version: int,
                           **overrides) -> dict:
    """Wallet deposit payload (PRD §3.2, OCC-guarded per §2.7)."""
    defaults = {
        "amount_cents": amount_cents,
        "expected_permit_holder_version": expected_permit_holder_version,
    }
    defaults.update(overrides)
    return defaults
