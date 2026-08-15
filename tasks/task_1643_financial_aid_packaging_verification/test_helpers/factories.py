"""Payload factories — one per creatable entity, input fields only.

Computed fields (efc/cohort/pool aggregates/snapshots) are never set here;
server-computed fields in a request payload are only ever sent by tests that
explicitly probe computed-field suppression.
"""
from .constants import (
    CLOCK_TEST,
    COA_IN_STATE_CENTS,
    COA_OUT_OF_STATE_CENTS,
    DEFAULT_PELL_SCHEDULE,
    ISIR_RECEIVED_PRIORITY,
    PRIORITY_DEADLINE,
    VERIFICATION_FLAG_RATE,
    YEAR_CODE,
)


def create_aid_year_payload(**overrides) -> dict:
    defaults = {
        "year_code": YEAR_CODE,
        "coa_in_state_cents": COA_IN_STATE_CENTS,
        "coa_out_of_state_cents": COA_OUT_OF_STATE_CENTS,
        "priority_deadline": PRIORITY_DEADLINE,
        "pell_schedule": [dict(row) for row in DEFAULT_PELL_SCHEDULE],
        "verification_tracking_flag_rate": VERIFICATION_FLAG_RATE,
    }
    defaults.update(overrides)
    return defaults


def create_fund_type_payload(aid_year_id, **overrides) -> dict:
    defaults = {
        "aid_year_id": aid_year_id,
        "fund_code": "PELL",
        "category": "FEDERAL_TITLE_IV",
        "need_based": True,
        "annual_cap_cents": 739500,
        "pool_budget_cents": 0,
        "packaging_rank": 1,
        "requires_verification_complete": False,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(ssn, **overrides) -> dict:
    defaults = {
        "ssn": ssn,
        "full_name": f"Student {ssn}",
        "email": f"student-{ssn}@example.edu",
        "residency": "IN_STATE",
        "dependency_status": "DEPENDENT",
        "enrollment_status": "FULL_TIME",
        "grade_level": 1,
    }
    defaults.update(overrides)
    return defaults


def create_isir_payload(student_id, aid_year_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "aid_year_id": aid_year_id,
        "transaction_number": 1,
        "received_at": ISIR_RECEIVED_PRIORITY,
        "household_size": 4,
        "number_in_college": 1,
        "agi_cents": 2000000,
        "untaxed_income_cents": 0,
        "asset_net_worth_cents": 0,
        "cps_selection_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_conflicting_info_case_payload(student_id, aid_year_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "aid_year_id": aid_year_id,
        "subject_field": "agi_cents",
    }
    defaults.update(overrides)
    return defaults


def create_pj_case_payload(student_id, aid_year_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "aid_year_id": aid_year_id,
        "adjustment_type": "EFC_ADJUSTMENT",
        "requested_delta_cents": -500000,
        "justification": "Documented special circumstance on file with the office",
        "documentation_complete": True,
    }
    defaults.update(overrides)
    return defaults


def create_award_package_payload(student_id, aid_year_id, **overrides) -> dict:
    defaults = {"student_id": student_id, "aid_year_id": aid_year_id}
    defaults.update(overrides)
    return defaults


def line_acceptance(award_line_id, accept_cents) -> dict:
    return {"award_line_id": award_line_id, "accept_cents": accept_cents}


def create_disbursement_payload(award_line_id, **overrides) -> dict:
    defaults = {
        "award_line_id": award_line_id,
        "scheduled_cents": 100000,
        "term_code": "2026-FALL",
    }
    defaults.update(overrides)
    return defaults


def create_external_aid_payload(student_id, aid_year_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "aid_year_id": aid_year_id,
        "source_name": "Community Scholarship",
        "amount_cents": 900000,
        "counts_against_coa": True,
    }
    defaults.update(overrides)
    return defaults


def resolution_plan_step(award_line_id, reduce_by_cents) -> dict:
    return {"award_line_id": award_line_id, "reduce_by_cents": reduce_by_cents}


def reconciliation_adjustment_payload(award_line_id, **overrides) -> dict:
    defaults = {
        "award_line_id": award_line_id,
        "adjust_cents": -200,
        "reason_code": "FEDERAL_UNDERREPORT",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601=CLOCK_TEST) -> dict:
    return {"to_iso8601": to_iso8601}
