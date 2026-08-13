"""Payload factories — one per creatable entity, input fields only.

Email/name uniqueness within a test comes from a process-local counter; the
database resets before every test, so counter reuse across tests is safe.
"""
import itertools

from .constants import CYCLE_WINDOW, WINDOW

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# ---------------------------------------------------------------------------
# Students / donors / funds
# ---------------------------------------------------------------------------

def create_student_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "full_name": f"Test Student {i}",
        "email": f"student-{i}@test.example",
        "grade_level": 12,
        "gpa_hundredths": 350,
        "residency_state": "CA",
        "intended_major": "STEM",
        "household_income_cents": 5000000,
        "efc_cents": 0,
        "cost_of_attendance_cents": 3000000,
        "institution_name": "State U",
    }
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Test Donor {i}",
        "contact_email": f"donor-{i}@test.example",
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Test Fund {i}",
        "committed_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Programs / applications / components
# ---------------------------------------------------------------------------

def create_program_payload(donor_id, fund_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Test Program {i}",
        "donor_id": donor_id,
        "fund_id": fund_id,
        "program_type": "MERIT",
        "match_policy": "HOLISTIC",
        "stacking_scope": "ANNUAL",
        "award_amount_cents": 500000,
        "max_recipients": 2,
        "min_gpa_hundredths": 300,
        "required_residency_state": "CA",
        "max_household_income_cents": 10000000,
        "application_open_at": WINDOW["OPEN_AT"],
        "application_close_at": WINDOW["CLOSE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(student_id, program_id, **overrides) -> dict:
    defaults = {"student_id": student_id, "program_id": program_id}
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {"component_type": "ESSAY", "required": True}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Review cycles / scores
# ---------------------------------------------------------------------------

def create_cycle_payload(program_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "program_id": program_id,
        "label": f"CYCLE-{i}",
        "starts_on": CYCLE_WINDOW["STARTS_ON"],
        "ends_on": CYCLE_WINDOW["ENDS_ON"],
        "quorum_count": 1,
        "selection_quota": 1,
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(cycle_id, application_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "application_id": application_id,
        "academic_score": 90,
        "essay_score": 90,
        "need_score": 90,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Awards / disbursements / adjustments
# ---------------------------------------------------------------------------

def create_award_payload(application_id, student_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "student_id": student_id,
        "amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(award_id, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "term_seq": 1,
        "amount_cents": 500000,
        "scheduled_date": "2026-08-01",
        "term_start_date": "2026-08-01",
        "term_end_date": "2027-01-31",
        "institution_name": "State U",
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(award_id, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "reason": "DATA_ERROR",
        "delta_cents": -100000,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Renewal evaluations / donor reports
# ---------------------------------------------------------------------------

def create_renewal_payload(award_id, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "term_label": "2027-SPRING",
        "reported_gpa_hundredths": 300,
        "reported_credits": 14,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(donor_id, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "period_start": "2026-08-01",
        "period_end": "2027-08-01",
    }
    defaults.update(overrides)
    return defaults
