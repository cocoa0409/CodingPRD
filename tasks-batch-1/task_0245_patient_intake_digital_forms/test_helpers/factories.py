"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_clinic_payload(**overrides) -> dict:
    defaults = {"name": "Test Clinic"}
    defaults.update(overrides)
    return defaults


def create_provider_payload(clinic_id, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "full_name": "Dr Test",
        "required_consent_codes": [],
        "questionnaire_required_sections": [],
    }
    defaults.update(overrides)
    return defaults


def create_exam_room_payload(clinic_id, **overrides) -> dict:
    defaults = {"clinic_id": clinic_id, "label": "Room 1"}
    defaults.update(overrides)
    return defaults


def create_patient_payload(clinic_id, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "legal_name": "Test Patient",
        "date_of_birth": "1990-01-01",
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(clinic_id, provider_id, patient_id, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "provider_id": provider_id,
        "patient_id": patient_id,
        "start_utc": "2026-06-10T10:00:00.000Z",
        "end_utc": "2026-06-10T10:30:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_intake_session_payload(appointment_id, **overrides) -> dict:
    defaults = {"appointment_id": appointment_id}
    defaults.update(overrides)
    return defaults


def create_insurance_card_payload(intake_session_id, **overrides) -> dict:
    defaults = {
        "intake_session_id": intake_session_id,
        "payer_name": "Acme",
        "member_id": "M1",
    }
    defaults.update(overrides)
    return defaults


def resolve_eligibility_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_consent_document_payload(intake_session_id, consent_code, **overrides) -> dict:
    defaults = {"intake_session_id": intake_session_id, "consent_code": consent_code}
    defaults.update(overrides)
    return defaults


def sign_consent_payload(signer_name="Test Patient", **overrides) -> dict:
    defaults = {"signer_name": signer_name}
    defaults.update(overrides)
    return defaults


def create_questionnaire_payload(intake_session_id, answered_sections=None, **overrides) -> dict:
    defaults = {"intake_session_id": intake_session_id}
    if answered_sections is not None:
        defaults["answered_sections"] = answered_sections
    defaults.update(overrides)
    return defaults


def patch_questionnaire_payload(answered_sections, **overrides) -> dict:
    defaults = {"answered_sections": answered_sections}
    defaults.update(overrides)
    return defaults


def create_copay_payment_payload(intake_session_id, amount_cents, expected_intake_session_version, **overrides) -> dict:
    defaults = {
        "intake_session_id": intake_session_id,
        "amount_cents": amount_cents,
        "expected_intake_session_version": expected_intake_session_version,
    }
    defaults.update(overrides)
    return defaults


def call_queue_entry_payload(exam_room_id, **overrides) -> dict:
    defaults = {"exam_room_id": exam_room_id}
    defaults.update(overrides)
    return defaults


def create_room_booking_payload(exam_room_id, queue_entry_id, start_utc, end_utc, expected_exam_room_version, **overrides) -> dict:
    defaults = {
        "exam_room_id": exam_room_id,
        "queue_entry_id": queue_entry_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_exam_room_version": expected_exam_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_reminder_payload(intake_session_id, target_kind, scheduled_utc, scheduled_local_min, **overrides) -> dict:
    defaults = {
        "intake_session_id": intake_session_id,
        "target_kind": target_kind,
        "scheduled_utc": scheduled_utc,
        "scheduled_local_min": scheduled_local_min,
    }
    defaults.update(overrides)
    return defaults


def create_demographics_sync_payload(intake_session_id, idempotency_key, synced_legal_name, synced_phone, **overrides) -> dict:
    defaults = {
        "intake_session_id": intake_session_id,
        "idempotency_key": idempotency_key,
        "synced_legal_name": synced_legal_name,
        "synced_phone": synced_phone,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(clinic_id, to_iso8601, **overrides) -> dict:
    defaults = {"clinic_id": clinic_id, "to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
