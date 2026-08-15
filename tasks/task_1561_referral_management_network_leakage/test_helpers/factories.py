"""Payload factories — one per creatable entity, input fields only (PRD §3)."""


def create_referring_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "Dr A",
        "npi": "2000000001",
        "specialty": "INTERNAL_MEDICINE",
    }
    defaults.update(overrides)
    return defaults


def create_specialist_payload(**overrides) -> dict:
    defaults = {
        "name": "Dr Cardio",
        "npi": "1000000001",
        "specialty": "CARDIOLOGY",
        "base_region": "NORTH",
        "weekly_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": "PPO-1",
        "payer_name": "PayerOne",
        "payer_mix_factor": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(insurance_plan_id: str, **overrides) -> dict:
    defaults = {
        "mrn": "M001",
        "full_name": "Pat One",
        "date_of_birth": "1980-01-01",
        "region": "NORTH",
        "insurance_plan_id": insurance_plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_participation_payload(specialist_id: str, insurance_plan_id: str, **overrides) -> dict:
    defaults = {
        "specialist_id": specialist_id,
        "insurance_plan_id": insurance_plan_id,
        "tier": "PREFERRED",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_auth_rule_payload(specialty: str, insurance_plan_id: str, **overrides) -> dict:
    defaults = {
        "specialty": specialty,
        "insurance_plan_id": insurance_plan_id,
        "requires_auth": True,
        "auth_validity_days": 10,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "specialty": "CARDIOLOGY",
        "diagnosis_code": "I10",
        "urgency": "ROUTINE",
    }
    defaults.update(overrides)
    return defaults


def book_appointment_payload(expected_referral_version: int, scheduled_start: str,
                             scheduled_end: str, **overrides) -> dict:
    defaults = {
        "expected_referral_version": expected_referral_version,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def confirm_appointment_payload(channel: str = "PHONE") -> dict:
    return {"confirmation_channel": channel}


def consult_note_payload(**overrides) -> dict:
    defaults = {
        "findings_summary": "OK",
        "follow_up_recommended": False,
    }
    defaults.update(overrides)
    return defaults


def loop_closure_payload(expected_referral_version: int, outcome: str, **overrides) -> dict:
    defaults = {
        "expected_referral_version": expected_referral_version,
        "outcome": outcome,
        "verification_note": "Loop verified",
    }
    defaults.update(overrides)
    return defaults


def record_auth_outcome_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def cancel_referral_payload(reason: str = "PATIENT_DECLINED") -> dict:
    return {"reason": reason}


def document_patient_choice_payload(choice_type: str, note: str = "") -> dict:
    return {"choice_type": choice_type, "note": note}


def period_close_payload(period_start: str, period_end: str) -> dict:
    return {"period_start": period_start, "period_end": period_end}
