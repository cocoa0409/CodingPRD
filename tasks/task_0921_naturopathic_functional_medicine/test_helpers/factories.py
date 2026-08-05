"""Payload factories — one per write endpoint, input fields only."""

import itertools

_SKU_SEQ = itertools.count(1)
_LOT_SEQ = itertools.count(1)
_EMAIL_SEQ = itertools.count(1)


def next_sku(prefix: str = "SKU") -> str:
    return f"{prefix}-{next(_SKU_SEQ):04d}"


def next_lot_code(prefix: str = "LOT") -> str:
    return f"{prefix}-{next(_LOT_SEQ):04d}"


def next_email(local: str = "patient") -> str:
    return f"{local}{next(_EMAIL_SEQ)}@example.com"


def create_practitioner_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dr Nora Vance",
        "credential": "ND",
        "licensed_state_codes": ["OR"],
        "npi": "1234567893",
    }
    payload.update(overrides)
    return payload


def create_patient_payload(primary_practitioner_id: str = None, **overrides) -> dict:
    payload = {
        "full_name": "Ada Reyes",
        "email": next_email("ada"),
        "state_code": "OR",
    }
    if primary_practitioner_id is not None:
        payload["primary_practitioner_id"] = primary_practitioner_id
    payload.update(overrides)
    return payload


def create_intake_section_payload(section_type: str, **overrides) -> dict:
    payload = {
        "section_type": section_type,
        "payload_summary": f"digest for {section_type.lower()}",
    }
    payload.update(overrides)
    return payload


def create_membership_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "tier": "CORE",
        "cycle_start_date": "2026-05-01",
    }
    payload.update(overrides)
    return payload


def create_lab_order_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "panel_code": "SERUM_METABOLIC",
        "funding_source": "CASH",
        "requested_collection_date": "2026-05-04",
        "fasting_attested": True,
    }
    payload.update(overrides)
    return payload


def create_lab_result_payload(**overrides) -> dict:
    """Default analyte sits inside both ranges and is not critical."""
    payload = {
        "analyte_code": "TSH",
        "value": 2.0,
        "unit": "uIU/mL",
        "standard_low": 0.45,
        "standard_high": 4.50,
        "optimal_low": 1.00,
        "optimal_high": 2.50,
        "critical_low": 0.10,
        "critical_high": 10.00,
    }
    payload.update(overrides)
    return payload


def critical_potassium_payload(**overrides) -> dict:
    """Potassium at 12.0 is above critical_high, so it escalates the order."""
    payload = {
        "analyte_code": "K",
        "value": 12.0,
        "unit": "mmol/L",
        "standard_low": 3.5,
        "standard_high": 5.2,
        "optimal_low": 4.0,
        "optimal_high": 4.8,
        "critical_low": 2.5,
        "critical_high": 10.0,
    }
    payload.update(overrides)
    return payload


def create_protocol_payload(patient_id: str, expected_patient_version: int, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "title": "Foundational repletion",
        "symptom_score_baseline": 28,
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def create_protocol_item_payload(product_id: str, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "dose_amount_mg": 400,
        "frequency_per_day": 1,
        "duration_days": 60,
        "titration_interval_days": 14,
    }
    payload.update(overrides)
    return payload


def create_dispensary_product_payload(**overrides) -> dict:
    payload = {
        "sku": next_sku("MAG-GLY"),
        "name": "Magnesium Glycinate",
        "supplement_class": "VITAMIN_MINERAL",
        "retail_price_cents": 4995,
        "practitioner_cost_cents": 3000,
    }
    payload.update(overrides)
    return payload


def create_product_lot_payload(**overrides) -> dict:
    payload = {
        "lot_code": next_lot_code("L-2026"),
        "quantity_initial": 20,
        "expiry_date": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def create_dispense_payload(
    protocol_item_id: str, expected_protocol_version: int, **overrides
) -> dict:
    payload = {
        "protocol_item_id": protocol_item_id,
        "quantity": 1,
        "expected_protocol_version": expected_protocol_version,
    }
    payload.update(overrides)
    return payload


def create_encounter_payload(patient_id: str, practitioner_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "practitioner_id": practitioner_id,
        "modality": "IN_PERSON",
        "scheduled_start": "2026-06-01T09:00:00Z",
        "scheduled_end": "2026-06-01T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def complete_encounter_payload(**overrides) -> dict:
    payload = {
        "duration_minutes": 40,
        "service_code": "99214",
        "diagnosis_codes": ["R53.83"],
    }
    payload.update(overrides)
    return payload


def create_message_thread_payload(patient_id: str, practitioner_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "practitioner_id": practitioner_id,
        "subject": "rash question",
        "body": "started three days ago",
    }
    payload.update(overrides)
    return payload


def create_message_payload(body: str = "follow-up note", **overrides) -> dict:
    payload = {"body": body}
    payload.update(overrides)
    return payload


def create_superbill_payload(patient_id: str, encounter_id: str, **overrides) -> dict:
    payload = {"patient_id": patient_id, "encounter_id": encounter_id}
    payload.update(overrides)
    return payload


def superbill_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "recipient_name": "Cascade Endocrinology",
        "specialty": "ENDOCRINOLOGY",
        "reason": "persistent TSH elevation",
    }
    payload.update(overrides)
    return payload


def referral_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def adverse_reaction_payload(severity: str = "MILD", **overrides) -> dict:
    payload = {
        "severity": severity,
        "description": "palpitations and rash within 48 hours",
    }
    payload.update(overrides)
    return payload


def titration_decision_payload(current_symptom_score: int, **overrides) -> dict:
    payload = {"current_symptom_score": current_symptom_score}
    payload.update(overrides)
    return payload
