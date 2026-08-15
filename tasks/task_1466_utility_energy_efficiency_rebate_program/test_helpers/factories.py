"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    """Process-unique suffix so unique-constrained fields never collide."""
    return f"{prefix}-{next(_counter)}"


def create_program_year_payload(**overrides) -> dict:
    defaults = {
        "program_code": _uniq("PROG"),
        "program_year_label": "PY2026",
        "budget_cap_cents": TEST_DEFAULTS["BUDGET_CAP_CENTS"],
        "savings_goal_kwh": TEST_DEFAULTS["SAVINGS_GOAL_KWH"],
    }
    defaults.update(overrides)
    return defaults


def create_measure_payload(program_year_id: str, **overrides) -> dict:
    defaults = {
        "program_year_id": program_year_id,
        "measure_code": _uniq("M"),
        "measure_name": "Test Measure",
        "base_rate_cents": TEST_DEFAULTS["BASE_RATE_CENTS"],
        "deemed_kwh_per_unit": TEST_DEFAULTS["DEEMED_KWH_PER_UNIT"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_ally_payload(**overrides) -> dict:
    defaults = {
        "ally_name": "Acme Efficiency",
        "license_number": _uniq("LIC"),
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(program_year_id: str, trade_ally_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "program_year_id": program_year_id,
        "trade_ally_id": trade_ally_id,
        "customer_account_number": f"CUST-{n}",
        "service_address": f"{n} Test Ave",
        "invoice_number": f"INV-{n}",
        "invoice_date": TEST_DEFAULTS["INVOICE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(application_id: str, measure_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "measure_id": measure_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_savings_claim_payload(line_item_id: str, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "claim_method": "DEEMED",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_schedule_payload(**overrides) -> dict:
    defaults = {"scheduled_on": "2026-08-13"}
    defaults.update(overrides)
    return defaults


def create_inspection_completion_payload(outcome="PASSED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_evaluation_adjustment_payload(program_year_id: str, **overrides) -> dict:
    defaults = {
        "program_year_id": program_year_id,
        "realization_rate_pct": 80,
        "effective_on": "2026-08-13",
    }
    defaults.update(overrides)
    return defaults
