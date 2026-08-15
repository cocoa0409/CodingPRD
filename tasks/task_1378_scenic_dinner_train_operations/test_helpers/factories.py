"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "host_railroad_name": "Host Line RR",
        "subdivision_code": "SUB-7",
        "valid_from": TEST_DEFAULTS["VALID_FROM"],
        "valid_until": TEST_DEFAULTS["VALID_UNTIL"],
        "max_trains_per_day": TEST_DEFAULTS["MAX_TRAINS_PER_DAY"],
        "min_slot_minutes": TEST_DEFAULTS["MIN_SLOT_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "service_date": TEST_DEFAULTS["SERVICE_DATE"],
        "start_minute": TEST_DEFAULTS["SLOT_START_MINUTE"],
        "end_minute": TEST_DEFAULTS["SLOT_END_MINUTE"],
    }
    defaults.update(overrides)
    return defaults


def create_rolling_stock_payload(**overrides) -> dict:
    defaults = {
        "unit_code": "LOC-1",
        "stock_type": "LOCOMOTIVE",
        "seat_capacity": 0,
        "table_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(stock_id: str, **overrides) -> dict:
    defaults = {
        "stock_id": stock_id,
        "window_start": "2026-10-20T09:00:00Z",
        "window_end": "2026-10-20T11:00:00Z",
        "scope": "INSPECTION",
    }
    defaults.update(overrides)
    return defaults


def create_excursion_payload(slot_id: str, **overrides) -> dict:
    defaults = {
        "title": "Test Run",
        "slot_id": slot_id,
        "event_type": "REGULAR",
        "surge_multiplier_bp": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_car_assignment_payload(excursion_id: str, stock_id: str, class_code: str,
                                  position: int, **overrides) -> dict:
    defaults = {
        "excursion_id": excursion_id,
        "stock_id": stock_id,
        "class_code": class_code,
        "position": position,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(excursion_id: str, customer_email: str, class_code: str,
                           party_size: int, dining_service=None, **overrides) -> dict:
    payload = {
        "excursion_id": excursion_id,
        "customer_email": customer_email,
        "class_code": class_code,
        "party_size": party_size,
    }
    # dining_service is required exactly when class_code is DINING (PRD §3.5);
    # the key is included only when a value is supplied.
    if dining_service is not None:
        payload["dining_service"] = dining_service
    payload.update(overrides)
    return payload


def create_crew_member_payload(name: str, role: str, is_volunteer: bool = False,
                               cert_expires_on=None, **overrides) -> dict:
    payload = {
        "name": name,
        "role": role,
        "is_volunteer": is_volunteer,
    }
    # cert_expires_on must be null for non-certificate roles (PRD §3.3);
    # the key is included only when a value is supplied.
    if cert_expires_on is not None:
        payload["cert_expires_on"] = cert_expires_on
    payload.update(overrides)
    return payload


def create_crew_assignment_payload(excursion_id: str, crew_member_id: str,
                                   position: str, **overrides) -> dict:
    defaults = {
        "excursion_id": excursion_id,
        "crew_member_id": crew_member_id,
        "position": position,
    }
    defaults.update(overrides)
    return defaults
