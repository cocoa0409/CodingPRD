"""Payload factories — one per entity, client-supplied input fields only."""
from .constants import (
    ASSIGNMENT_EFFECTIVE_FROM,
    BUSINESS_DATE_2,
    NOTICE_ACKNOWLEDGED_AT,
    PERIOD_END_DATE,
    PERIOD_START_DATE,
)


def create_location_payload(**overrides) -> dict:
    """A Texas unit that claims a tip credit at the federal floor."""
    payload = {
        "name": "Dallas Unit",
        "state_code": "TX",
        "state_min_wage_cents": 725,
        "cash_wage_cents": 213,
        "tip_credit_enabled": True,
        "cc_fee_policy": "ACTUAL_ONLY",
        "service_charge_treatment": "WAGES",
    }
    payload.update(overrides)
    return payload


def create_job_role_payload(**overrides) -> dict:
    """A tipped server role that contributes 15% of tips and holds 10 points."""
    payload = {
        "code": "SERVER",
        "title": "Server",
        "tip_status": "TIPPED",
        "is_management": False,
        "pool_contribution_pct_bps": 1500,
        "pool_share_points": 10,
        "side_work_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_employee_payload(location_id: str, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "full_name": "Ana Reyes",
        "external_payroll_ref": "E1",
        "monthly_tip_baseline_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_role_assignment_payload(
    employee_id: str, job_role_id: str, **overrides
) -> dict:
    payload = {
        "employee_id": employee_id,
        "job_role_id": job_role_id,
        "effective_from": ASSIGNMENT_EFFECTIVE_FROM,
        "tip_credit_notice_acknowledged_at": NOTICE_ACKNOWLEDGED_AT,
        "is_primary": True,
    }
    payload.update(overrides)
    return payload


def create_tip_pool_policy_payload(location_id: str, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "pool_type": "TIPPED_ONLY",
        "contribution_basis": "TIPS_RECEIVED_PCT",
        "share_basis": "HOURS_WEIGHTED_POINTS",
        "cc_fee_pass_through": True,
    }
    payload.update(overrides)
    return payload


def create_pay_period_payload(location_id: str, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "start_date": PERIOD_START_DATE,
        "end_date": PERIOD_END_DATE,
    }
    payload.update(overrides)
    return payload


def create_shift_payload(
    employee_id: str,
    location_id: str,
    job_role_id: str,
    pay_period_id: str,
    **overrides,
) -> dict:
    """A 480-minute shift running 16:00 to midnight on 2026-08-04."""
    payload = {
        "employee_id": employee_id,
        "location_id": location_id,
        "job_role_id": job_role_id,
        "pay_period_id": pay_period_id,
        "business_date": BUSINESS_DATE_2,
        "start_at": "2026-08-04T16:00:00Z",
        "end_at": "2026-08-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def declare_tips_payload(
    declared_cash_tips_cents: int = 0, declared_charged_tips_cents: int = 0
) -> dict:
    return {
        "declared_cash_tips_cents": declared_cash_tips_cents,
        "declared_charged_tips_cents": declared_charged_tips_cents,
    }


def create_service_charge_payload(location_id: str, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "business_date": BUSINESS_DATE_2,
        "amount_cents": 6000,
        "description": "20 percent large-party charge",
    }
    payload.update(overrides)
    return payload


def create_shift_tip_pool_payload(location_id: str, **overrides) -> dict:
    payload = {"location_id": location_id, "business_date": BUSINESS_DATE_2}
    payload.update(overrides)
    return payload


def create_dispute_payload(
    pay_line_id: str, raised_by_employee_id: str, **overrides
) -> dict:
    payload = {
        "pay_line_id": pay_line_id,
        "raised_by_employee_id": raised_by_employee_id,
        "category": "TIP_CREDIT",
        "claimed_amount_cents": 2000,
        "narrative": "Side work was billed against my tip credit",
    }
    payload.update(overrides)
    return payload


def adjudicate_dispute_payload(resolution: str, **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


def create_back_wage_correction_payload(
    pay_line_id: str, expected_pay_line_version: int, **overrides
) -> dict:
    payload = {
        "pay_line_id": pay_line_id,
        "amount_cents": 1000,
        "reason_code": "SIDE_WORK_OVERAGE",
        "expected_pay_line_version": expected_pay_line_version,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
