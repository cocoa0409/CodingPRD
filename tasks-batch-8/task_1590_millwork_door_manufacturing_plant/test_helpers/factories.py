"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_code_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_code_counter)}"


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Project",
        "site_address": "1 Main St",
        "contract_code": _uniq("CC"),
    }
    defaults.update(overrides)
    return defaults


def create_hardware_template_payload(**overrides) -> dict:
    defaults = {
        "template_code": _uniq("T"),
        "manufacturer": "ACME",
        "fire_rated_compatible": True,
    }
    defaults.update(overrides)
    return defaults


def create_moulder_machine_payload(**overrides) -> dict:
    defaults = {
        "machine_code": _uniq("M"),
        "supported_species": ["OAK"],
    }
    defaults.update(overrides)
    return defaults


def create_spray_booth_payload(**overrides) -> dict:
    defaults = {
        "booth_code": _uniq("B"),
    }
    defaults.update(overrides)
    return defaults


def create_fire_label_roll_payload(**overrides) -> dict:
    defaults = {
        "label_series": "UL_20MIN",
        "serial_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "order_code": _uniq("O"),
        "species": "OAK",
        "profile_code": "PR-1",
        "finish_system": "STAIN",
        "sheen_target": "SATIN",
        "hardware_prep_mode": "INSTALLER_PREP",
        "fire_rating_required": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_opening_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "opening_no": _uniq("N"),
        "width_in": 36,
        "height_in": 84,
        "fire_rating": "NONE",
        "required_on_site_date": "2026-10-01",
    }
    defaults.update(overrides)
    return defaults


def create_shop_drawing_payload(order_id, expected_order_version, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_machining_program_payload(drawing_id, order_id, **overrides) -> dict:
    defaults = {
        "drawing_id": drawing_id,
        "order_id": order_id,
        "estimated_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_moulder_setup_slot_payload(program_id, machine_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "machine_id": machine_id,
        "start_hour": 8,
        "end_hour": 10,
    }
    defaults.update(overrides)
    return defaults


def create_finishing_batch_payload(order_id, booth_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "booth_id": booth_id,
        "cure_start_hour": 10,
        "cure_end_hour": 16,
    }
    defaults.update(overrides)
    return defaults


def create_label_allocation_payload(opening_id, roll_id, expected_roll_version, **overrides) -> dict:
    defaults = {
        "opening_id": opening_id,
        "roll_id": roll_id,
        "expected_roll_version": expected_roll_version,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_trip_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "trip_code": _uniq("T"),
        "truck_capacity_leaves": 4,
        "departure_date": "2026-10-02",
        "site_arrival_date": "2026-10-04",
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(opening_id, **overrides) -> dict:
    defaults = {
        "opening_id": opening_id,
        "category": "TRANSIT_DAMAGE",
        "severity": "MINOR",
        "description": "deficiency",
    }
    defaults.update(overrides)
    return defaults
