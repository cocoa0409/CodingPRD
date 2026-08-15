"""Payload factories — one per entity, input fields only.

All factories accept **overrides so individual tests can control exactly the
values their assertions depend on.
"""
from .constants import TEST_DEFAULTS


def create_sign_up_period_payload(**overrides) -> dict:
    defaults = {
        "name": "Fall 2026 Sign-Up",
        "effective_start_date": TEST_DEFAULTS["EFFECTIVE_START_DATE"],
        "effective_end_date": TEST_DEFAULTS["EFFECTIVE_END_DATE"],
        "spread_limit_minutes": TEST_DEFAULTS["SPREAD_LIMIT_MINUTES"],
        "paid_break_minutes": TEST_DEFAULTS["PAID_BREAK_MINUTES"],
        "extra_board_ratio_pct": TEST_DEFAULTS["EXTRA_BOARD_RATIO_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_run_piece(report_minutes: int, release_minutes: int, platform_minutes: int) -> dict:
    return {
        "report_minutes": report_minutes,
        "release_minutes": release_minutes,
        "platform_minutes": platform_minutes,
    }


def create_run_payload(**overrides) -> dict:
    defaults = {
        "run_number": "R1",
        "service_date": "2026-09-07",
        "pieces": [create_run_piece(300, 700, 400)],
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "employee_number": "E1",
        "full_name": "Op One",
        "hire_date": "2000-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_bid_entry_payload(operator_id, run_id, preference_rank, expected_version, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "run_id": run_id,
        "preference_rank": preference_rank,
        "expected_sign_up_period_version": expected_version,
    }
    payload.update(overrides)
    return payload


def create_absence_case_payload(operator_id, absence_date="2026-09-07", reason_code="SICK", **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "absence_date": absence_date,
        "reason_code": reason_code,
    }
    payload.update(overrides)
    return payload


def create_vacation_slot_payload(**overrides) -> dict:
    defaults = {
        "week_start_date": "2026-10-05",
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_grievance_case_payload(filed_by_operator_id, sign_up_period_id, **overrides) -> dict:
    payload = {
        "filed_by_operator_id": filed_by_operator_id,
        "sign_up_period_id": sign_up_period_id,
        "category": "SENIORITY_BYPASS",
        "detail": "detail",
    }
    payload.update(overrides)
    return payload


def schedule_revision_payload(new_runs) -> dict:
    return {"new_runs": new_runs}
