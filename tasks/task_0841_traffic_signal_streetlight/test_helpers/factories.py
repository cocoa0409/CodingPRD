"""Payload factories — one per entity, input fields only.

Optional input fields (marked with ? in the PRD endpoint bodies) are omitted by
default and only included when passed as an override, so a caller can add them
explicitly without the factory forcing a null/default onto the request.
"""


def create_intersection_payload(**overrides) -> dict:
    defaults = {
        "name": "Main & 1st",
        "district": "D1",
        "latitude": 40.0,
        "longitude": -80.0,
    }
    defaults.update(overrides)
    return defaults


def create_pole_payload(**overrides) -> dict:
    defaults = {
        "label": "P1",
        "latitude": 40.0,
        "longitude": -80.0,
        "load_capacity_units": 100,
    }
    # intersection_id is optional (standalone streetlight poles omit it).
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {
        "intersection_id": None,
        "device_type": "SIGNAL_HEAD",
        "criticality": "STANDARD",
        "model": "M1",
        "installed_at": "2025-06-01T00:00:00Z",
        "replacement_cost": 1000.00,
        "warranty_provider": "Acme",
    }
    # pole_id is optional (non-pole-mounted units omit it).
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": "Crew A",
        "specialty": "SIGNAL",
        "labor_capacity_hours": 8.0,
    }
    defaults.update(overrides)
    return defaults


def create_pole_attachment_payload(**overrides) -> dict:
    defaults = {
        "pole_id": None,
        "attacher_name": "ISP1",
        "mount_zone": "LOW",
        "load_units": 10,
        "effective_from": "2026-04-01T00:00:00Z",
        "effective_to": "2026-05-01T00:00:00Z",
        "expected_pole_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    defaults = {
        "device_id": None,
        "source": "SRC_311",
        "reported_severity": 3,
        "description": "signal dark",
    }
    # hazard_flag and struck_pole are optional (default false); include via overrides.
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "device_id": None,
        "work_type": "REPAIR",
        "estimated_labor_hours": 1.0,
    }
    # estimated_parts, ticket_id, locate_request_id are optional; add via overrides.
    defaults.update(overrides)
    return defaults


def create_timing_change_request_payload(**overrides) -> dict:
    defaults = {
        "intersection_id": None,
        "proposed_cycle_length_sec": 90,
        "proposed_offset_sec": 10,
        "rationale": "peak tuning",
    }
    defaults.update(overrides)
    return defaults


def create_locate_request_payload(**overrides) -> dict:
    defaults = {
        "intersection_id": None,
        "requested_by": "UtilCo",
    }
    # valid_days is optional (default 21); add via overrides.
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "device_id": None,
        "defect_description": "LED flicker",
    }
    # work_order_id is optional; add via overrides.
    defaults.update(overrides)
    return defaults
