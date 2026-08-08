"""Payload factories — one per entity, input fields only."""

from .constants import CLOCK_STARTUP_UTC, TEST_DEFAULTS


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": "Pat Example",
        "date_of_birth": "1980-01-01",
        "email": "pat.example@example.com",
        "sex_at_birth": "MALE",
    }
    payload.update(overrides)
    return payload


def create_provider_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dr Ada Reyes",
        "provider_type": "PHYSICIAN",
        "npi": TEST_DEFAULTS["PHYSICIAN_NPI"],
    }
    payload.update(overrides)
    return payload


def publish_protocol_payload(published_by_provider_id: str, **overrides) -> dict:
    payload = {
        "hormone_type": "TESTOSTERONE",
        "title": "T pellet protocol v1",
        "published_by_provider_id": published_by_provider_id,
    }
    payload.update(overrides)
    return payload


def sign_consent_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "hormone_type": "TESTOSTERONE",
        "protocol_version": 1,
        "consented_max_dose_mg": 2000,
    }
    payload.update(overrides)
    return payload


def create_consult_payload(patient_id: str, physician_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "physician_id": physician_id,
        "hormone_type": "TESTOSTERONE",
        "prescribed_dose_mg": 1000,
        "symptom_score": 55,
        "indication": "Hypogonadism",
    }
    payload.update(overrides)
    return payload


def create_lab_panel_payload(patient_id: str, ordered_by_provider_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "ordered_by_provider_id": ordered_by_provider_id,
        "analyte": "TOTAL_TESTOSTERONE",
        "value": 400,
        "drawn_at": CLOCK_STARTUP_UTC,
    }
    payload.update(overrides)
    return payload


def create_pellet_lot_payload(**overrides) -> dict:
    payload = {
        "lot_code": "T200-A",
        "hormone_type": "TESTOSTERONE",
        "strength_mg": 200,
        "expiry_date": TEST_DEFAULTS["LOT_EXPIRY"],
        "qty_received": 20,
    }
    payload.update(overrides)
    return payload


def create_standing_order_payload(physician_id: str, **overrides) -> dict:
    payload = {
        "physician_id": physician_id,
        "scope_hormone_types": ["TESTOSTERONE", "ESTRADIOL"],
        "scope_injection_types": ["B12", "LIPOTROPIC", "VITAMIN_D", "GLUTATHIONE"],
        "max_dose_mg": TEST_DEFAULTS["STANDING_ORDER_MAX_DOSE_MG"],
        "valid_from": TEST_DEFAULTS["STANDING_ORDER_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["STANDING_ORDER_VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def create_procedure_payload(
    patient_id: str, provider_id: str, consult_id: str, standing_order_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "consult_id": consult_id,
        "standing_order_id": standing_order_id,
        "procedure_type": "INITIAL",
        "room_code": "RM1",
        "scheduled_start": "2026-06-01T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_injection_visit_payload(
    patient_id: str, provider_id: str, standing_order_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "standing_order_id": standing_order_id,
        "injection_type": "B12",
        "room_code": "RM1",
        "scheduled_start": "2026-06-01T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_membership_payload(patient_id: str, **overrides) -> dict:
    payload = {"patient_id": patient_id, "tier": "PLUS"}
    payload.update(overrides)
    return payload


def create_series_pack_payload(patient_id: str, **overrides) -> dict:
    payload = {"patient_id": patient_id, "series_type": "B12"}
    payload.update(overrides)
    return payload


def create_adverse_event_payload(patient_id: str, reported_by_provider_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "reported_by_provider_id": reported_by_provider_id,
        "severity": "MILD",
        "narrative": "Transient soreness at the insertion site",
        "onset_at": "2026-05-01T06:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_financing_plan_payload(patient_id: str, procedure_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "procedure_id": procedure_id,
        "principal_cents": 58300,
        "down_payment_cents": 11660,
        "installment_count": 6,
        "first_due_date": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def eligibility_hold_payload(hold_kind: str, hold_action: str, **overrides) -> dict:
    payload = {"hold_kind": hold_kind, "hold_action": hold_action}
    payload.update(overrides)
    return payload


def recall_payload(**overrides) -> dict:
    payload = {"severity_class": "CLASS_II", "recall_reason": "Sterility excursion at the fill line"}
    payload.update(overrides)
    return payload
