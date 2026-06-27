"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="client") -> str:
    """Generate a unique email (Client.email must be unique across clients)."""
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_client_payload(**overrides) -> dict:
    """Client input: full_name, email, billing_tier? (defaults RESIDENTIAL)."""
    defaults = {
        "full_name": "Test Client",
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id, **overrides) -> dict:
    """Project input: client_id, site_address, region_code."""
    defaults = {
        "client_id": client_id,
        "site_address": "1 Oak St",
        "region_code": "WEST",
    }
    defaults.update(overrides)
    return defaults


def create_rack_payload(**overrides) -> dict:
    """Rack input: rack_units_total, subnet_cidr."""
    defaults = {
        "rack_units_total": 10,
        "subnet_cidr": "10.20.0.0/24",
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(expected_project_version, **overrides) -> dict:
    """Proposal input: labor_hours_estimate, expected_project_version."""
    defaults = {
        "labor_hours_estimate": 2.0,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(**overrides) -> dict:
    """ProposalLineItem input: sku, category, qty, unit_price_cents."""
    defaults = {
        "sku": "C4-CTRL",
        "category": "CONTROLLER",
        "qty": 1,
        "unit_price_cents": 250000,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(rack_id, **overrides) -> dict:
    """Device input: rack_id, sku, category, rack_units? (defaults 1)."""
    defaults = {
        "rack_id": rack_id,
        "sku": "C4-CTRL",
        "category": "CONTROLLER",
        "rack_units": 2,
    }
    defaults.update(overrides)
    return defaults


def create_scene_payload(device_ids, **overrides) -> dict:
    """SceneProgram input: name, device_ids, action_count."""
    defaults = {
        "name": "Movie Night",
        "device_ids": device_ids,
        "action_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(**overrides) -> dict:
    """Visit input: window_start, window_end, visit_kind, crew_size_required."""
    defaults = {
        "window_start": "2026-03-01T09:00:00Z",
        "window_end": "2026-03-01T12:00:00Z",
        "visit_kind": "INSTALL",
        "crew_size_required": 1,
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    """CrewMember input: full_name, region_code, cert_level, daily_visit_cap?, active?."""
    defaults = {
        "full_name": "Test Tech",
        "region_code": "WEST",
        "cert_level": "JOURNEYMAN",
        "daily_visit_cap": 2,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(crew_member_id, expected_visit_version, **overrides) -> dict:
    """VisitAssignment input: crew_member_id, expected_visit_version."""
    defaults = {
        "crew_member_id": crew_member_id,
        "expected_visit_version": expected_visit_version,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    """Contract input: plan, prepaid_hours, hourly_rate_cents."""
    defaults = {
        "plan": "PLUS",
        "prepaid_hours": 10,
        "hourly_rate_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_firmware_update_payload(**overrides) -> dict:
    """FirmwareUpdate input: target_version."""
    defaults = {
        "target_version": "3.4.1",
    }
    defaults.update(overrides)
    return defaults


def create_rma_payload(device_id, contract_id, **overrides) -> dict:
    """RmaTicket input: device_id, contract_id, fault_code, resolution? (defaults RETURN_REPAIR)."""
    defaults = {
        "device_id": device_id,
        "contract_id": contract_id,
        "fault_code": "HARDWARE",
        "resolution": "RETURN_REPAIR",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    """ChangeOrder input: description, delta_cents, added_labor_hours? (defaults 0)."""
    defaults = {
        "description": "Scope change",
        "delta_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def apply_change_order_payload(expected_project_version, **overrides) -> dict:
    """apply change order input: expected_project_version."""
    defaults = {
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def consume_payload(hours, **overrides) -> dict:
    """contract consume input: hours."""
    defaults = {"hours": hours}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    """clock input: to_iso8601."""
    return {"to_iso8601": to_iso8601}
