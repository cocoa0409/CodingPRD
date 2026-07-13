"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the client-supplied (input) fields for a create
call. Foreign keys that must reference real records are passed explicitly by the
caller (fixtures thread real ids through). System/computed fields are never
included.
"""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    """Return a process-unique token so parallel entities do not collide."""
    return f"{prefix}{next(_counter)}"


def create_client_payload(**overrides) -> dict:
    n = _uniq("client")
    defaults = {
        "full_name": f"Test Client {n}",
        "email": f"{n}@example.com",
        "home_address": f"{n} Test Street",
    }
    defaults.update(overrides)
    return defaults


def create_organizer_payload(**overrides) -> dict:
    n = _uniq("org")
    defaults = {
        "full_name": f"Test Organizer {n}",
        "email": f"{n}@example.com",
        "hourly_rate_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id: str, lead_organizer_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "lead_organizer_id": lead_organizer_id,
        "title": f"Project {_uniq('p')}",
        "billing_mode": "HOURLY",
        "scope_rooms": ["Garage"],
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(project_id: str, organizer_id: str,
                           scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "organizer_id": organizer_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(project_id: str, disposition: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "room_label": "Garage",
        "description": f"Item {_uniq('i')}",
        "disposition": disposition,
    }
    defaults.update(overrides)
    return defaults


def create_product_line_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "product_name": f"Bin {_uniq('b')}",
        "category": "BIN",
        "wholesale_cost_cents": 1099,
        "quantity": 3,
        "markup_pct": 0.35,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(project_id: str, expected_project_version: int, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_plan_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "cadence": "QUARTERLY",
        "monthly_fee_cents": 9900,
    }
    defaults.update(overrides)
    return defaults
