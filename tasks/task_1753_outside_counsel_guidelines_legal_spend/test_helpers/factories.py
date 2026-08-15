"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from test_helpers.constants import DEPT_DEFAULTS, TEST_DEFAULTS


def create_legal_department_payload(**overrides) -> dict:
    defaults = dict(DEPT_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_panel_firm_payload(**overrides) -> dict:
    defaults = {"firm_name": TEST_DEFAULTS["FIRM_NAME"]}
    defaults.update(overrides)
    return defaults


def create_guideline_version_payload(**overrides) -> dict:
    defaults = {"version_label": "OCG-2026-A", "effective_date": "2026-09-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_matter_payload(**overrides) -> dict:
    defaults = {
        "panel_firm_id": overrides.pop("panel_firm_id", None),
        "title": TEST_DEFAULTS["MATTER_TITLE"],
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_rate_card_payload(**overrides) -> dict:
    defaults = {
        "effective_year": TEST_DEFAULTS["EFFECTIVE_YEAR"],
        "expected_panel_firm_version": overrides.pop("expected_panel_firm_version", 1),
    }
    defaults.update(overrides)
    return defaults


def create_timekeeper_payload(**overrides) -> dict:
    defaults = {"full_name": "Pat Partner", "tk_class": "PARTNER"}
    defaults.update(overrides)
    return defaults


def create_rate_row_payload(**overrides) -> dict:
    defaults = {
        "timekeeper_id": overrides.pop("timekeeper_id", None),
        "hourly_rate_cents": TEST_DEFAULTS["PARTNER_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def make_line_item(**overrides) -> dict:
    defaults = {
        "timekeeper_id": overrides.pop("timekeeper_id", None),
        "utbms_task_code": "L110",
        "narrative": "Review motion L110",
        "hours": 1.00,
        "rate_cents": TEST_DEFAULTS["PARTNER_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "invoice_number": "INV-001",
        "billing_period_start": TEST_DEFAULTS["PERIOD_START"],
        "billing_period_end": TEST_DEFAULTS["PERIOD_END"],
        "expected_matter_version": overrides.pop("expected_matter_version", 1),
        "line_items": overrides.pop("line_items", []),
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {"rationale": "The rejection is not supported by the record"}
    defaults.update(overrides)
    return defaults


def create_accrual_payload(**overrides) -> dict:
    defaults = {"period_year": 2026, "period_month": 8, "amount_cents": 500_000}
    defaults.update(overrides)
    return defaults


def put_forecast_payload(**overrides) -> dict:
    defaults = {"lifecycle_estimate_cents": 10_000_000}
    defaults.update(overrides)
    return defaults


def recompute_scorecard_payload(**overrides) -> dict:
    defaults = {"period_year": 2026, "period_month": 8}
    defaults.update(overrides)
    return defaults


def set_clock_payload(**overrides) -> dict:
    defaults = {"to_iso8601": "2026-08-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults
