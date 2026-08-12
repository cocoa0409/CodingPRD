"""Payload factories — one per creatable entity, input fields only.

Each test runs against a freshly restarted server with an empty database, so
counter-suffixed defaults are unique within any single test.
"""
import itertools

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_patient_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Test Patient {n}",
        "date_of_birth": "1960-01-01",
        "mrn": f"MRN-{9000 + n}",
        "phone": f"555-{1000 + (n % 9000)}",
        "insurance_plan": "MEDICARE",
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Dr Test {n}",
        "npi": f"{1000000000 + n}",  # exactly 10 digits
        "specialty": "CARDIOLOGY",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Tech Test {n}",
        "certification_level": "CCT",
        "shift_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "serial_number": f"EV-{9000 + n}",
        "model": "EVENT",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "monitor_type": "EVENT",
        "prescribed_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(device_id: str, expected_order_version: int, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_transmission_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "seq_no": n,
        "bytes_received": 1024,
        "signal_quality": 80,
    }
    defaults.update(overrides)
    return defaults


def create_alert_payload(**overrides) -> dict:
    defaults = {
        "severity": "ROUTINE",
        "arrhythmia_type": "AFIB",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "report_type": "INTERIM",
        "findings_summary": "Routine findings.",
    }
    defaults.update(overrides)
    return defaults


def propose_adjustment_payload(**overrides) -> dict:
    defaults = {
        "delta_cents": 100,
        "reason": "Documentation adjustment",
    }
    defaults.update(overrides)
    return defaults
