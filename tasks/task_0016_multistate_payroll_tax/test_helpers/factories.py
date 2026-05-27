"""Payload factories — one per entity, input fields only.

Driven by PRD §3 entity-by-entity field lists. Every field defaulted here matches the
PRD's stated default; all overrides flow through `**overrides`.
"""
from typing import Optional


# ─── Employee ─────────────────────────────────────────────────────────────

def create_employee_payload(
    full_name: str = "Test Employee",
    work_state_code: str = "CA",
    residence_state_code: str = "CA",
    locality_code: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "work_state_code": work_state_code,
        "residence_state_code": residence_state_code,
    }
    if locality_code is not None:
        payload["locality_code"] = locality_code
    payload.update(overrides)
    return payload


def update_employee_status_payload(status: str) -> dict:
    return {"status": status}


# ─── W4Form ───────────────────────────────────────────────────────────────

def create_w4_form_payload(
    employee_id: str,
    tax_year: int = 2025,
    filing_status: str = "SINGLE",
    **overrides,
) -> dict:
    payload = {
        "employee_id": employee_id,
        "tax_year": tax_year,
        "filing_status": filing_status,
    }
    payload.update(overrides)
    return payload


# ─── PaycheckRun ──────────────────────────────────────────────────────────

def create_paycheck_run_payload(
    pay_period_start: str = "2025-11-01T00:00:00.000Z",
    pay_period_end: str = "2025-11-15T23:59:59.999Z",
    pay_date: str = "2025-11-15T00:00:00.000Z",
    **overrides,
) -> dict:
    payload = {
        "pay_period_start": pay_period_start,
        "pay_period_end": pay_period_end,
        "pay_date": pay_date,
    }
    payload.update(overrides)
    return payload


def pay_paycheck_run_payload(is_year_end_run: Optional[bool] = None) -> dict:
    payload: dict = {}
    if is_year_end_run is not None:
        payload["is_year_end_run"] = is_year_end_run
    return payload


# ─── Paycheck ─────────────────────────────────────────────────────────────

def create_paycheck_payload(
    paycheck_run_id: str,
    employee_id: str,
    pay_type: str = "REGULAR",
    **overrides,
) -> dict:
    payload = {
        "paycheck_run_id": paycheck_run_id,
        "employee_id": employee_id,
        "pay_type": pay_type,
    }
    payload.update(overrides)
    return payload


def regular_paycheck_payload(
    paycheck_run_id: str,
    employee_id: str,
    regular_hours_e2: int = 4000,
    hourly_rate_cents: int = 5000,
    **overrides,
) -> dict:
    payload = create_paycheck_payload(
        paycheck_run_id=paycheck_run_id,
        employee_id=employee_id,
        pay_type="REGULAR",
        regular_hours_e2=regular_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    payload.update(overrides)
    return payload


def overtime_paycheck_payload(
    paycheck_run_id: str,
    employee_id: str,
    overtime_hours_e2: int = 4000,
    hourly_rate_cents: int = 2500,
    **overrides,
) -> dict:
    payload = create_paycheck_payload(
        paycheck_run_id=paycheck_run_id,
        employee_id=employee_id,
        pay_type="OVERTIME",
        overtime_hours_e2=overtime_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    payload.update(overrides)
    return payload


def double_paycheck_payload(
    paycheck_run_id: str,
    employee_id: str,
    double_hours_e2: int = 2000,
    hourly_rate_cents: int = 2500,
    **overrides,
) -> dict:
    payload = create_paycheck_payload(
        paycheck_run_id=paycheck_run_id,
        employee_id=employee_id,
        pay_type="DOUBLE",
        double_hours_e2=double_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    payload.update(overrides)
    return payload


def retro_paycheck_payload(
    paycheck_run_id: str,
    employee_id: str,
    retro_amount_cents: int = 150000,
    **overrides,
) -> dict:
    payload = create_paycheck_payload(
        paycheck_run_id=paycheck_run_id,
        employee_id=employee_id,
        pay_type="RETRO",
        retro_amount_cents=retro_amount_cents,
    )
    payload.update(overrides)
    return payload


# ─── GarnishmentOrder ─────────────────────────────────────────────────────

def create_garnishment_order_payload(
    employee_id: str,
    order_type: str = "CHILD_SUPPORT",
    weekly_cap_cents: int = 30000,
    original_balance_cents: int = 100000,
    served_on: str = "2025-06-01T00:00:00.000Z",
    **overrides,
) -> dict:
    payload = {
        "employee_id": employee_id,
        "order_type": order_type,
        "weekly_cap_cents": weekly_cap_cents,
        "original_balance_cents": original_balance_cents,
        "served_on": served_on,
    }
    payload.update(overrides)
    return payload


# ─── TaxRateTable ─────────────────────────────────────────────────────────

def create_tax_rate_table_payload(
    jurisdiction: str,
    tax_year: int,
    filing_status: str,
    brackets_json: list,
    supplemental_flat_basis_points: int,
) -> dict:
    return {
        "jurisdiction": jurisdiction,
        "tax_year": tax_year,
        "filing_status": filing_status,
        "brackets_json": brackets_json,
        "supplemental_flat_basis_points": supplemental_flat_basis_points,
    }


# ─── Remittance ───────────────────────────────────────────────────────────

def remit_payload(paid_cents: int, expected_remittance_version: int) -> dict:
    return {
        "paid_cents": paid_cents,
        "expected_remittance_version": expected_remittance_version,
    }


# ─── Test-driving (PRD §2.10) ─────────────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def set_ytd_payload(**ytd_fields) -> dict:
    """Pass any subset of: ytd_wages_cents, ytd_fed_withheld_cents,
    ytd_ss_wages_cents, ytd_medicare_wages_cents."""
    return dict(ytd_fields)
