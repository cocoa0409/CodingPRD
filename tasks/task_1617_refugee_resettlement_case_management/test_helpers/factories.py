"""Payload factories — input fields only, one per entity (PRD §3, §4)."""
import itertools

from .constants import (
    DEFAULT_AGENCY_CODE,
    DEFAULT_ARRIVAL_DATE,
    DEFAULT_OCCUPANCY_END,
    DEFAULT_OCCUPANCY_START,
)

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_case_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "case_number": f"CASE-{n:05d}",
        "agency_affiliate_code": DEFAULT_AGENCY_CODE,
        "household_size": 1,
        "scheduled_arrival_date": DEFAULT_ARRIVAL_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "case_id": None,
        "full_name": f"Member {n}",
        "date_of_birth": "1990-01-01",
        "relationship": "PRINCIPAL",
        "work_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_housing_unit_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "address": f"{n} Resettlement Way",
        "bedrooms": 1,
    }
    defaults.update(overrides)
    return defaults


def create_housing_setup_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "housing_unit_id": None,
        "occupancy_start": DEFAULT_OCCUPANCY_START,
        "occupancy_end": DEFAULT_OCCUPANCY_END,
    }
    defaults.update(overrides)
    return defaults


def create_furnish_payload(**overrides) -> dict:
    defaults = {"item": "BED"}
    defaults.update(overrides)
    return defaults


def create_benefit_application_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "member_id": None,
        "benefit_type": "SSN",
    }
    defaults.update(overrides)
    return defaults


def transition_application_payload(**overrides) -> dict:
    defaults = {"to_status": "FILED"}
    defaults.update(overrides)
    return defaults


def create_employment_plan_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "expected_case_version": None,
    }
    defaults.update(overrides)
    return defaults


def patch_employment_plan_payload(**overrides) -> dict:
    defaults = {
        "monthly_income_cents": 0,
        "trailing_3m_income_cents": 0,
        "employed_members_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_orientation_session_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "topic": "US_LAWS",
        "start_at": "2026-08-12T09:00:00Z",
        "end_at": "2026-08-12T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_case_note_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "case_id": None,
        "note_type": "GENERAL",
        "body": f"Note body {n}",
    }
    defaults.update(overrides)
    return defaults


def create_case_transfer_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "receiving_affiliate_code": "AFF-99",
        "reason": "SECONDARY_MIGRATION",
    }
    defaults.update(overrides)
    return defaults


def create_federal_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-10-01",
        "period_end": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def fulfill_benchmark_payload(**overrides) -> dict:
    defaults = {
        "fulfilled_on": "2026-08-15",
        "evidence_note_id": None,
    }
    defaults.update(overrides)
    return defaults
