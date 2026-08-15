"""Payload factories — one per entity, input fields only (PRD §3)."""

_sku_counter = [0]


def _next_sku(prefix="SKU"):
    _sku_counter[0] += 1
    return f"{prefix}-{ _sku_counter[0]:05d}"


def create_practice_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Practice",
        "region": "R1",
        "credit_limit_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _next_sku(),
        "name": "Test Product",
        "kind": "CONSUMABLE",
        "unit_price_cents": 1000,
        "manufacturer": "TestManufacturer",
    }
    defaults.update(overrides)
    return defaults


def create_usage_profile_payload(practice_id, product_id, expected_practice_version, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "product_id": product_id,
        "reorder_point": 20,
        "target_stock_level": 100,
        "auto_replenish_enabled": True,
        "expected_practice_version": expected_practice_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(practice_id, lines, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "kind": "MANUAL",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_sale_payload(practice_id, product_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "product_id": product_id,
        "sale_price_cents": 900_000,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Technician",
        "region": "R1",
        "certifications": ["INSTALL", "REPAIR"],
    }
    defaults.update(overrides)
    return defaults


def create_van_stock_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quantity_on_van": 10,
        "min_quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(practice_id, equipment_sale_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "equipment_sale_id": equipment_sale_id,
        "issue_description": "Equipment malfunction",
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-08-05T09:00:00Z",
        "scheduled_end": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_resolve_payload(**overrides) -> dict:
    defaults = {
        "parts_used": [],
        "labor_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_agreement_payload(practice_id, equipment_sale_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "equipment_sale_id": equipment_sale_id,
        "coverage_type": "SERVICE_PLAN",
        "start_date": "2026-08-01T00:00:00Z",
        "end_date": "2028-08-01T00:00:00Z",
        "deductible_cents": 5000,
        "coverage_cap_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_bundle_promotion_payload(required_product_ids, **overrides) -> dict:
    defaults = {
        "name": "Bundle Promo",
        "promo_kind": "BUNDLE_DISCOUNT",
        "required_product_ids": required_product_ids,
        "discount_pct": 0.15,
        "max_discount_cents": 20_000,
        "stacking_allowed": False,
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rebate_promotion_payload(eligible_product_ids, **overrides) -> dict:
    defaults = {
        "name": "Rebate Promo",
        "promo_kind": "MANUFACTURER_REBATE",
        "eligible_product_ids": eligible_product_ids,
        "rebate_per_unit_cents": 50,
        "fund_total_cents": 10_000,
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rebate_claim_payload(practice_id, order_id, promotion_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "order_id": order_id,
        "promotion_id": promotion_id,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(practice_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "description": "Used equipment",
        "equipment_age_months": 12,
        "condition": "WORKING",
        "category_base_value_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults
