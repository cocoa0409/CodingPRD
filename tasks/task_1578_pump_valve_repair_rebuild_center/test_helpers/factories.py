"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from .constants import (
    DEFAULT_PLANNED_END,
    DEFAULT_PLANNED_START,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    TEST_DEFAULTS,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": f"Customer {_unique('C')}",
        "account_number": _unique("AC"),
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        "warranty_terms_days": TEST_DEFAULTS["WARRANTY_TERMS_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "serial_number": _unique("SN"),
        "equipment_class": "GENERAL_VALVE",
        "manufacturer": "Flowserve",
        "model": "G1",
    }
    defaults.update(overrides)
    # Conditional nameplate fields (PRD §3.2): fill sane class defaults when the
    # caller selected a class but did not supply the required field.
    if defaults.get("equipment_class") == "PUMP" and "rated_flow_gpm" not in overrides:
        defaults["rated_flow_gpm"] = TEST_DEFAULTS["RATED_FLOW_GPM"]
    if defaults.get("equipment_class") == "SAFETY_RELIEF_VALVE" and "set_pressure_psig" not in overrides:
        defaults["set_pressure_psig"] = TEST_DEFAULTS["SET_PRESSURE_PSIG"]
    return defaults


def create_repair_order_payload(customer_id: str, asset_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "asset_id": asset_id,
        "failure_mode": "SEAT_LEAKAGE",
        "failure_description": "passing at seat",
        "intake_priority": "STANDARD",
        "planned_start_date": DEFAULT_PLANNED_START,
        "planned_end_date": DEFAULT_PLANNED_END,
        "estimated_bay_hours": TEST_DEFAULTS["ESTIMATED_BAY_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_report_payload(**overrides) -> dict:
    defaults = {
        "findings_summary": "teardown findings",
        "recommended_action": "REPAIR",
        "estimated_labor_hours": 1,
        "part_lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(repair_order_id: str, capacity_window_id: str,
                         expected_repair_order_version: int, **overrides) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "capacity_window_id": capacity_window_id,
        "labor_hours": TEST_DEFAULTS["LABOR_HOURS"],
        "labor_rate_cents": TEST_DEFAULTS["LABOR_RATE_CENTS"],
        "part_lines": [],
        "expected_repair_order_version": expected_repair_order_version,
    }
    defaults.update(overrides)
    return defaults


def quote_part_line(part_id: str, quantity: int, unit_price_cents: int,
                    substitution_for_part_id: str = None) -> dict:
    line = {"part_id": part_id, "quantity": quantity, "unit_price_cents": unit_price_cents}
    if substitution_for_part_id is not None:
        line["substitution_for_part_id"] = substitution_for_part_id
    return line


def create_part_payload(**overrides) -> dict:
    defaults = {
        "part_number": _unique("PN"),
        "description": "catalog part",
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_pool_unit_payload(customer_id: str, asset_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "asset_id": asset_id}
    defaults.update(overrides)
    return defaults


def create_test_run_payload(**overrides) -> dict:
    defaults = {
        "test_type": "PERFORMANCE_CURVE",
        "measured_points": [
            {"duty_pct": 100, "measured_value": 100, "reference_value": 100},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "set_pressure_psig": TEST_DEFAULTS["SET_PRESSURE_PSIG"],
        "seat_leakage_class": "CLASS_V",
    }
    defaults.update(overrides)
    return defaults


# PRD §3.6: "a new window may not overlap an existing one". Tests routinely build
# several shops (hence several capacity windows) against one server, so a shared
# constant default interval is a PRD-impossible precondition — every default
# window after the first would be rejected with ERR_WINDOW_OVERLAP. When the
# caller does not pin dates, hand out disjoint 31-day intervals from a
# session-scoped counter, far from the 2026 dates used by explicit-date tests.
_window_default_seq = itertools.count()
_WINDOW_DEFAULT_BASE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _default_window_interval() -> tuple:
    n = next(_window_default_seq)
    start = _WINDOW_DEFAULT_BASE + timedelta(days=62 * n)
    end = start + timedelta(days=31)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


def create_capacity_window_payload(**overrides) -> dict:
    defaults = {
        "label": _unique("WIN"),
        "bay_hours_capacity": TEST_DEFAULTS["WINDOW_CAPACITY"],
    }
    if "window_start" not in overrides and "window_end" not in overrides:
        defaults["window_start"], defaults["window_end"] = _default_window_interval()
    else:
        defaults["window_start"] = DEFAULT_WINDOW_START
        defaults["window_end"] = DEFAULT_WINDOW_END
    defaults.update(overrides)
    return defaults
