"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

# Unique-ish suffixes so payloads never collide across tests within a run.
_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    """Only the required program fields by default; all policy knobs overridable."""
    defaults = {
        "name": f"RecProg-{_n()}",
        "max_points_per_nomination": TEST_DEFAULTS["MAX_POINTS_PER_NOMINATION"],
        "point_cost_rate_cents": TEST_DEFAULTS["POINT_COST_RATE_CENTS"],
        "state_rate_map": dict(TEST_DEFAULTS["STATE_RATE_MAP"]),
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Dept-{i}",
        "chargeback_account_code": f"GL-{i:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(department_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "employee_ref": f"EMP-REF-{i}",
        "full_name": f"Employee {i}",
        "department_id": department_id,
        "hire_date": "2021-06-15",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(program_id, department_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "department_id": department_id,
        "period_start_date": TEST_DEFAULTS["BUDGET_WINDOW_START"],
        "period_end_date": TEST_DEFAULTS["BUDGET_WINDOW_END"],
        "allocated_points": TEST_DEFAULTS["ALLOCATED_POINTS"],
    }
    defaults.update(overrides)
    return defaults


def create_nomination_payload(program_id, nominee_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "program_id": program_id,
        "nominee_id": nominee_id,
        "type": "PEER",
        "points_requested": 100,
        "reason_code": "TEAMWORK",
        "message": f"nomination {i}",
        "idempotency_key": f"nom-key-{i}",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Vendor-{i}",
        "vendor_code": f"VC-{i}",
        "daily_ship_capacity": 10,
        "lead_time_business_days": 1,
        "supported_categories": ["MERCH"],
    }
    defaults.update(overrides)
    return defaults


def create_catalog_item_payload(vendor_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "vendor_id": vendor_id,
        "sku": f"SKU-{i}",
        "name": f"Item {i}",
        "category": "MERCH",
        "point_cost": 100,
        "cash_value_cents": 500,
        "taxable_class": "MERCHANDISE",
        "de_minimis_eligible": False,
        "active_window_start": TEST_DEFAULTS["ITEM_WINDOW_START"],
        "active_window_end": TEST_DEFAULTS["ITEM_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_redemption_order_payload(catalog_item_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "catalog_item_id": catalog_item_id,
        "quantity": 1,
        "idempotency_key": f"ord-key-{i}",
    }
    defaults.update(overrides)
    return defaults


def create_abuse_flag_payload(employee_id, program_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "program_id": program_id,
        "rule_code": "MANUAL_REVIEW",
        "details": {"note": "manual audit"},
    }
    defaults.update(overrides)
    return defaults


def create_accrual_run_payload(program_id, period_year, period_month, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period_year": period_year,
        "period_month": period_month,
    }
    defaults.update(overrides)
    return defaults


def create_points_adjustment_payload(program_id, points, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "points": points,
        "reason": f"adjustment {_n()}",
    }
    defaults.update(overrides)
    return defaults
