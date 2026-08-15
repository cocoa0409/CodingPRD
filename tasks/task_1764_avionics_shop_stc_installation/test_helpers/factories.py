"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_tail_counter = itertools.count(1)

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "CUSTOMER_EMAIL": "customer@example.com",
    "CUSTOMER_KIND": "INDIVIDUAL",
    "MAKE_MODEL": "Cessna 182T",
    "BASELINE_WEIGHT": 1800.0,
    "BASELINE_ARM": 40.0,
    "CG_MIN": 35.0,
    "CG_MAX": 41.5,
    "SCOPE": "panel upgrade",
    "ESTIMATED_DOWNTIME_DAYS": 10,
    "QUOTED_LABOR_HOURS": 5,
    "BAY_CODE": "BAY-1",
    "BAY_WINDOW_START": "2026-08-01T00:00:00Z",
    "BAY_WINDOW_END": "2026-08-20T00:00:00Z",
    "LAYOUT_NOTES": "panel layout",
    "TASK_DESCRIPTION": "install task",
    "ESTIMATED_HOURS": 2.0,
    "GROUND_START": "2026-08-05T10:00:00Z",
    "GROUND_END": "2026-08-05T11:00:00Z",
    "FLIGHT_START": "2026-08-06T14:00:00Z",
    "FLIGHT_END": "2026-08-06T15:30:00Z",
    "STC_NUMBER": "STC-SA1000",
}


def unique_tail_number() -> str:
    """Distinct registration per call so multiple aircraft coexist in one test."""
    return f"N{next(_tail_counter):05d}T"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "contact_email": DEFAULTS["CUSTOMER_EMAIL"],
        "customer_kind": DEFAULTS["CUSTOMER_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tail_number": unique_tail_number(),
        "make_model": DEFAULTS["MAKE_MODEL"],
        "baseline_empty_weight_lb": DEFAULTS["BASELINE_WEIGHT"],
        "baseline_arm_in": DEFAULTS["BASELINE_ARM"],
        "cg_min_arm_in": DEFAULTS["CG_MIN"],
        "cg_max_arm_in": DEFAULTS["CG_MAX"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "scope_description": DEFAULTS["SCOPE"],
        "estimated_downtime_days": DEFAULTS["ESTIMATED_DOWNTIME_DAYS"],
        "quoted_labor_hours": DEFAULTS["QUOTED_LABOR_HOURS"],
        "bay_code": DEFAULTS["BAY_CODE"],
        "bay_window_start": DEFAULTS["BAY_WINDOW_START"],
        "bay_window_end": DEFAULTS["BAY_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def make_equipment_line(part_number, unit_price_cents, weight_lb, arm_in,
                        lead_time_days, quantity=1, description="") -> dict:
    return {
        "part_number": part_number,
        "description": description or part_number,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "weight_lb": weight_lb,
        "arm_in": arm_in,
        "lead_time_days": lead_time_days,
    }


def create_panel_design_payload(work_order_id, expected_work_order_version,
                                **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "expected_work_order_version": expected_work_order_version,
        "layout_notes": DEFAULTS["LAYOUT_NOTES"],
        "equipment_list": [],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_order_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "part_number": "GI275",
        "description": "Engine display",
        "quantity": 1,
        "unit_price_cents": 100000,
        "lead_time_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_install_task_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "task_kind": "INSTALLATION",
        "description": DEFAULTS["TASK_DESCRIPTION"],
        "estimated_hours": DEFAULTS["ESTIMATED_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_test_event_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "test_kind": "GROUND",
        "scheduled_start": DEFAULTS["GROUND_START"],
        "scheduled_end": DEFAULTS["GROUND_END"],
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_package_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "approval_path": "STC",
        "stc_number": DEFAULTS["STC_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_weight_balance_revision_payload(work_order_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "method": "INCREMENTAL",
        "added_items": [],
        "removed_weight_lb": 0,
    }
    defaults.update(overrides)
    # removed_arm_in is present exactly when a removal is recorded (PRD §3.7);
    # callers pass it explicitly alongside removed_weight_lb > 0.
    if defaults.get("removed_arm_in") is None:
        defaults.pop("removed_arm_in", None)
    return defaults
