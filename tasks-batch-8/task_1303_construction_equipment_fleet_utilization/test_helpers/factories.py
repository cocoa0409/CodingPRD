"""Payload factories -- one per entity, input fields only (per PRD section 4)."""
from .constants import TEST_DEFAULTS


def create_equipment_class_payload(**overrides) -> dict:
    defaults = {
        "class_code": "EXC-320",
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "external_daily_rate_cents": TEST_DEFAULTS["EXTERNAL_DAILY_RATE_CENTS"],
        "weekend_multiplier_bp": TEST_DEFAULTS["WEEKEND_MULTIPLIER_BP"],
        "idle_day_multiplier_bp": TEST_DEFAULTS["IDLE_DAY_MULTIPLIER_BP"],
        "service_interval_hours": TEST_DEFAULTS["SERVICE_INTERVAL_HOURS"],
        "idle_alert_utilization_bp": TEST_DEFAULTS["IDLE_ALERT_UTILIZATION_BP"],
        "expected_life_hours": TEST_DEFAULTS["EXPECTED_LIFE_HOURS"],
        "salvage_value_cents": TEST_DEFAULTS["SALVAGE_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(class_id, **overrides) -> dict:
    defaults = {
        "unit_tag": "UNIT-1",
        "class_id": class_id,
        "ownership": "OWNED",
        "acquisition_cost_cents": TEST_DEFAULTS["ACQUISITION_COST_CENTS"],
        "acquisition_date": "2026-01-01",
        "useful_life_months": TEST_DEFAULTS["USEFUL_LIFE_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {
        "project_code": "PRJ-A",
        "name": "Project A",
        "equipment_budget_cents": TEST_DEFAULTS["PROJECT_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(equipment_id, project_id, expected_equipment_version, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "project_id": project_id,
        "start_date": "2026-08-03",
        "end_date": "2026-08-10",
        "expected_equipment_version": expected_equipment_version,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(equipment_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "kind": "REPAIR",
    }
    defaults.update(overrides)
    return defaults


def create_mechanic_payload(home_project_id, **overrides) -> dict:
    defaults = {
        "mechanic_code": "MECH-1",
        "name": "Mac One",
        "home_project_id": home_project_id,
    }
    defaults.update(overrides)
    return defaults


def create_lowboy_payload(**overrides) -> dict:
    defaults = {
        "lowboy_code": "LB-1",
        "capacity_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_transport_job_payload(equipment_id, from_project_id, to_project_id, lowboy_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "from_project_id": from_project_id,
        "to_project_id": to_project_id,
        "lowboy_id": lowboy_id,
        "depart_at": "2026-08-12T08:00:00Z",
        "arrive_at": "2026-08-12T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(**overrides) -> dict:
    defaults = {
        "recorded_date": "2026-08-03",
        "engine_hours_delta_milli": 8000,
        "fuel_used_milliliters": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_damage_report_payload(equipment_id, project_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "project_id": project_id,
        "description": "panel damage",
        "abuse_flag": False,
        "line_items": [{"description": "panel", "amount_cents": 1000}],
    }
    defaults.update(overrides)
    return defaults
