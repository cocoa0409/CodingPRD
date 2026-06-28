"""Payload factories — one per entity, input fields only."""
import itertools

# Monotonic counter to keep unique fields (doctor email, material code) distinct
# across repeated factory calls within a single test.
_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def create_doctor_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Dr Test {n}",
        "practice_name": "Test Practice",
        "email": f"doctor{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "code": f"MAT{n}",
        "name": "Test Material",
        "base_unit_price_cents": 12000,
        "fabrication_process": "MILLED",
    }
    defaults.update(overrides)
    return defaults


def create_mill_machine_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Mill-{n}",
        "capability": "MILLED",
    }
    defaults.update(overrides)
    return defaults


def create_courier_route_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "label": f"Route {n}",
        "service_date": "2026-01-06T00:00:00Z",
        "max_stops": 10,
        "buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(doctor_id: str, **overrides) -> dict:
    defaults = {
        "doctor_id": doctor_id,
        "intake_method": "INTRAORAL_SCAN",
    }
    defaults.update(overrides)
    return defaults


def create_restoration_payload(material_id: str, **overrides) -> dict:
    defaults = {
        "material_id": material_id,
        "restoration_type": "CROWN",
        "unit_count": 1,
        "requested_shade": "A2",
    }
    defaults.update(overrides)
    return defaults


def create_mill_job_payload(fabrication_unit_id: str, mill_machine_id: str, **overrides) -> dict:
    defaults = {
        "fabrication_unit_id": fabrication_unit_id,
        "mill_machine_id": mill_machine_id,
        "start_at": "2026-01-01T01:00:00Z",
        "duration_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(courier_route_id: str, case_id: str, **overrides) -> dict:
    defaults = {
        "courier_route_id": courier_route_id,
        "case_id": case_id,
        "window_start_at": "2026-01-02T09:00:00Z",
        "window_minutes": 20,
    }
    defaults.update(overrides)
    return defaults


def tryin_verdict_payload(verdict: str, expected_case_version: int, **overrides) -> dict:
    defaults = {
        "verdict": verdict,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_remake_request_payload(fabrication_unit_id: str, reason: str = "FRACTURE",
                                  **overrides) -> dict:
    defaults = {
        "fabrication_unit_id": fabrication_unit_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
