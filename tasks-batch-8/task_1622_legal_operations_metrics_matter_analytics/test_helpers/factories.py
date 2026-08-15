"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


DEFAULTS = {
    "DEPT_NAME": "Default Legal",
    "PERIOD_LABEL": "FY2026",
    "PERIOD_START": "2026-01-01",
    "PERIOD_END": "2026-12-31",
    "FIRM_TIER": "TIER_1",
    "FIRM_RATE_CENTS": 25000,
    "COUNSEL_CAPACITY_HOURS": 2000,
    "COUNSEL_LOADED_RATE_CENTS": 15000,
    "MATTER_TITLE": "Test Matter",
    "ASSIGNMENT_HOURS": 5,
}


def create_department_payload(**overrides) -> dict:
    defaults = {"name": f"{DEFAULTS['DEPT_NAME']} {_next()}"}
    defaults.update(overrides)
    return defaults


def create_fiscal_period_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "label": f"{DEFAULTS['PERIOD_LABEL']}-{n}",
        "start_date": DEFAULTS["PERIOD_START"],
        "end_date": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_practice_area_payload(**overrides) -> dict:
    n = _next()
    defaults = {"code": f"PA{n:02d}", "display_name": f"Practice Area {n}"}
    defaults.update(overrides)
    return defaults


def create_matter_type_payload(**overrides) -> dict:
    n = _next()
    defaults = {"code": f"MT{n:02d}", "display_name": f"Matter Type {n}"}
    defaults.update(overrides)
    return defaults


def create_firm_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Firm-{n}",
        "tier": DEFAULTS["FIRM_TIER"],
        "blended_hourly_rate_cents": DEFAULTS["FIRM_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_counsel_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Counsel {n}",
        "email": f"counsel{n}@example.com",
        "annual_capacity_hours": DEFAULTS["COUNSEL_CAPACITY_HOURS"],
        "loaded_hourly_cost_cents": DEFAULTS["COUNSEL_LOADED_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_matter_payload(
    practice_area_id: str,
    matter_type_id: str,
    fiscal_period_id: str,
    lead_counsel_id: str,
    **overrides,
) -> dict:
    n = _next()
    defaults = {
        "matter_number": f"LGL-2026-{n:05d}",
        "title": f"{DEFAULTS['MATTER_TITLE']} {n}",
        "practice_area_id": practice_area_id,
        "matter_type_id": matter_type_id,
        "fiscal_period_id": fiscal_period_id,
        "lead_counsel_id": lead_counsel_id,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(counsel_id: str, allocated_hours: int = None, **overrides) -> dict:
    defaults = {
        "counsel_id": counsel_id,
        "allocated_hours": (
            DEFAULTS["ASSIGNMENT_HOURS"] if allocated_hours is None else allocated_hours
        ),
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(
    fiscal_period_id: str,
    practice_area_id: str,
    allocated_cents: int,
    matter_type_id=None,
    **overrides,
) -> dict:
    defaults = {
        "fiscal_period_id": fiscal_period_id,
        "practice_area_id": practice_area_id,
        "allocated_cents": allocated_cents,
    }
    if matter_type_id is not None:
        defaults["matter_type_id"] = matter_type_id
    defaults.update(overrides)
    return defaults


def create_accrual_payload(
    matter_id: str,
    fiscal_period_id: str,
    firm_id: str,
    amount_cents: int,
    **overrides,
) -> dict:
    defaults = {
        "matter_id": matter_id,
        "fiscal_period_id": fiscal_period_id,
        "firm_id": firm_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(
    matter_id: str,
    firm_id: str,
    fiscal_period_id: str,
    amount_cents: int,
    invoice_number: str = None,
    **overrides,
) -> dict:
    n = _next()
    defaults = {
        "matter_id": matter_id,
        "firm_id": firm_id,
        "fiscal_period_id": fiscal_period_id,
        "invoice_number": invoice_number or f"INV-{n:05d}",
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_dashboard_payload(fiscal_period_id: str, snapshot_label: str = None, **overrides) -> dict:
    n = _next()
    defaults = {
        "fiscal_period_id": fiscal_period_id,
        "snapshot_label": snapshot_label or f"snap-{n}",
    }
    defaults.update(overrides)
    return defaults
