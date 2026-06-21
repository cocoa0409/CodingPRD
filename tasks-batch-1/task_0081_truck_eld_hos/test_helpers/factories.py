"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

# Monotonic counters so concurrently-built payloads get unique business keys
# within a single test (each test runs against a fresh DB).
_license_seq = itertools.count(1)
_unit_seq = itertools.count(1)
_serial_seq = itertools.count(1)


def unique_license() -> str:
    return f"CDL-{next(_license_seq):06d}"


def unique_unit() -> str:
    return f"UNIT-{next(_unit_seq):06d}"


def unique_serial() -> str:
    return f"SER-{next(_serial_seq):06d}"


def create_driver_payload(**overrides) -> dict:
    """POST /eld/drivers body. Required: license_number, full_name."""
    defaults = {
        "license_number": unique_license(),
        "full_name": "Test Driver",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    """POST /eld/vehicles body. Required: unit_number, vin."""
    unit = overrides.pop("unit_number", unique_unit())
    defaults = {
        "unit_number": unit,
        "vin": f"VIN-{unit}",
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(vehicle_id, **overrides) -> dict:
    """POST /eld/devices body. Required: serial_number, vehicle_id."""
    defaults = {
        "serial_number": unique_serial(),
        "vehicle_id": vehicle_id,
    }
    defaults.update(overrides)
    return defaults


def create_duty_event_payload(driver_id, device_id, duty_status, event_time,
                              expected_driver_version, **overrides) -> dict:
    """POST /eld/duty-events body.

    Required: driver_id, device_id, duty_status, event_time, expected_driver_version.
    Optional: special_driving_category, edited_from_event_id, annotation.
    """
    defaults = {
        "driver_id": driver_id,
        "device_id": device_id,
        "duty_status": duty_status,
        "event_time": event_time,
        "expected_driver_version": expected_driver_version,
    }
    defaults.update(overrides)
    return defaults


def create_daily_log_payload(driver_id, log_date, **overrides) -> dict:
    """POST /eld/daily-logs body. Required: driver_id, log_date."""
    defaults = {"driver_id": driver_id, "log_date": log_date}
    defaults.update(overrides)
    return defaults


def create_adverse_claim_payload(driver_id, log_date, reason="WEATHER",
                                 narrative="Adverse conditions on route.", **overrides) -> dict:
    """POST /eld/adverse-claims body. Required: driver_id, log_date, reason, narrative."""
    defaults = {
        "driver_id": driver_id,
        "log_date": log_date,
        "reason": reason,
        "narrative": narrative,
    }
    defaults.update(overrides)
    return defaults


def mark_error_payload(expected_dutystatusevent_version) -> dict:
    """POST /eld/duty-events/{id}/mark-error body."""
    return {"expected_dutystatusevent_version": expected_dutystatusevent_version}


def approve_claim_payload(expected_adverseconditionsclaim_version) -> dict:
    """POST /eld/adverse-claims/{id}/approve body."""
    return {"expected_adverseconditionsclaim_version": expected_adverseconditionsclaim_version}


def resolve_violation_payload(resolution_note="Reviewed and resolved.") -> dict:
    """POST /eld/hos-violations/{id}/resolve body."""
    return {"resolution_note": resolution_note}
