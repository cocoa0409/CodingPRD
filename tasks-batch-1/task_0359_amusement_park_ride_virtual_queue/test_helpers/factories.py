"""Payload factories — one per entity, input fields only."""
from .constants import OPERATING_DATE


def create_park_payload(**overrides) -> dict:
    """Input fields for POST /parks. peak_threshold_pct is optional (default 0.85)."""
    defaults = {
        "name": "Test Park",
        "gate_capacity": 100,
        "operating_date": OPERATING_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_ride_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/rides.
    min_height_cm, wheelchair_transfer_required, single_rider_enabled are optional."""
    defaults = {
        "name": "Test Ride",
        "hourly_throughput": 100,
    }
    defaults.update(overrides)
    return defaults


def create_return_window_payload(**overrides) -> dict:
    """Input fields for POST /rides/{id}/return-windows."""
    defaults = {
        "window_start_utc": "2026-06-15T10:00:00.000Z",
        "window_end_utc": "2026-06-15T11:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/guests. uses_wheelchair is optional (default false)."""
    defaults = {
        "full_name": "Test Guest",
        "height_cm": 170,
    }
    defaults.update(overrides)
    return defaults


def create_day_ticket_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/day-tickets."""
    defaults = {
        "guest_id": None,
        "ticket_date": OPERATING_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_party_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/parties."""
    defaults = {
        "leader_guest_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_entitlement_plan_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/entitlement-plans. surge_multiplier optional (default 1.0)."""
    defaults = {
        "tier": "MULTI_PASS",
        "price_cents": 1500,
        "max_concurrent_holds": 3,
    }
    defaults.update(overrides)
    return defaults


def create_lightning_lane_purchase_payload(**overrides) -> dict:
    """Input fields for POST /lightning-lane-purchases."""
    defaults = {
        "park_id": None,
        "guest_id": None,
        "ride_id": None,
        "plan_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    """Input fields for POST /reservations."""
    defaults = {
        "ride_id": None,
        "guest_id": None,
        "return_window_id": None,
        "queue_type": "VIRTUAL_QUEUE",
        "expected_return_window_id_version": None,
    }
    defaults.update(overrides)
    return defaults
