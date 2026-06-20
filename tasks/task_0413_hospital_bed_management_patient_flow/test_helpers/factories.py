"""Payload factories — one per entity, input fields only (PRD Section 3)."""


def create_unit_payload(**overrides) -> dict:
    """Input fields for POST /units: name, unit_type, gmlos_days? (default 3)."""
    defaults = {"name": "Test Unit", "unit_type": "MEDSURG"}
    defaults.update(overrides)
    return defaults


def create_bed_payload(unit_id: str, **overrides) -> dict:
    """Input for POST /units/{id}/beds: unit_id, label, room_type?,
    isolation_capable?, telemetry_capable?."""
    defaults = {"unit_id": unit_id, "label": "Test-Bed"}
    defaults.update(overrides)
    return defaults


def create_block_payload(blocked_reason: str = "MAINTENANCE", **overrides) -> dict:
    """Input for POST /units/{id}/beds/{bedId}/block: blocked_reason."""
    defaults = {"blocked_reason": blocked_reason}
    defaults.update(overrides)
    return defaults


def create_encounter_payload(**overrides) -> dict:
    """Input for POST /encounters: mrn, sex, requires_isolation?,
    requires_telemetry?, origin? (default ED)."""
    defaults = {"mrn": "M-TEST", "sex": "MALE"}
    defaults.update(overrides)
    return defaults


def create_transfer_payload(target_bed_id: str, **overrides) -> dict:
    """Input for POST /encounters/{id}/transfer: target_bed_id."""
    defaults = {"target_bed_id": target_bed_id}
    defaults.update(overrides)
    return defaults


def create_bed_request_payload(encounter_id: str, **overrides) -> dict:
    """Input for POST /bed-requests: encounter_id, preferred_unit_id?,
    acceptable_unit_types?, priority? (default ROUTINE)."""
    defaults = {"encounter_id": encounter_id}
    defaults.update(overrides)
    return defaults


def create_assign_payload(bed_id: str, **overrides) -> dict:
    """Input for POST /bed-requests/{id}/assign: bed_id."""
    defaults = {"bed_id": bed_id}
    defaults.update(overrides)
    return defaults


def create_confirm_payload(expected_bed_version: int, **overrides) -> dict:
    """Input for POST /bed-requests/{id}/confirm: expected_bed_version (required)."""
    defaults = {"expected_bed_version": expected_bed_version}
    defaults.update(overrides)
    return defaults


def create_evs_task_payload(bed_id: str, **overrides) -> dict:
    """Input for POST /evs-tasks: bed_id, task_type? (default ROUTINE)."""
    defaults = {"bed_id": bed_id}
    defaults.update(overrides)
    return defaults


def create_evs_assign_payload(**overrides) -> dict:
    """Input for POST /evs-tasks/{id}/assign: tech_id? (optional)."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_discharge_barrier_payload(encounter_id: str, barrier_type: str, **overrides) -> dict:
    """Input for POST /discharge-barriers: encounter_id, barrier_type, note?."""
    defaults = {"encounter_id": encounter_id, "barrier_type": barrier_type}
    defaults.update(overrides)
    return defaults


def create_surge_event_payload(unit_id: str, level: str, **overrides) -> dict:
    """Input for POST /surge-events: unit_id, level, reason?."""
    defaults = {"unit_id": unit_id, "level": level}
    defaults.update(overrides)
    return defaults
