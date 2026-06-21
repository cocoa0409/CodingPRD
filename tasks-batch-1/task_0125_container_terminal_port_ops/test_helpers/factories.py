"""Payload factories — one per entity, input fields only.

Each factory builds a valid create/transition payload with sensible defaults
and accepts **overrides for the values a given test needs to control.
"""

# A counter to keep naturally-unique identifiers distinct within a single test.
_seq = {"n": 0}


def _next() -> int:
    _seq["n"] += 1
    return _seq["n"]


def create_berth_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "code": f"B-{n:04d}",
        "length_m": 400,
        "draft_m": 16.0,
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "imo_number": f"{9000000 + n}",
        "name": f"Vessel {n}",
        "loa_m": 300,
        "draft_m": 14.0,
        "free_time_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_berth_window_payload(berth_id, vessel_id, **overrides) -> dict:
    defaults = {
        "berth_id": berth_id,
        "vessel_id": vessel_id,
        "eta": "2026-02-01T00:00:00.000Z",
        "etd": "2026-02-20T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(vessel_id, berth_window_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "container_number": f"TEST{n:07d}",
        "vessel_id": vessel_id,
        "berth_window_id": berth_window_id,
    }
    defaults.update(overrides)
    return defaults


def create_yard_slot_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "block": "A",
        "bay": n,
        "row": 1,
        "tier": 1,
    }
    defaults.update(overrides)
    return defaults


def create_gate_appointment_payload(container_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "container_id": container_id,
        "truck_plate": f"TRK-{n:04d}",
        "window_start": "2026-03-01T10:00:00.000Z",
        "window_end": "2026-03-01T11:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_customs_hold_payload(container_id, **overrides) -> dict:
    defaults = {
        "container_id": container_id,
        "reason": "INSPECTION",
    }
    defaults.update(overrides)
    return defaults


def ground_payload(yard_slot_id, **overrides) -> dict:
    defaults = {
        "yard_slot_id": yard_slot_id,
        "condition": "SOUND",
    }
    defaults.update(overrides)
    return defaults


def reefer_reading_payload(recorded_at, temperature_c) -> dict:
    return {"recorded_at": recorded_at, "temperature_c": temperature_c}
