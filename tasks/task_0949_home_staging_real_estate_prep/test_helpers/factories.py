"""Payload factories — one per creatable resource, input fields only."""

from .constants import (
    ITEM_SOFA,
    TIER_SIGNATURE,
)


def create_brokerage_payload(**overrides):
    payload = {"name": "Cedar Realty", "license_code": "BR-4410"}
    payload.update(overrides)
    return payload


def create_client_payload(**overrides):
    payload = {"client_type": "SELLER", "full_name": "Dana Reyes", "email": "dana@ex.com"}
    payload.update(overrides)
    return payload


def create_property_payload(**overrides):
    payload = {
        "owner_client_id": None,
        "address_line": "18 Larch Ct",
        "city": "Bend",
        "state_code": "OR",
        "distance_miles": 22.0,
        "occupancy": "VACANT",
        "room_count": 4,
    }
    payload.update(overrides)
    return payload


def create_listing_payload(**overrides):
    payload = {
        "property_id": None,
        "listing_agent_client_id": None,
        "mls_number": "MLS-9001",
        "list_price": 749000.00,
    }
    payload.update(overrides)
    return payload


def create_package_tier_payload(**overrides):
    payload = dict(TIER_SIGNATURE)
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides):
    payload = {
        "name": "Metro Rentals",
        "lead_time_days": 7,
        "min_lease_cycles": 4,
        "cancel_cutoff_days": 4,
        "rate_multiplier": 1.35,
    }
    payload.update(overrides)
    return payload


def create_inventory_item_payload(**overrides):
    payload = dict(ITEM_SOFA)
    payload.update(overrides)
    return payload


def create_consultation_payload(**overrides):
    payload = {
        "property_id": None,
        "requested_by_client_id": None,
        "scheduled_at": "2026-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_scope_item_payload(**overrides):
    payload = {
        "room_label": "Living",
        "action": "PACKAGE_ROOM",
        "estimated_hours": 0.0,
        "requires_rental": True,
        "accessory_set_count": 0,
    }
    payload.update(overrides)
    return payload


def submit_scope_payload(**overrides):
    payload = {"recommended_tier_code": "SIGNATURE"}
    payload.update(overrides)
    return payload


def create_project_payload(**overrides):
    payload = {
        "property_id": None,
        "consultation_id": None,
        "listing_id": None,
        "package_tier_id": None,
        "payer_client_id": None,
        "payer_type": "SELLER",
    }
    payload.update(overrides)
    return payload


def create_pull_line_payload(**overrides):
    payload = {"source": "OWNED", "category": "SOFA", "room_label": "Living", "quantity": 1}
    payload.update(overrides)
    return payload


def create_rental_order_payload(**overrides):
    payload = {"project_id": None, "vendor_id": None, "unit_count": 10}
    payload.update(overrides)
    return payload


def schedule_install_payload(**overrides):
    payload = {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3, "initial_cycles": 4}
    payload.update(overrides)
    return payload


def schedule_pickup_payload(**overrides):
    payload = {"lease_id": None, "scheduled_at": "2026-10-13T09:00:00Z"}
    payload.update(overrides)
    return payload


def raise_damage_assessment_payload(**overrides):
    payload = {"pull_line_id": None, "condition_at_pickup": "MINOR", "repair_cost_estimate": 0.00}
    payload.update(overrides)
    return payload


def schedule_photo_shoot_payload(**overrides):
    payload = {"scheduled_at": "2026-06-11T10:00:00Z", "is_reshoot": False}
    payload.update(overrides)
    return payload
