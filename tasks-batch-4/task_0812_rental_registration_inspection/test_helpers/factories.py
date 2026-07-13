"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_landlord_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Landlord",
        "email": "landlord@example.com",
        "phone": "555-0100",
        "mailing_address": "1 Records Way",
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Inspector",
        "badge_number": "BADGE-001",
        "email": "inspector@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(landlord_id, **overrides) -> dict:
    defaults = {
        "landlord_id": landlord_id,
        "street_address": "10 Maple St",
        "unit_count": 3,
        "year_built": 1980,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "tenant_email": "tenant@example.com",
        "tenant_unit": "1A",
        "category": "HABITABILITY",
        "description": "No heat in unit",
        "severity_alleged": "MAJOR",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(property_id, inspector_id, scheduled_date, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "inspector_id": inspector_id,
        "inspection_type": "PERIODIC",
        "scheduled_date": scheduled_date,
    }
    defaults.update(overrides)
    return defaults


def create_checklist_item_payload(category, code, result, **overrides) -> dict:
    defaults = {
        "category": category,
        "code": code,
        "result": result,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(property_id, expected_property_version, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "term_years": 1,
        "expected_property_version": expected_property_version,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "recipient_email": "tenant@example.com",
        "recipient_unit": "1A",
        "notice_type": "INSPECTION_NOTICE",
    }
    defaults.update(overrides)
    return defaults


def create_condemnation_order_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "basis": "Uninhabitable conditions",
    }
    defaults.update(overrides)
    return defaults
