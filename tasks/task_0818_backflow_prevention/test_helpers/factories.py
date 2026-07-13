"""Payload factories — one per write endpoint, input fields only (PRD §3)."""


def connection_payload(**overrides) -> dict:
    """Body for POST /service-connections."""
    payload = {
        "account_number": "AC-DEFAULT",
        "address": "1 Main St",
        "owner_user_id": "owner-1",
        "hazard_class": "HIGH_HAZARD",
    }
    payload.update(overrides)
    return payload


def device_payload(service_connection_id, **overrides) -> dict:
    """Body for POST /devices. test_interval_months is optional (defaults to 12 server-side)."""
    payload = {
        "service_connection_id": service_connection_id,
        "serial_number": "SN-DEFAULT",
        "device_type": "RP",
        "hazard_rating": "HIGH",
        "test_interval_months": 12,
        "install_date": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def tester_payload(**overrides) -> dict:
    """Body for POST /testers."""
    payload = {
        "name": "Jane Tester",
        "certification_number": "CN-DEFAULT",
        "cert_effective_date": "2025-01-01T00:00:00Z",
        "cert_expiry_date": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def appointment_payload(device_id, tester_id, **overrides) -> dict:
    """Body for POST /test-appointments."""
    payload = {
        "device_id": device_id,
        "tester_id": tester_id,
        "scheduled_start": "2026-04-10T09:00:00Z",
        "scheduled_end": "2026-04-10T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def report_payload(device_id, tester_id, **overrides) -> dict:
    """Body for POST /test-reports. Defaults model a passing RP reading."""
    payload = {
        "device_id": device_id,
        "tester_id": tester_id,
        "test_date": "2026-02-20T00:00:00Z",
        "relief_valve_differential_psid": 2.5,
        "check_valve_1_psid": 1.5,
    }
    payload.update(overrides)
    return payload


def survey_payload(service_connection_id, **overrides) -> dict:
    """Body for POST /hazard-surveys."""
    payload = {
        "service_connection_id": service_connection_id,
        "premise_use_score": 10,
        "chemical_exposure_score": 10,
        "auxiliary_supply_score": 10,
    }
    payload.update(overrides)
    return payload


def notice_payload(service_connection_id, **overrides) -> dict:
    """Body for POST /shutoff-notices."""
    payload = {
        "service_connection_id": service_connection_id,
        "reason": "OVERDUE_TEST",
    }
    payload.update(overrides)
    return payload


def repair_order_payload(device_id, **overrides) -> dict:
    """Body for POST /repair-orders."""
    payload = {
        "device_id": device_id,
        "order_type": "REPAIR",
        "description": "reseat check valve",
    }
    payload.update(overrides)
    return payload
