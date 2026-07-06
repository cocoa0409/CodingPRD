"""Payload factories — one per entity, input fields only (PRD §3)."""


def customer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Owner",
        "email": "owner@example.com",
    }
    payload.update(overrides)
    return payload


def product_payload(**overrides) -> dict:
    payload = {
        "sku": "PAV-HOLLAND",
        "name": "Holland Paver",
        "category": "PAVER",
        "unit": "SQFT",
        "unit_price_cents": 850,
        "waste_factor": 0.10,
        "coverage_per_pallet_sqft": 120,
    }
    payload.update(overrides)
    return payload


def paver_product_payload(**overrides) -> dict:
    return product_payload(**overrides)


def wall_product_payload(**overrides) -> dict:
    base = {
        "sku": "WALL-STONE",
        "name": "Stone Wall",
        "category": "WALL_BLOCK",
        "unit": "FACE_SQFT",
        "unit_price_cents": 2200,
        "waste_factor": 0.10,
        "coverage_per_pallet_sqft": 30,
    }
    base.update(overrides)
    return base


def fire_pit_product_payload(**overrides) -> dict:
    base = {
        "sku": "FIRE-KIT",
        "name": "Fire Pit Kit",
        "category": "FIRE_PIT",
        "unit": "EACH",
        "unit_price_cents": 180000,
    }
    base.update(overrides)
    return base


def crew_payload(**overrides) -> dict:
    payload = {"name": "Test Crew", "region_code": "CA"}
    payload.update(overrides)
    return payload


def project_payload(customer_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "site_address": "1 Yard Ln",
        "region_code": "CA",
    }
    payload.update(overrides)
    return payload


def design_revision_payload(project_id, **overrides) -> dict:
    payload = {"project_id": project_id}
    payload.update(overrides)
    return payload


def site_measurement_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "zone_label": "patio",
        "measured_sqft": 100,
        "wall_height_in": 0,
    }
    payload.update(overrides)
    return payload


def line_item_payload(project_id, product_id, measured_quantity=100, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "product_id": product_id,
        "measured_quantity": measured_quantity,
    }
    payload.update(overrides)
    return payload


def change_order_payload(project_id, add_product_id, expected_project_version,
                         add_measured_quantity=100, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "add_product_id": add_product_id,
        "add_measured_quantity": add_measured_quantity,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def material_order_payload(project_id, line_item_ids, requested_delivery_date="2026-06-10",
                           **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "requested_delivery_date": requested_delivery_date,
        "line_item_ids": list(line_item_ids),
    }
    payload.update(overrides)
    return payload


def work_phase_payload(project_id, phase_type="EXCAVATION", **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "phase_type": phase_type,
    }
    payload.update(overrides)
    return payload


def schedule_payload(crew_id, start_date="2026-06-11", end_date="2026-06-15", **overrides) -> dict:
    payload = {
        "crew_id": crew_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def draw_payload(project_id, draw_type, amount_cents, expected_project_version, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "draw_type": draw_type,
        "amount_cents": amount_cents,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def warranty_claim_payload(project_id, claim_category="WORKMANSHIP", **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "claim_category": claim_category,
    }
    payload.update(overrides)
    return payload
