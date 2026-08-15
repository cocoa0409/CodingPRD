"""Payload factories — one per entity, caller-supplied (input) fields only.

Server-stamped and server-computed fields (ids, timestamps, statuses,
decay constants, possession totals, required/residual activities, ...) are
never placed into request payloads here.
"""
from .constants import F18_PARAMS, T_ADMIN, T_AU_EXPIRY, T_LICENSE_EXPIRY, TEST_DEFAULTS


def create_isotope_product_payload(**overrides) -> dict:
    defaults = dict(F18_PARAMS)
    defaults.update(overrides)
    return defaults


def create_license_payload(isotope_product_id: str, **overrides) -> dict:
    defaults = {
        "license_number": TEST_DEFAULTS["LICENSE_NUMBER"],
        "max_possession_mbq": TEST_DEFAULTS["LICENSE_MAX_POSSESSION_MBQ"],
        "isotope_conditions": [
            {
                "isotope_product_id": isotope_product_id,
                "max_possession_mbq": TEST_DEFAULTS["CONDITION_MAX_POSSESSION_MBQ"],
                "allowed_use": "BOTH",
            }
        ],
        "expires_at": T_LICENSE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_authorized_user_payload(license_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Dr. A",
        "license_id": license_id,
        "scope": "BOTH",
        "expires_at": T_AU_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": TEST_DEFAULTS["PATIENT_NAME"],
        "weight_kg": TEST_DEFAULTS["PATIENT_WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_imaging_room_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["ROOM_NAME"],
        "cleanup_buffer_minutes": TEST_DEFAULTS["ROOM_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_isotope_delivery_payload(isotope_product_id: str, **overrides) -> dict:
    defaults = {
        "isotope_product_id": isotope_product_id,
        "scheduled_arrival_at": "2026-08-01T08:00:00Z",
        "reference_activity_mbq": TEST_DEFAULTS["DELIVERY_REFERENCE_MBQ"],
        "reference_time_at": "2026-08-01T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_dose_order_payload(patient_id: str, isotope_product_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "isotope_product_id": isotope_product_id,
        "use_type": "DIAGNOSTIC",
        "prescribed_activity_mbq": TEST_DEFAULTS["PRESCRIBED_ACTIVITY_MBQ"],
        "administration_scheduled_at": T_ADMIN,
    }
    defaults.update(overrides)
    return defaults


def create_dose_vial_payload(order_id: str, delivery_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "delivery_id": delivery_id,
    }
    defaults.update(overrides)
    return defaults


def create_procedure_appointment_payload(order_id: str, room_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "room_id": room_id,
        "start_at": "2026-08-01T10:00:00Z",
        "end_at": "2026-08-01T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_waste_container_payload(isotope_product_id: str, room_id: str, **overrides) -> dict:
    defaults = {
        "isotope_product_id": isotope_product_id,
        "room_id": room_id,
    }
    defaults.update(overrides)
    return defaults


def create_radiation_survey_payload(room_id: str, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "ambient_dose_rate_usv_h": 0.5,
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_spill_incident_payload(room_id: str, isotope_product_id: str, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "isotope_product_id": isotope_product_id,
        "estimated_activity_mbq": 10,
        "occurred_at": "2026-08-01T08:45:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_patient_release_instruction_payload(administration_id: str, **overrides) -> dict:
    defaults = {
        "administration_id": administration_id,
        "evaluation_variant": "ACTIVITY_BASED",
    }
    defaults.update(overrides)
    return defaults
