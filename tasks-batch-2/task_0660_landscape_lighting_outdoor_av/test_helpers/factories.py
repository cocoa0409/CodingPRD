"""Payload factories — one per entity, input fields only.

Each factory builds the minimal valid create payload and accepts **overrides.
Field names are PRD-exact.
"""
import itertools

# Monotonic counter so default customer emails are unique within a single test
# (the email-uniqueness rule is case-insensitive, PRD §3.1).
_email_counter = itertools.count(1)


def create_customer_payload(**overrides) -> dict:
    n = next(_email_counter)
    defaults = {
        "full_name": "Test Owner",
        "email": f"owner{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "property_address": "1 Test Street",
    }
    defaults.update(overrides)
    return defaults


def create_transformer_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "model_code": "TX-300",
        "rated_capacity_va": 300,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(transformer_id: str, **overrides) -> dict:
    # project_id is supplied via the URL path (POST /projects/{id}/zones).
    defaults = {
        "transformer_id": transformer_id,
        "label": "Front Path",
    }
    defaults.update(overrides)
    return defaults


def create_fixture_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "model_code": "PATH-3W",
        "category": "PATH",
        "wattage_w": 3,
        "purchase_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def assign_zone_payload(zone_id: str, expected_transformer_version: int, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "expected_transformer_version": expected_transformer_version,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_payload(**overrides) -> dict:
    defaults = {
        "model_code": "PATH-3W",
        "quantity": 1,
        "unit_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(project_id: str, quote_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "quote_id": quote_id,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_program_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "scene_label": "Evening Warm",
        "window_start_min": 540,
        "window_end_min": 600,
    }
    defaults.update(overrides)
    return defaults


def create_service_plan_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "tier": "BASIC",
        "annual_fee_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(service_plan_id: str, project_id: str, **overrides) -> dict:
    defaults = {
        "service_plan_id": service_plan_id,
        "project_id": project_id,
        "visit_date": "2026-05-01",
        "window_start_min": 540,
        "window_end_min": 600,
    }
    defaults.update(overrides)
    return defaults


def create_crew_route_payload(**overrides) -> dict:
    defaults = {
        "technician_id": "tech-1",
        "route_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def add_visit_payload(visit_id: str, **overrides) -> dict:
    defaults = {
        "visit_id": visit_id,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(fixture_id: str, project_id: str, **overrides) -> dict:
    defaults = {
        "fixture_id": fixture_id,
        "project_id": project_id,
        "reason": "Fixture failed",
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "kind": "AUDIO",
        "power_draw_va": 0,
    }
    defaults.update(overrides)
    return defaults
