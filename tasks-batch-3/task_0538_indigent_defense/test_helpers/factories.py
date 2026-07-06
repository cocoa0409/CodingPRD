"""Payload factories — one per entity, input fields only."""
from .constants import LARGE_BUDGET_CENTS


def create_office_payload(**overrides) -> dict:
    defaults = {
        "name": "Public Defender Office",
        "annual_voucher_budget_cents": LARGE_BUDGET_CENTS,
        "recoupment_basis": "SCHEDULE",
    }
    defaults.update(overrides)
    return defaults


def create_attorney_payload(office_id, **overrides) -> dict:
    defaults = {
        "office_id": office_id,
        "name": "Test Attorney",
        "attorney_type": "STAFF",
        "bar_number": "BAR-0001",
        "hourly_rate_cents": 15_000,
        "max_weighted_caseload": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_courtroom_payload(**overrides) -> dict:
    defaults = {
        "name": "Dept 1",
        "courthouse": "Main Courthouse",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(office_id, **overrides) -> dict:
    defaults = {
        "office_id": office_id,
        "defendant_name": "Test Defendant",
        "charge_class": "MISDEMEANOR",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "household_income_cents": 800_000,
        "household_size": 2,
        "asset_value_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_conflict_check_payload(case_id, attorney_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "attorney_id": attorney_id,
        "co_defendant_names": [],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(case_id, attorney_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "attorney_id": attorney_id,
    }
    defaults.update(overrides)
    return defaults


def create_court_event_payload(case_id, courtroom_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "courtroom_id": courtroom_id,
        "event_type": "ARRAIGNMENT",
        "scheduled_start": "2026-06-10T09:00:00Z",
        "scheduled_end": "2026-06-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "service_type": "INVESTIGATOR",
        "estimated_hours": 10.0,
        "estimated_rate_cents": 8_000,
    }
    defaults.update(overrides)
    return defaults


def create_voucher_payload(case_id, attorney_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "attorney_id": attorney_id,
        "voucher_type": "PANEL_FEE",
        "claimed_hours": 5.0,
    }
    defaults.update(overrides)
    return defaults
