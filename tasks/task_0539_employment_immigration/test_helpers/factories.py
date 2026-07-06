"""Payload factories — one per entity, input fields only.

Each factory provides PRD-faithful defaults and accepts **overrides. FEINs and
passport numbers are auto-unique per process so a single test can create several
distinct employers/beneficiaries without collision.
"""
import itertools

_fein_counter = itertools.count(1)
_passport_counter = itertools.count(1)


def unique_fein() -> str:
    return f"{100000000 + next(_fein_counter):09d}"


def unique_passport() -> str:
    return f"P-{next(_passport_counter):06d}"


def employer_payload(**overrides) -> dict:
    defaults = {
        "fein": unique_fein(),
        "legal_name": "Test Employer",
        "employee_count": 10,
    }
    defaults.update(overrides)
    return defaults


def pwd_payload(employer_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "soc_code": "15-1252",
        "job_title": "Software Engineer",
        "area_code": "AREA_A",
        "wage_level": "LEVEL_II",
        "wage_source": "OES",
        "oes_wage_cents": 10000000,
        "validity_start": "2026-05-01T00:00:00Z",
        "validity_end": "2027-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def perm_case_payload(employer_id: str, pwd_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "pwd_id": pwd_id,
        "job_title": "Software Engineer",
        "offered_wage_cents": 12000000,
    }
    defaults.update(overrides)
    return defaults


def recruitment_step_payload(perm_case_id: str, **overrides) -> dict:
    defaults = {
        "perm_case_id": perm_case_id,
        "step_type": "JOB_ORDER",
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2026-05-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def lca_payload(employer_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "soc_code": "15-1252",
        "worksite_areas": ["AREA_A"],
        "area_wage_map": {"AREA_A": 10000000},
        "offered_wage_cents": 12000000,
        "prevailing_wage_cents": 10000000,
        "validity_start": "2026-05-01T00:00:00Z",
        "validity_end": "2028-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def beneficiary_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Beneficiary",
        "passport_number": unique_passport(),
    }
    defaults.update(overrides)
    return defaults


def cap_program_payload(fiscal_year: int = 2027, selection_quota: int = 5, **overrides) -> dict:
    defaults = {
        "fiscal_year": fiscal_year,
        "selection_quota": selection_quota,
    }
    defaults.update(overrides)
    return defaults


def registration_payload(employer_id: str, beneficiary_id: str, fiscal_year: int = 2027, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "beneficiary_id": beneficiary_id,
        "fiscal_year": fiscal_year,
    }
    defaults.update(overrides)
    return defaults


def h1b_petition_payload(employer_id: str, lca_id: str, beneficiary_id: str,
                         registration_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "lca_id": lca_id,
        "beneficiary_id": beneficiary_id,
        "registration_id": registration_id,
        "worksite_area": "AREA_A",
        "employment_start": "2026-10-01T00:00:00Z",
        "employment_end": "2029-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def i140_petition_payload(employer_id: str, beneficiary_id: str, category: str = "EB2", **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "beneficiary_id": beneficiary_id,
        "category": category,
    }
    defaults.update(overrides)
    return defaults
