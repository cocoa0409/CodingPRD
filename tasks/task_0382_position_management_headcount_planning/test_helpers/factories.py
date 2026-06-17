"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)
_cc_code_counter = itertools.count(1)
_grade_code_counter = itertools.count(1)


def unique_email(prefix="emp") -> str:
    return f"{prefix}{next(_email_counter):05d}@example.com"


def unique_cc_code(prefix="CC") -> str:
    return f"{prefix}{next(_cc_code_counter):05d}"


def unique_grade_code(prefix="GX") -> str:
    return f"{prefix}{next(_grade_code_counter):05d}"


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Employee",
        "email": unique_email(),
        "annual_salary_cents": 13000000,
    }
    defaults.update(overrides)
    return defaults


def create_grade_payload(**overrides) -> dict:
    defaults = {
        "code": unique_grade_code(),
        "band_min_cents": 10000000,
        "band_mid_cents": 12000000,
        "band_max_cents": 15000000,
        "rank": 7,
    }
    defaults.update(overrides)
    return defaults


def create_cost_center_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Cost Center",
        "code": unique_cc_code(),
        "annual_budget_cents": 100000000,
        "fte_cap": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(cost_center_id, grade_id, **overrides) -> dict:
    defaults = {
        "cost_center_id": cost_center_id,
        "grade_id": grade_id,
        "title": "Test Position",
        "fte": 0.5,
    }
    defaults.update(overrides)
    return defaults


def update_position_payload(**overrides) -> dict:
    # All fields optional; the caller supplies only the ones under test.
    return dict(overrides)


def lifecycle_payload(action, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_incumbent_payload(employee_id, start_date="2026-01-01", **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "start_date": start_date,
    }
    defaults.update(overrides)
    return defaults


def vacate_payload(vacate_date="2026-06-30", **overrides) -> dict:
    defaults = {"vacate_date": vacate_date}
    defaults.update(overrides)
    return defaults


def create_freeze_order_payload(effective_from, effective_to, reason="freeze", **overrides) -> dict:
    defaults = {
        "effective_from": effective_from,
        "effective_to": effective_to,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_requisition_payload(req_type="NEW_HIRE", justification="hire", **overrides) -> dict:
    defaults = {
        "req_type": req_type,
        "justification": justification,
    }
    defaults.update(overrides)
    return defaults


def create_reclass_request_payload(target_grade_id, justification="promo", **overrides) -> dict:
    defaults = {
        "target_grade_id": target_grade_id,
        "justification": justification,
    }
    defaults.update(overrides)
    return defaults


def approve_reclass_payload(**overrides) -> dict:
    # override is optional.
    return dict(overrides)


def create_forecast_period_payload(fiscal_label="FY26-Q1", planned_fte=2.0, **overrides) -> dict:
    defaults = {
        "fiscal_label": fiscal_label,
        "planned_fte": planned_fte,
    }
    defaults.update(overrides)
    return defaults


def snapshot_payload(expected_cost_center_version, **overrides) -> dict:
    defaults = {"expected_cost_center_version": expected_cost_center_version}
    defaults.update(overrides)
    return defaults


def create_budget_adjustment_payload(amount_cents, memo="adjustment", **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "memo": memo,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
