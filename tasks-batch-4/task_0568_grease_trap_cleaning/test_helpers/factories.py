"""Payload factories — one per entity, input fields only (PRD §3)."""

MAY_PERIOD_START = "2026-05-01T00:00:00Z"
MAY_PERIOD_END = "2026-06-01T00:00:00Z"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Test Diner",
        "billing_email": "test@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "address": "1 Test St",
        "municipality_code": "MUNI-A",
        "permit_number": "P-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "equipment_type": "GREASE_TRAP",
        "capacity_gallons": 100,
        "nominal_frequency_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_service_contract_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "billing_cycle": "MONTHLY",
        "base_rate_cents": 12500,
        "tax_rate_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Technician",
        "certification_level": "BASIC",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(site_id: str, equipment_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "equipment_id": equipment_id,
        "service_type": "SCHEDULED",
        "planned_start": "2026-05-10T08:00:00Z",
        "planned_end": "2026-05-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(work_order_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "disposal_facility_name": "Acme Disposal",
        "disposal_facility_permit": "FAC-1",
        "hazmat_certified": False,
        "volume_gallons": 50,
        "fog_percentage": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_hood_certificate_payload(work_order_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "cleanliness_grade": "ACCEPTABLE",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "municipality_code": "MUNI-A",
        "period_start": "2026-04-01T00:00:00Z",
        "period_end": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(customer_id: str, expected_customer_version: int, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "period_start": MAY_PERIOD_START,
        "period_end": MAY_PERIOD_END,
        "expected_customer_version": expected_customer_version,
    }
    defaults.update(overrides)
    return defaults
