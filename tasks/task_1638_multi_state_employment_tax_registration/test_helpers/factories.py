"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "fein": TEST_DEFAULTS["FEIN"],
        "home_state_code": TEST_DEFAULTS["HOME_STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_tax_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_kind": "STATE_WITHHOLDING",
        "state_code": "OR",
        "agency_name": "Oregon DOR",
        "withholding_rate_bp": TEST_DEFAULTS["OR_WITHHOLDING_RATE_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_reciprocity_agreement_payload(**overrides) -> dict:
    defaults = {
        "state_a": "PA",
        "state_b": "NJ",
        "effective_from": "2020-01-01T00:00:00Z",
        "scope": "FULL",
    }
    defaults.update(overrides)
    return defaults


_LOCATION_DEFAULTS = {
    "OR": {
        "label": "Portland Office",
        "address_line1": "100 Main St",
        "city": "Portland",
        "state_code": "OR",
        "postal_code": "97201",
        "location_type": "COMPANY_OFFICE",
    },
    "NJ": {
        "label": "Jersey Home",
        "address_line1": "5 Grove St",
        "city": "Jersey City",
        "state_code": "NJ",
        "postal_code": "07302",
        "location_type": "REMOTE_HOME",
    },
    "PA": {
        "label": "Philly Office",
        "address_line1": "1 Liberty Pl",
        "city": "Philadelphia",
        "state_code": "PA",
        "postal_code": "19103",
        "location_type": "COMPANY_OFFICE",
    },
    "NY": {
        "label": "NYC Office",
        "address_line1": "7 Park Ave",
        "city": "New York",
        "state_code": "NY",
        "postal_code": "10016",
        "location_type": "COMPANY_OFFICE",
    },
}


def create_work_location_payload(state_code="OR", **overrides) -> dict:
    defaults = dict(_LOCATION_DEFAULTS.get(state_code, _LOCATION_DEFAULTS["OR"]))
    defaults.update(overrides)
    return defaults


def create_employee_payload(work_location_id, **overrides) -> dict:
    defaults = {
        "employee_ref": "E-0001",
        "full_name": "Test Employee",
        "resident_state_code": "OR",
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
        "annual_wage_cents": 3_000_000,
        "current_work_location_id": work_location_id,
    }
    defaults.update(overrides)
    return defaults


def create_nexus_case_payload(state_code="OR", **overrides) -> dict:
    defaults = {"state_code": state_code}
    defaults.update(overrides)
    return defaults


def create_registration_payload(agency_id, expected_employer_version, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "projected_annual_withholding_cents": 200_000,
        "expected_employer_version": expected_employer_version,
    }
    defaults.update(overrides)
    return defaults


def create_withholding_election_payload(employee_id, expected_employee_version, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "election_type": "RECIPROCITY_EXEMPTION",
        "work_state_code": "NJ",
        "effective_from": TEST_DEFAULTS["HIRE_DATE"],
        "expected_employee_version": expected_employee_version,
    }
    defaults.update(overrides)
    return defaults


def create_ui_rate_payload(registration_id, expected_registration_version, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "rate_year": 2026,
        "experience_rated": True,
        "assigned_rate_bp": 420,
        "contributions_paid_3yr_cents": 600_000,
        "benefits_charged_3yr_cents": 200_000,
        "taxable_payroll_3yr_cents": 10_000_000,
        "expected_registration_version": expected_registration_version,
    }
    defaults.update(overrides)
    return defaults


def create_voluntary_contribution_payload(ui_rate_id, **overrides) -> dict:
    defaults = {
        "ui_rate_id": ui_rate_id,
        "proposed_amount_cents": 100_000,
        "decision_deadline": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_location_change_payload(employee_id, to_work_location_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "to_work_location_id": to_work_location_id,
        "effective_date": "2026-09-01T00:00:00Z",
        "reason": "Relocating",
    }
    defaults.update(overrides)
    return defaults


def create_agency_notice_payload(**overrides) -> dict:
    defaults = {
        "notice_type": "PENALTY_ASSESSMENT",
        "received_date": "2026-08-10T00:00:00Z",
        "response_due_date": "2026-09-10T00:00:00Z",
        "penalty_amount_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def create_abatement_request_payload(agency_notice_id, **overrides) -> dict:
    defaults = {
        "agency_notice_id": agency_notice_id,
        "abatement_type": "REASONABLE_CAUSE",
        "requested_amount_cents": 500_000,
        "reason": "Natural disaster disrupted payroll operations",
    }
    defaults.update(overrides)
    return defaults


def override_local_assignment_payload(employee_id, work_location_id,
                                      expected_employee_version, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "work_location_id": work_location_id,
        "effective_from": "2026-08-15T00:00:00Z",
        "override_reason": "Audit correction",
        "expected_employee_version": expected_employee_version,
    }
    defaults.update(overrides)
    return defaults
