"""Payload factories — one per entity, input fields only.

Convention: passing an override value of None REMOVES the key from the
payload, which is how tests exercise optional-field defaults and
missing-required-field validation.
"""
from .constants import (
    DEFAULT_CONTRACT_AMOUNT_CENTS,
    DEFAULT_CRANE_REF,
    DEFAULT_EQUIPMENT_HOURLY_RATE_CENTS,
    DEFAULT_LIFT_END,
    DEFAULT_LIFT_START,
)


def _apply_overrides(defaults: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if value is None:
            defaults.pop(key, None)
        else:
            defaults[key] = value
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Project",
        "customer_name": "Acme Industrial",
        "site_address": "1 Plant Rd",
        "billing_mode": "TM",
        "contract_amount_cents": DEFAULT_CONTRACT_AMOUNT_CENTS,
        "equipment_hourly_rate_cents": DEFAULT_EQUIPMENT_HOURLY_RATE_CENTS,
        "retainage_pct": 0.10,
        "ot_basis": "DAILY_OT",
    }
    return _apply_overrides(defaults, overrides)


def create_site_survey_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "survey_date": "2026-08-01",
        "anchor_bolt_count": 24,
        "anchor_tolerance_mm": 3.0,
        "anchor_measured_max_deviation_mm": 1.5,
        "overhead_clearance_mm": 6000,
        "foundation_pour_date": "2026-08-01T00:00:00Z",
    }
    return _apply_overrides(defaults, overrides)


def create_safety_plan_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "plan_document_ref": "DOC-SP-1",
        "loto_procedure_ref": "DOC-LOTO-1",
    }
    return _apply_overrides(defaults, overrides)


def create_lockout_window_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "feeder_id": "F-1",
        "starts_at": "2026-08-10T10:00:00Z",
        "ends_at": "2026-08-10T14:00:00Z",
    }
    return _apply_overrides(defaults, overrides)


def create_rigging_plan_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "expected_project_version": None,
        "lift_weight_tons": 40,
        "crane_model": "GROVE GMK5250",
        "planned_crane_capacity_tons": 50,
        "rigging_config": "SINGLE_CRANE",
    }
    return _apply_overrides(defaults, overrides)


def create_lift_permit_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "crane_ref": DEFAULT_CRANE_REF,
        "lift_starts_at": DEFAULT_LIFT_START,
        "lift_ends_at": DEFAULT_LIFT_END,
        "road_permit_required": False,
    }
    return _apply_overrides(defaults, overrides)


def create_alignment_record_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "measurement_point": "PUMP-MOTOR",
        "tolerance_class": "PRECISION",
        "measured_offset_mils": 1.5,
        "measured_angular_mils_per_in": 0.4,
    }
    return _apply_overrides(defaults, overrides)


def create_checklist_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "items": [
            {"item_key": "GROUT", "description": "grout cured", "required": True},
        ],
    }
    return _apply_overrides(defaults, overrides)


def create_labor_entry_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "worker_ref": "U-1001",
        "classification": "MW_JOURNEYMAN",
        "work_date": "2026-08-08",
        "hours_worked": 8,
        "shift": "DAY",
    }
    return _apply_overrides(defaults, overrides)


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "project_id": None,
        "kind": "PROGRESS",
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
    }
    return _apply_overrides(defaults, overrides)


def create_review_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    return _apply_overrides(defaults, overrides)
