"""Payload factories — one per entity, input fields only."""


def create_producer_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Test Bakes",
        "operator_name": "Test Operator",
        "contact_email": "test@x.com",
        "county": "Alameda",
        "water_source": "PUBLIC",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "food_category": "BAKED_GOODS",
        "is_cottage_allowed": True,
        "class_b_required": False,
        "requires_allergen_label": False,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(producer_id, **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "name": "Test Product",
        "food_category": "BAKED_GOODS",
        "requires_refrigeration": False,
        "unit_price_cents": 800,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(producer_id, permit_class="CLASS_A", **overrides) -> dict:
    defaults = {"producer_id": producer_id, "permit_class": permit_class}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(permit_id, inspection_type="ROUTINE",
                              scheduled_for="2026-05-10T09:00:00Z", **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "inspection_type": inspection_type,
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(producer_id, category="LABELING",
                             description="test complaint", **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "category": category,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_market_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Market",
        "county": "Alameda",
        "venue_type": "CERTIFIED_FM",
        "max_vendors_per_day": 5,
        "allowed_classes": ["CLASS_A", "CLASS_B"],
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(producer_id, market_id, permit_id, product_ids,
                            event_date="2026-06-15", **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "market_id": market_id,
        "permit_id": permit_id,
        "event_date": event_date,
        "product_ids": list(product_ids),
    }
    defaults.update(overrides)
    return defaults


def create_sales_record_payload(manifest_id, gross_amount_cents, **overrides) -> dict:
    defaults = {"manifest_id": manifest_id, "gross_amount_cents": gross_amount_cents}
    defaults.update(overrides)
    return defaults


def create_recall_payload(producer_id, product_id, reason="CONTAMINATION",
                          severity="MEDIUM", **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "product_id": product_id,
        "reason": reason,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults
