"""Payload factories — one per create endpoint, input fields only.

Every factory returns a fresh dict and accepts **overrides so individual tests
can pin only the fields they exercise.
"""
from .constants import PACKAGE_DEFAULTS, ADDON_DEFAULTS, SIZE_MULTIPLIER_BPS


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": "cust@example.com", "full_name": "Test Customer"}
    defaults.update(overrides)
    return defaults


def create_package_payload(tier="FULL", **overrides) -> dict:
    base = dict(PACKAGE_DEFAULTS[tier])
    base["tier"] = tier
    base.update(overrides)
    return base


def create_vehicle_size_rate_payload(vehicle_size="SEDAN", **overrides) -> dict:
    defaults = {
        "vehicle_size": vehicle_size,
        "size_multiplier_bps": SIZE_MULTIPLIER_BPS[vehicle_size],
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(addon_code="ENGINE_BAY", **overrides) -> dict:
    base = dict(ADDON_DEFAULTS[addon_code])
    base["addon_code"] = addon_code
    base.update(overrides)
    return base


def create_service_bay_payload(bay_code="BAY-1", supports_ceramic=False, **overrides) -> dict:
    defaults = {"bay_code": bay_code, "supports_ceramic": supports_ceramic}
    defaults.update(overrides)
    return defaults


def create_mobile_unit_payload(unit_code="UNIT-1", travel_buffer_minutes=30, **overrides) -> dict:
    defaults = {"unit_code": unit_code, "travel_buffer_minutes": travel_buffer_minutes}
    defaults.update(overrides)
    return defaults


def create_membership_payload(customer_id, default_vehicle_size="SEDAN", **overrides) -> dict:
    defaults = {"customer_id": customer_id, "default_vehicle_size": default_vehicle_size}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(
    customer_id,
    tier="FULL",
    vehicle_size="SEDAN",
    location_mode="MOBILE",
    scheduled_start_utc="2026-06-15T09:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tier": tier,
        "vehicle_size": vehicle_size,
        "location_mode": location_mode,
        "scheduled_start_utc": scheduled_start_utc,
    }
    defaults.update(overrides)
    return defaults


def create_addon_line_payload(addon_code="ENGINE_BAY", **overrides) -> dict:
    defaults = {"addon_code": addon_code}
    defaults.update(overrides)
    return defaults


def create_photo_payload(phase="BEFORE", image_url="s3://photo.jpg", **overrides) -> dict:
    defaults = {"phase": phase, "image_url": image_url}
    defaults.update(overrides)
    return defaults


def create_rework_claim_payload(original_appointment_id, reason="defect noted", **overrides) -> dict:
    defaults = {"original_appointment_id": original_appointment_id, "reason": reason}
    defaults.update(overrides)
    return defaults
