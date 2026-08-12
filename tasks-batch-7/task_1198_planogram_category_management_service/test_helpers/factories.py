"""Payload factories — one per entity, input fields only."""


def create_retailer_payload(**overrides) -> dict:
    defaults = {"name": "Test Retailer"}
    defaults.update(overrides)
    return defaults


def create_category_payload(**overrides) -> dict:
    defaults = {
        "code": "CAT",
        "role": "ROUTINE",
        "annual_sales_cents": 100_000,
        "total_linear_feet": 10,
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {"name": "Test Supplier"}
    defaults.update(overrides)
    return defaults


def create_product_payload(category_id, supplier_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "supplier_id": supplier_id,
        "sku": "SKU-1",
        "width_in": 6,
        "unit_cost_cents": 100,
        "weekly_demand_units": 70,
    }
    defaults.update(overrides)
    return defaults


def create_planogram_payload(**overrides) -> dict:
    defaults = {
        "name": "PG",
        "variant": "BASE",
    }
    defaults.update(overrides)
    return defaults


def create_planogram_line_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "position_index": 1,
        "facings": 5,
        "capacity_units": 50,
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_code": "ST1",
        "cluster": "BASE",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(planogram_id, **overrides) -> dict:
    defaults = {
        "planogram_id": planogram_id,
        "photo_url": "https://example.com/photo.jpg",
    }
    defaults.update(overrides)
    return defaults


def create_funding_deal_payload(category_id, supplier_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "supplier_id": supplier_id,
        "amount_cents": 5_000,
        "starts_at": "2026-06-01T00:00:00Z",
        "ends_at": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_reset_project_payload(planogram_id, store_id, **overrides) -> dict:
    defaults = {
        "planogram_id": planogram_id,
        "store_id": store_id,
        "scheduled_start": "2026-06-01T10:00:00Z",
        "scheduled_end": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_reset_crew_payload(**overrides) -> dict:
    defaults = {"name": "Crew"}
    defaults.update(overrides)
    return defaults


def create_reset_assignment_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "assigned_start": "2026-06-01T10:00:00Z",
        "assigned_end": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults
