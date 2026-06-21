"""Payload factories — one per entity, input fields only.

Every factory emits only the client-supplied (source: input) fields the PRD
declares for that create. Computed and system fields are never included.
Required-vs-optional follows the PRD: is_veteran / has_disability and
required_for_completion are optional (they have server-side defaults), so they
are omitted unless explicitly overridden.
"""
from .constants import (
    BASE_WAGE_CENTS,
    DEFAULT_OJT_HOURS_REQUIRED,
    DEFAULT_RTI_HOURS_REQUIRED,
)

DEFAULTS = {
    "SPONSOR_NAME": "Test Sponsor LLC",
    "EIN": "12-3456789",
    "CONTACT_EMAIL": "sponsor@test.example",
    "OCCUPATION_CODE": "47-2111.00",
    "OCCUPATION_TITLE": "Electrician",
    "JOURNEYWORKER_NAME": "Test Journeyworker",
    "APPRENTICE_NAME": "Test Apprentice",
    "START_DATE": "2026-01-01",
    "WORK_DATE": "2026-02-01",
    "SESSION_DATE": "2026-02-02",
    "ATTAINED_ON": "2026-02-02",
    "COURSE_CODE": "RTI-101",
    "MILESTONE_TITLE": "Safety Competency",
}


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["SPONSOR_NAME"],
        "ein": DEFAULTS["EIN"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(sponsor_id: str, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "occupation_code": DEFAULTS["OCCUPATION_CODE"],
        "occupation_title": DEFAULTS["OCCUPATION_TITLE"],
        "completion_type": "HOURS_BASED",
        "ojt_hours_required": DEFAULT_OJT_HOURS_REQUIRED,
        "rti_hours_required": DEFAULT_RTI_HOURS_REQUIRED,
        "base_journeyworker_wage_cents": BASE_WAGE_CENTS,
        "journeyman_ratio": 4,
    }
    defaults.update(overrides)
    return defaults


def create_wage_step_payload(program_id: str, step_number: int,
                             ojt_hours_threshold: int, wage_pct: float,
                             **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "step_number": step_number,
        "ojt_hours_threshold": ojt_hours_threshold,
        "wage_pct": wage_pct,
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(program_id: str, sequence: int, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "sequence": sequence,
        "title": DEFAULTS["MILESTONE_TITLE"],
    }
    defaults.update(overrides)
    return defaults


def create_journeyworker_payload(sponsor_id: str, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "full_name": DEFAULTS["JOURNEYWORKER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_apprentice_payload(sponsor_id: str, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "full_name": DEFAULTS["APPRENTICE_NAME"],
        "gender": "MALE",
        "race_ethnicity": "WHITE",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(program_id: str, apprentice_id: str,
                             journeyworker_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "apprentice_id": apprentice_id,
        "journeyworker_id": journeyworker_id,
        "start_date": DEFAULTS["START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def register_agreement_payload(expected_program_version: int, **overrides) -> dict:
    defaults = {"expected_program_version": expected_program_version}
    defaults.update(overrides)
    return defaults


def create_ojt_entry_payload(agreement_id: str, start_time: int, end_time: int,
                             credited_hours: float, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "work_date": DEFAULTS["WORK_DATE"],
        "start_time": start_time,
        "end_time": end_time,
        "credited_hours": credited_hours,
    }
    defaults.update(overrides)
    return defaults


def create_rti_record_payload(agreement_id: str, instruction_hours: float,
                              **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "course_code": DEFAULTS["COURSE_CODE"],
        "session_date": DEFAULTS["SESSION_DATE"],
        "instruction_hours": instruction_hours,
    }
    defaults.update(overrides)
    return defaults


def create_milestone_attainment_payload(agreement_id: str, milestone_id: str,
                                        **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "milestone_id": milestone_id,
        "attained_on": DEFAULTS["ATTAINED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_eeo_report_payload(program_id: str, cohort_basis: str,
                              **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "cohort_basis": cohort_basis,
    }
    defaults.update(overrides)
    return defaults
