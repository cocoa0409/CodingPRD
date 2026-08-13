"""Payload factories — one per creatable entity, input fields only."""
import uuid

from .constants import (
    DEFAULT_BUDGET_CENTS,
    DEFAULT_EFFECTIVE_FROM,
    DEFAULT_ESTIMATED_LABOR_MINUTES,
    DEFAULT_EXPECTED_LIFE_MONTHS,
    DEFAULT_FREQUENCY_DAYS,
    DEFAULT_INSTALLED_ON,
    DEFAULT_LABOR_RATE_CENTS_PER_HOUR,
    DEFAULT_NOTICE_LEAD_HOURS,
    DEFAULT_PLAN_YEAR,
    DEFAULT_REPLACEMENT_COST_CENTS,
    DEFAULT_SCHEDULED_START,
    DEFAULT_TECHNICIAN_ID,
    DEFAULT_WARRANTY_MONTHS,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_property_payload(**overrides) -> dict:
    defaults = {
        "property_code": _code("PROP"),
        "display_name": "Test Property",
        "notice_lead_hours": DEFAULT_NOTICE_LEAD_HOURS,
        "default_labor_rate_cents_per_hour": DEFAULT_LABOR_RATE_CENTS_PER_HOUR,
    }
    defaults.update(overrides)
    return defaults


def create_building_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "building_label": "A",
        "floors": 1,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(building_id, **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "unit_number": "101",
        "occupancy_status": "VACANT",
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "component_type": "HVAC",
        "installed_on": DEFAULT_INSTALLED_ON,
        "warranty_months": DEFAULT_WARRANTY_MONTHS,
        "expected_life_months": DEFAULT_EXPECTED_LIFE_MONTHS,
        "replacement_cost_cents": DEFAULT_REPLACEMENT_COST_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_template_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "component_type": "HVAC",
        "task_name": "HVAC service",
        "frequency_days": DEFAULT_FREQUENCY_DAYS,
        "estimated_labor_minutes": DEFAULT_ESTIMATED_LABOR_MINUTES,
        "requires_evidence": False,
        "effective_from": DEFAULT_EFFECTIVE_FROM,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "plan_year": DEFAULT_PLAN_YEAR,
        "budget_cents": DEFAULT_BUDGET_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "batch_label": "batch-1",
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(batch_id, unit_id, template_id, asset_id, plan_id, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "unit_id": unit_id,
        "template_id": template_id,
        "asset_id": asset_id,
        "plan_id": plan_id,
        "scheduled_start": DEFAULT_SCHEDULED_START,
        "technician_id": DEFAULT_TECHNICIAN_ID,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_type": "FILTER_REPLACEMENT",
        "serial_or_lot": "LOT-1",
    }
    defaults.update(overrides)
    return defaults


def create_deficiency_payload(asset_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "severity": "HIGH",
        "description": "Corroded flue",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {"outcome": "PASS"}
    defaults.update(overrides)
    return defaults


def create_work_order_payload(deficiency_id, plan_id, expected_deficiency_version, **overrides) -> dict:
    defaults = {
        "deficiency_id": deficiency_id,
        "plan_id": plan_id,
        "estimated_cost_cents": 100_000,
        "assigned_technician_id": "tech-9",
        "expected_deficiency_version": expected_deficiency_version,
    }
    defaults.update(overrides)
    return defaults


def create_forecast_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "horizon_years": 5,
        "variant": "AGE_BASED",
    }
    defaults.update(overrides)
    return defaults
