"""Payload factories — one per entity, input fields only."""
from .constants import SHARED_CONFIG

_EMAIL_SEQ = [0]


def _unique_email(prefix="owner"):
    _EMAIL_SEQ[0] += 1
    return f"{prefix}{_EMAIL_SEQ[0]}@example.com"


def create_pricing_config_payload(**overrides) -> dict:
    """Body for POST /pricing-configs. Defaults to the shared price book."""
    defaults = dict(SHARED_CONFIG)
    defaults.update(overrides)
    return defaults


def create_homeowner_payload(**overrides) -> dict:
    """Body for POST /homeowners."""
    defaults = {
        "full_name": "Test Owner",
        "email": _unique_email(),
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_home_payload(homeowner_id, **overrides) -> dict:
    """Body for POST /homes."""
    defaults = {
        "homeowner_id": homeowner_id,
        "address_line": "1 Vent Rd",
        "zone_code": "Z1",
        "square_footage": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_system_payload(**overrides) -> dict:
    """Body for POST /homes/{id}/systems."""
    defaults = {
        "label": "Sys A",
        "register_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    """Body for POST /crew-members."""
    defaults = {
        "full_name": "Test Crew",
        "home_zone_code": "Z1",
    }
    defaults.update(overrides)
    return defaults


def create_route_plan_payload(crew_member_id, **overrides) -> dict:
    """Body for POST /route-plans."""
    defaults = {
        "crew_member_id": crew_member_id,
        "zone_code": "Z1",
        "service_date": "2026-04-10",
        "shift_start_minute": 480,
        "shift_end_minute": 1020,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(home_id, service_lines, **overrides) -> dict:
    """Body for POST /work-orders. service_lines is required."""
    defaults = {
        "home_id": home_id,
        "service_lines": service_lines,
        "requested_start_minute": 540,
    }
    defaults.update(overrides)
    return defaults


def inspect_payload(**overrides) -> dict:
    """Body for POST /work-orders/{id}/inspect."""
    defaults = {
        "before_photo_count": 2,
        "dust_severity": 4,
    }
    defaults.update(overrides)
    return defaults


def complete_payload(performed_service_lines, **overrides) -> dict:
    """Body for POST /work-orders/{id}/complete."""
    defaults = {
        "after_photo_count": 2,
        "dust_severity": 3,
        "performed_service_lines": performed_service_lines,
    }
    defaults.update(overrides)
    return defaults


def commit_payload(work_order_id, scheduled_start_minute, expected_route_plan_version) -> dict:
    """Body for POST /route-plans/{id}/commit."""
    return {
        "work_order_id": work_order_id,
        "scheduled_start_minute": scheduled_start_minute,
        "expected_route_plan_version": expected_route_plan_version,
    }


def recurring_plan_payload(cadence_months, expected_home_version, **overrides) -> dict:
    """Body for POST /homes/{id}/recurring-plans."""
    defaults = {
        "cadence_months": cadence_months,
        "expected_home_version": expected_home_version,
    }
    defaults.update(overrides)
    return defaults


def callback_ticket_payload(work_order_id, **overrides) -> dict:
    """Body for POST /callback-tickets."""
    defaults = {
        "work_order_id": work_order_id,
        "reason": "Still dusty",
    }
    defaults.update(overrides)
    return defaults


def duct_line(system_id) -> dict:
    return {"service_type": "DUCT", "system_id": system_id}


def sanitize_line(system_id) -> dict:
    return {"service_type": "SANITIZE", "system_id": system_id}


def dryer_line() -> dict:
    return {"service_type": "DRYER_VENT"}
