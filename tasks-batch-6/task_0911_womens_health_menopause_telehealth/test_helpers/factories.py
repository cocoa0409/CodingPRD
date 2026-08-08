"""Payload factories — one per entity, input fields only.

Only fields the client actually supplies on a write are included; system- and
computed-source fields are omitted (the server mints those).
"""
import uuid

from .constants import DEFAULT_SLOT_START, DEFAULT_SLOT_END


def _unique_email(prefix: str = "patient") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}@example.com"


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "email": _unique_email(),
        "date_of_birth": "1970-01-01",
        "state_code": "CA",
        "billing_mode": "CASH",
        "menopause_stage": "MENOPAUSE",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Test",
        "specialty": "GYNECOLOGY",
        "npi": uuid.uuid4().int.__str__()[:10],
        "visit_fee_cents": 15000,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(**overrides) -> dict:
    defaults = {
        "payer_name": "BlueGrid",
        "deductible_cents": 25000,
        "coinsurance_rate": 0.20,
        "out_of_pocket_max_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(**overrides) -> dict:
    defaults = {
        "symptom_ratings": [],
        "reported_conditions": ["NONE"],
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "provider_id": None,
        "intake_assessment_id": None,
        "scheduled_start": DEFAULT_SLOT_START,
        "scheduled_end": DEFAULT_SLOT_END,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(**overrides) -> dict:
    defaults = {
        "visit_id": None,
        "hrt_type": "ESTROGEN_PATCH",
        "days_supply_per_fill": 30,
        "total_refills_authorized": 2,
        "lab_required_before_refill": False,
        "coverage_days": 90,
        "refill_price_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_lab_order_payload(**overrides) -> dict:
    defaults = {"panel_type": "HORMONE"}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "plan_tier": "ESSENTIAL",
        "expected_patient_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_message_payload(**overrides) -> dict:
    defaults = {"body": "Test message"}
    defaults.update(overrides)
    return defaults
