"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ACCOUNT_NAME": "Acme",
    "BILLING_EMAIL": "a@x.com",
    "TECH_NAME": "Tina",
    "SHIFT_START": 480,    # 08:00
    "SHIFT_END": 1020,     # 17:00
    "ADDRESS": "1 Pine",
    "COUNTY_CODE": "KING",
    "SERVICE_MINUTES": 60,
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ACCOUNT_NAME"],
        "billing_email": DEFAULTS["BILLING_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TECH_NAME"],
        "shift_start_minute": DEFAULTS["SHIFT_START"],
        "shift_end_minute": DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "address": DEFAULTS["ADDRESS"],
        "county_code": DEFAULTS["COUNTY_CODE"],
        "service_minutes": DEFAULTS["SERVICE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "asset_type": "SEPTIC_TANK",
        "capacity_gallons": 1200,
        "install_year": 2015,
    }
    defaults.update(overrides)
    return defaults


def create_service_plan_payload(site_id: str, expected_site_version: int, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "frequency_months": 36,
        "estimated_gallons": 800,
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(site_id: str, work_type: str, scheduled_date: str,
                              window_start_minute: int, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "work_type": work_type,
        "scheduled_date": scheduled_date,
        "window_start_minute": window_start_minute,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(technician_id: str, route_date: str, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "route_date": route_date,
    }
    defaults.update(overrides)
    return defaults


def create_repair_line_payload(work_order_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "part_name": "Gasket",
        "quantity": 1,
        "unit_price_cents": 101,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_report_payload(work_order_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
    }
    defaults.update(overrides)
    return defaults


def create_permit_filing_payload(inspection_report_id: str, site_id: str, **overrides) -> dict:
    defaults = {
        "inspection_report_id": inspection_report_id,
        "site_id": site_id,
    }
    defaults.update(overrides)
    return defaults
