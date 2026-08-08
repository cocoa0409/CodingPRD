"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the fields a client supplies on create; system and
computed fields (status, version, derived counters, computed volumes/classes) are
never included. Callers pass **overrides for the values a test controls.
"""
import uuid

from .constants import (
    STANDARD_CIRCUMFERENCES,
    STANDARD_CONTRALATERAL,
    STANDARD_INTERVAL_CM,
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
)


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "mrn": f"MRN-{_unique_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(patient_id, expected_patient_version, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "body_region": "LEFT_ARM",
        "etiology": "SECONDARY",
        "isl_stage": "STAGE_II",
        "interval_cm": STANDARD_INTERVAL_CM,
        "circumferences_cm": list(STANDARD_CIRCUMFERENCES),
        "contralateral_circumferences_cm": list(STANDARD_CONTRALATERAL),
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "body_region": "LEFT_ARM",
        "payer_name": "Acme Health",
        "auth_number": f"AUTH-{_unique_suffix()}",
        "visit_cap": 5,
        "effective_start_date": DEFAULT_WINDOW_START,
        "effective_end_date": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(patient_id, evaluation_id, authorization_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "evaluation_id": evaluation_id,
        "authorization_id": authorization_id,
        "prescribed_daily_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_therapist_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Therapist",
        "credential": "CLT",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(plan_id, authorization_id, therapist_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "authorization_id": authorization_id,
        "therapist_id": therapist_id,
        "scheduled_start": "2026-06-01T09:00:00Z",
        "scheduled_end": "2026-06-01T10:00:00Z",
        "cdt_component": "MLD",
    }
    defaults.update(overrides)
    return defaults


def create_garment_order_payload(patient_id, evaluation_id, expected_patient_version, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "evaluation_id": evaluation_id,
        "quantity": 1,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_dme_item_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{_unique_suffix()}",
        "l_code": "L8100",
        "initial_stock_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_dispense_payload(garment_order_id, dme_item_id, **overrides) -> dict:
    defaults = {
        "garment_order_id": garment_order_id,
        "dme_item_id": dme_item_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_reassessment_payload(plan_id, baseline_evaluation_id, current_evaluation_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "baseline_evaluation_id": baseline_evaluation_id,
        "current_evaluation_id": current_evaluation_id,
    }
    defaults.update(overrides)
    return defaults


def create_adherence_log_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "log_date": "2026-06-01",
        "minutes_completed": 60,
        "wore_garment": True,
    }
    defaults.update(overrides)
    return defaults
