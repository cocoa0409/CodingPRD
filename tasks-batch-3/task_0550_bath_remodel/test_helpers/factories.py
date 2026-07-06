"""Payload factories — one per entity, input fields only.

Optional fields are included only when explicitly overridden, so the server's
own defaults (e.g. designer.active, crew.accessibility_certified) are exercised
by tests that omit them.
"""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Homer Homeowner",
        "email": f"{_uniq('cust')}@example.com",
        "phone": "555-0100",
        "street_address": "1 Main St",
        "city": "Los Angeles",
        "state_code": "CA",
        "postal_code": "90001",
    }
    payload.update(overrides)
    return payload


def create_designer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Designer",
        "email": f"{_uniq('des')}@example.com",
        "region_state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {
        "crew_name": _uniq("Crew"),
        "home_state_code": "CA",
        "max_installs_per_day": 2,
    }
    payload.update(overrides)
    return payload


def create_project_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "state_code": "CA",
        "bathroom_type": "FULL_BATH",
    }
    payload.update(overrides)
    return payload


def create_design_appointment_payload(project_id: str, designer_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "designer_id": designer_id,
        "scheduled_start": "2026-05-10T14:00:00Z",
        "scheduled_end": "2026-05-10T15:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_quote_payload(project_id: str, expected_project_version: int, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "wall_system": "TILE_LOOK_ACRYLIC",
        "color": "WHITE",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "defect_type": "CRACK",
        "description": "hairline crack near the drain",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(referrer_customer_id: str, **overrides) -> dict:
    payload = {
        "referrer_customer_id": referrer_customer_id,
    }
    payload.update(overrides)
    return payload
