"""Payload factories — one per entity, input fields only."""


def create_retailer_payload(**overrides) -> dict:
    defaults = {"name": "Test Retailer", "commission_rate_bps": 1000}
    defaults.update(overrides)
    return defaults


def create_service_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": "SF-94103",
        "name": "SF Central",
        "max_concurrent_appointments": 5,
        "coverage_active": True,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ada Customer",
        "email": "ada@example.com",
        "phone": "5551234",
        "address_line": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def create_pro_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat Pro",
        "email": "pat@example.com",
        "service_zone_id": None,
        "skills": ["TV_MOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {"background_check_ref": "BG-1"}
    defaults.update(overrides)
    return defaults


def create_install_task_payload(**overrides) -> dict:
    defaults = {
        "task_code": "TV_MOUNT_STD",
        "name": "Standard TV Mount",
        "category": "TV_MOUNT",
        "required_skill": "TV_MOUNT",
        "base_price_cents": 12000,
        "estimated_minutes": 60,
        "warranty_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {
        "addon_code": "CABLE_CONCEAL",
        "name": "Cable Conceal",
        "category": "TV_MOUNT",
        "price_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "retailer_id": None,
        "customer_id": None,
        "install_task_id": None,
        "service_zone_id": None,
        "product_sku": "TV-55",
        "product_category": "TV_MOUNT",
    }
    defaults.update(overrides)
    return defaults


def schedule_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-03-05T09:00:00Z",
        "scheduled_end": "2026-03-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "name": "Bracket",
        "unit_cost_cents": 1500,
        "quantity": 1,
        "markup_bps": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_rating_payload(**overrides) -> dict:
    defaults = {"stars": 5}
    defaults.update(overrides)
    return defaults
