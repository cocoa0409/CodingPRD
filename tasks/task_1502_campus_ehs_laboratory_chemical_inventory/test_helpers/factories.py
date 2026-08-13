"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import DOCK_ID, DOCK_WINDOW_END, DOCK_WINDOW_START, FUTURE_TRAINING_DUE

_counter = itertools.count(1)


def create_lab_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "name": f"Lab {n}",
        "department": "Chemistry",
        "building": "Hall A",
        "room": "101",
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(lab_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "lab_id": lab_id,
        "full_name": f"Worker {n}",
        "role_in_lab": "RESEARCHER",
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(lab_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "lab_id": lab_id,
        "barcode": f"BC-{n}",
        "chemical_name": f"Chemical {n}",
        "hazard_class": "FLAMMABLE",
        "quantity_value": 1.0,
        "quantity_unit": "GAL",
    }
    defaults.update(overrides)
    return defaults


def create_area_payload(lab_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "lab_id": lab_id,
        "name": f"SAA-{n}",
        "area_type": "SAA",
        "capacity_containers": 10,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_payload(lab_id: str, **overrides) -> dict:
    defaults = {"lab_id": lab_id}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(lab_id: str, **overrides) -> dict:
    defaults = {
        "lab_id": lab_id,
        "inspector_id": "insp-1",
        "scheduled_start": "2026-08-05T09:00:00Z",
        "scheduled_end": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_training_payload(lab_id: str, worker_id: str, **overrides) -> dict:
    defaults = {
        "lab_id": lab_id,
        "worker_id": worker_id,
        "hazard_class": "FLAMMABLE",
        "due_date": FUTURE_TRAINING_DUE,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(lab_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "lab_id": lab_id,
        "title": f"Incident {n}",
        "description": "spill observed and contained",
        "severity": "LOW",
        "near_miss": False,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(lab_id: str, expected_lab_version: int, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "lab_id": lab_id,
        "material_type": "CONTROLLED_SUBSTANCE",
        "registration_number": f"REG-{n}",
        "expected_lab_version": expected_lab_version,
    }
    defaults.update(overrides)
    return defaults


def schedule_window_payload(**overrides) -> dict:
    defaults = {
        "dock_id": DOCK_ID,
        "window_start": DOCK_WINDOW_START,
        "window_end": DOCK_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def finding(severity: str, description: str) -> dict:
    return {"severity": severity, "description": description}
