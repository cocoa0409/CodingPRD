"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next(tag: str) -> str:
    return f"{tag}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "company_name": f"Customer-{n}",
        "email": f"customer-{n}@example.com",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_material_grade_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["GRADE"])
    defaults["code"] = _next("AL")
    defaults["thickness_tiers"] = [{"max_thickness_mm": 1.0, "tier_index": 0}]
    defaults.update(overrides)
    return defaults


def create_sheet_stock_payload(grade_id: str, **overrides) -> dict:
    defaults = {
        "grade_id": grade_id,
        "thickness_mm": 1.0,
        "width_mm": 1200,
        "height_mm": 2400,
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(station: str = "LASER", **overrides) -> dict:
    defaults = {
        "name": _next(station.title()),
        "station": station,
        "shift_minutes_per_day": TEST_DEFAULTS["SHIFT_MINUTES_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_outside_vendor_payload(process: str = "PLATING", **overrides) -> dict:
    defaults = {
        "name": _next(f"{process.title()}Co"),
        "process": process,
        "lead_time_days": 7,
        "base_cost_cents_per_part": 350,
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_payload(grade_id: str, **overrides) -> dict:
    defaults = {
        "grade_id": grade_id,
        "thickness_mm": 1.0,
        "bbox_width_mm": 100,
        "bbox_height_mm": 100,
        "hole_count": 0,
        "hole_diameter_mm": 20,
        "corner_fillet_count": 0,
        "bend_count": 0,
        "weld_inches": 0,
        "finish": "NONE",
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(customer_id: str, lines=None, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "expedite_tier": "STANDARD",
    }
    if lines is not None:
        defaults["lines"] = lines
    defaults.update(overrides)
    return defaults


def create_inspection_report_payload(**overrides) -> dict:
    defaults = {
        "flatness_deviation_mm": 0.5,
        "measured_diagonal_mm": 400,
        "dimensional_pass": True,
    }
    defaults.update(overrides)
    return defaults


def create_scrap_credit_payload(customer_id: str, sheet_stock_id: str,
                                **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sheet_stock_id": sheet_stock_id,
    }
    defaults.update(overrides)
    return defaults
