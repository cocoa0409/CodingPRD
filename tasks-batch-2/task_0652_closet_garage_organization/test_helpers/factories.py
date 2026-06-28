"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix="cust"):
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Customer",
        "zip_code": "90001",  # first digit 9 -> WEST
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "room_type": "WALK_IN_CLOSET",
    }
    defaults.update(overrides)
    return defaults


def create_design_consult_payload(**overrides) -> dict:
    defaults = {
        "designer_user_id": "des-1",
        "scheduled_start": "2026-04-02T17:00:00Z",
        "scheduled_end": "2026-04-02T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_space_measure_payload(**overrides) -> dict:
    defaults = {
        "wall_count": 2,
        "linear_feet": 12.5,
        "ceiling_height_in": 96,
    }
    defaults.update(overrides)
    return defaults


def create_component_config_payload(space_measure_id, **overrides) -> dict:
    defaults = {
        "space_measure_id": space_measure_id,
        "material_grade": "MELAMINE",
        "line_items": [{"component_type": "SHELF", "quantity": 10, "unit_price_cents": 5000}],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(component_config_id, **overrides) -> dict:
    defaults = {
        "component_config_id": component_config_id,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(project_id, quote_id, amount_cents, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "quote_id": quote_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_name": "Test Crew",
        "region": "WEST",
        "daily_capacity_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(project_id, manufacture_order_id, crew_id,
                               window_start, window_end, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "manufacture_order_id": manufacture_order_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id, base_quote_id, change_type, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "base_quote_id": base_quote_id,
        "change_type": change_type,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(project_id, install_job_id, defect_type, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "install_job_id": install_job_id,
        "defect_type": defect_type,
    }
    defaults.update(overrides)
    return defaults


def create_financing_application_payload(project_id, quote_id, requested_amount_cents,
                                        term_months, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "quote_id": quote_id,
        "requested_amount_cents": requested_amount_cents,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults
