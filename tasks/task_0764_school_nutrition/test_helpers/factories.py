"""Payload factories — one per entity, input fields only."""


def create_site_payload(**overrides) -> dict:
    """Only name and site_code are required; every other field has a PRD default."""
    defaults = {"name": "Test School", "site_code": "TST-1"}
    defaults.update(overrides)
    return defaults


def create_food_item_payload(**overrides) -> dict:
    """name and category are required; nutrient/contribution fields default to 0."""
    defaults = {"name": "Test Food", "category": "ENTREE"}
    defaults.update(overrides)
    return defaults


def create_reimbursement_rate_payload(**overrides) -> dict:
    defaults = {
        "program": "NSLP",
        "category": "PAID",
        "rate_cents": 55,
        "effective_date": "2025-07-01",
    }
    defaults.update(overrides)
    return defaults


def create_menu_cycle_payload(site_id, components, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "meal_type": "LUNCH",
        "grade_group": "GRADES_9_12",
        "effective_date": "2026-04-01",
        "end_date": "2026-06-30",
        "components": components,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(site_id, food_item_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "food_item_id": food_item_id,
        "lot_type": "PURCHASED",
        "quantity_received": 1000,
        "received_date": "2026-03-10",
    }
    defaults.update(overrides)
    return defaults


def create_production_record_payload(site_id, menu_cycle_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "menu_cycle_id": menu_cycle_id,
        "service_date": "2026-04-15",
        "meal_type": "LUNCH",
        "planned_qty": 100,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "first_name": "Test",
        "last_name": "Student",
        "grade": "GRADES_9_12",
        "eligibility_category": "PAID",
    }
    defaults.update(overrides)
    return defaults


def create_meal_transaction_payload(site_id, student_id, production_record_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "student_id": student_id,
        "production_record_id": production_record_id,
        "service_date": "2026-04-15",
        "meal_type": "LUNCH",
        "selected_components": ["MEAT_MEAT_ALT", "GRAINS", "FRUIT"],
    }
    defaults.update(overrides)
    return defaults


def create_reimbursement_claim_payload(site_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "claim_month": "2026-04"}
    defaults.update(overrides)
    return defaults
