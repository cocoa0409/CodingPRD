"""Payload factories — one per entity, input fields only (PRD §4)."""
import itertools

from .constants import TEST_DEFAULTS

_serial_counter = itertools.count(1000)
_model_counter = itertools.count(100)
_license_counter = itertools.count(100)


def _next(counter, prefix):
    return f"{prefix}-{next(counter)}"


def create_property_payload(**overrides) -> dict:
    defaults = {
        "owner_user_id": TEST_DEFAULTS["OWNER_USER_ID"],
        "address_line": TEST_DEFAULTS["ADDRESS_LINE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Tech One",
        "certification": "CET_AND_QEI",
        "home_region": "north",
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "company_name": "BuildCo",
        "license_number": _next(_license_counter, "LIC"),
        "license_state_code": "WA",
    }
    defaults.update(overrides)
    return defaults


def create_product_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": _next(_model_counter, "HYD"),
        "drive_type": "HYDRAULIC",
        "min_pit_depth_inches": 12,
        "min_overhead_clearance_inches": 96,
        "capacity_lbs": 750,
        "base_price": 25000.00,
        "install_labor_price": 8000.00,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(property_id, surveyor_technician_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "surveyor_technician_id": surveyor_technician_id,
        "scheduled_date": "2026-08-05T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_survey_payload(**overrides) -> dict:
    defaults = {
        "measured_pit_depth_inches": 12,
        "measured_overhead_clearance_inches": 96,
        "shaft_width_inches": 40,
        "shaft_depth_inches": 44,
        "floors_served": 2,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(property_id, survey_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "survey_id": survey_id,
        "project_type": "NEW_INSTALLATION",
    }
    defaults.update(overrides)
    return defaults


def select_product_payload(product_model_id, lead_installer_technician_id,
                           expected_project_version, **overrides) -> dict:
    defaults = {
        "product_model_id": product_model_id,
        "lead_installer_technician_id": lead_installer_technician_id,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "ahj_name": TEST_DEFAULTS["AHJ_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(project_id, contractor_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "scope_description": "Deepen pit and raise overhead",
        "scheduled_start_date": "2026-08-05T08:00:00Z",
        "scheduled_end_date": "2026-08-08T17:00:00Z",
        "estimated_cost": 3100.00,
    }
    defaults.update(overrides)
    return defaults


def schedule_installation_payload(**overrides) -> dict:
    defaults = {
        "install_start_date": "2026-08-10T08:00:00Z",
        "install_end_date": "2026-08-20T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_installation_payload(**overrides) -> dict:
    defaults = {"serial_number": _next(_serial_counter, "SN")}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(unit_id, inspector_technician_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "inspection_type": "ACCEPTANCE",
        "inspector_technician_id": inspector_technician_id,
        "scheduled_start": "2026-08-12T10:00:00Z",
        "scheduled_end": "2026-08-12T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(unit_id, **overrides) -> dict:
    defaults = {"unit_id": unit_id}
    defaults.update(overrides)
    return defaults


def create_service_contract_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "tier": "STANDARD",
        "contract_year_start": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_call_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "call_type": "REPAIR",
    }
    defaults.update(overrides)
    return defaults


def create_grant_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": "AccessGrant",
        "funder_name": "State ADA Fund",
        "max_award": 10000.00,
        "income_cap": 60000.00,
        "coverage_percent": 0.40,
        "total_pool": 50000.00,
        "application_open_date": "2026-07-01T00:00:00Z",
        "application_close_date": "2026-12-31T23:59:59Z",
        "eligible_project_types": ["NEW_INSTALLATION", "MODERNIZATION"],
    }
    defaults.update(overrides)
    return defaults


def create_grant_application_payload(project_id, program_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "program_id": program_id,
        "household_income": 42000.00,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "description": "Scope change",
        "amount": 1000.00,
    }
    defaults.update(overrides)
    return defaults
