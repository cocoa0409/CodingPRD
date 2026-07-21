"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Member",
        "email": f"{_uniq('member')}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_fabric_bolt_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "color": "Test Color",
        "price_per_yard": 5.00,
        "original_yards": 50,
    }
    defaults.update(overrides)
    return defaults


def create_fabric_cut_payload(bolt_id: str, yards_requested, **overrides) -> dict:
    defaults = {
        "bolt_id": bolt_id,
        "yards_requested": yards_requested,
    }
    defaults.update(overrides)
    return defaults


def create_kit_payload(components, **overrides) -> dict:
    defaults = {
        "name": "Test Kit",
        "kit_type": "KIT",
        "components": components,
    }
    defaults.update(overrides)
    return defaults


def create_longarm_machine_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Machine"),
        "model": "APQS",
    }
    defaults.update(overrides)
    return defaults


def create_longarm_job_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "quoted_width_in": 50,
        "quoted_length_in": 50,
        "pattern_tier": "CUSTOM",
    }
    defaults.update(overrides)
    return defaults


def create_class_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Class",
        "event_type": "CLASS",
        "instructor": "Test Instructor",
        "start_time": "2026-09-01T10:00:00Z",
        "end_time": "2026-09-01T12:00:00Z",
        "capacity": 5,
        "fee": 20.00,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(class_event_id: str, member_id: str, **overrides) -> dict:
    defaults = {
        "class_event_id": class_event_id,
        "member_id": member_id,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "description": "Test special order",
        "quantity": 1,
        "est_unit_cost": 10.00,
    }
    defaults.update(overrides)
    return defaults
