"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
- Gate: code, terminal, max_wingspan_m required; is_cute_equipped, buffer_minutes optional.
- RemoteStand: code, max_wingspan_m required; capacity optional.
- CuteUnit: label, terminal required.
- GroundEquipment: asset_tag, equipment_type required; turnaround_minutes optional.
- Flight: flight_no, aircraft_wingspan_m, sched_departure_utc required;
          sched_arrival_utc, min_turn_minutes optional.
- SlotPermit: flight_id, movement_type, slot_time_utc required; tolerance_minutes optional.
- GateAssignment: flight_id, stand_type, start_utc, end_utc required;
                  gate_id/remote_stand_id per discriminator; expected_gate_version optional.
- CuteAllocation / GseAllocation: flight_id, (cute_unit_id|equipment_id), start_utc, end_utc required.
"""


def create_gate_payload(**overrides) -> dict:
    defaults = {
        "code": "A12",
        "terminal": "T1",
        "max_wingspan_m": 80,
        "buffer_minutes": 10,
    }
    defaults.update(overrides)
    return defaults


def create_remote_stand_payload(**overrides) -> dict:
    defaults = {
        "code": "R5",
        "max_wingspan_m": 80,
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_cute_unit_payload(**overrides) -> dict:
    defaults = {
        "label": "CUTE-3",
        "terminal": "T1",
    }
    defaults.update(overrides)
    return defaults


def create_ground_equipment_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": "GPU-07",
        "equipment_type": "GPU",
        "turnaround_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_flight_payload(**overrides) -> dict:
    defaults = {
        "flight_no": "AA482",
        "aircraft_wingspan_m": 60,
        "sched_arrival_utc": "2026-06-10T08:00:00Z",
        "sched_departure_utc": "2026-06-10T10:00:00Z",
        "min_turn_minutes": 45,
    }
    defaults.update(overrides)
    return defaults


def create_slot_permit_payload(flight_id, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "movement_type": "ARRIVAL",
        "slot_time_utc": "2026-06-10T12:00:00Z",
        "tolerance_minutes": 15,
    }
    defaults.update(overrides)
    return defaults


def create_gate_assignment_payload(flight_id, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "stand_type": "GATE",
        "start_utc": "2026-06-10T08:00:00Z",
        "end_utc": "2026-06-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cute_allocation_payload(flight_id, cute_unit_id, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "cute_unit_id": cute_unit_id,
        "start_utc": "2026-06-10T10:00:00Z",
        "end_utc": "2026-06-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_gse_allocation_payload(flight_id, equipment_id, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "equipment_id": equipment_id,
        "start_utc": "2026-06-10T10:00:00Z",
        "end_utc": "2026-06-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults
