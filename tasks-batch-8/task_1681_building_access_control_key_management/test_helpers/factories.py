"""Payload factories — one per creatable entity, input fields only."""
from .constants import ALL_DAYS


def create_building_payload(**overrides) -> dict:
    defaults = {"name": "Test Building"}
    defaults.update(overrides)
    return defaults


def create_key_node_payload(building_id, level, label, **overrides) -> dict:
    defaults = {"building_id": building_id, "level": level, "label": label}
    defaults.update(overrides)
    return defaults


def create_door_payload(building_id, key_node_id, door_code="D-1", **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "door_code": door_code,
        "key_node_id": key_node_id,
    }
    defaults.update(overrides)
    return defaults


def create_person_payload(building_id, full_name, kind, **overrides) -> dict:
    defaults = {"building_id": building_id, "full_name": full_name, "kind": kind}
    defaults.update(overrides)
    return defaults


def create_credential_payload(building_id, key_node_id, serial_no, type="FOB", **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "key_node_id": key_node_id,
        "serial_no": serial_no,
        "type": type,
    }
    defaults.update(overrides)
    return defaults


def issue_credential_payload(person_id, **overrides) -> dict:
    defaults = {"person_id": person_id}
    defaults.update(overrides)
    return defaults


def create_access_group_payload(building_id, name, **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "name": name,
        "days_of_week": list(ALL_DAYS),
        "window_start_utc": "00:00",
        "window_end_utc": "23:59",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(building_id, door_id, type, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "door_id": door_id,
        "type": type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_rekey_campaign_payload(building_id, key_node_id, **overrides) -> dict:
    defaults = {"building_id": building_id, "key_node_id": key_node_id}
    defaults.update(overrides)
    return defaults
