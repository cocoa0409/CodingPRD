"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS, TIMELINE


def create_provider_payload(**overrides) -> dict:
    payload = {
        "npi": "1000000001",
        "full_name": "Dr Sleep",
        "provider_type": "SLEEP_PHYSICIAN",
    }
    payload.update(overrides)
    return payload


def create_payer_payload(**overrides) -> dict:
    payload = {"name": "MedFirst", "payer_kind": "MEDICAL"}
    payload.update(overrides)
    return payload


def create_patient_payload(medical_payer_id: str = None, **overrides) -> dict:
    payload = {
        "mrn": "MRN-001",
        "full_name": "Pat One",
        "date_of_birth": "1975-03-02",
        "epworth_score": TEST_DEFAULTS["epworth_score"],
    }
    if medical_payer_id is not None:
        payload["medical_payer_id"] = medical_payer_id
    payload.update(overrides)
    return payload


def create_sleep_study_payload(
    patient_id: str, ordering_physician_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "ordering_physician_id": ordering_physician_id,
        "modality": "HSAT",
        "study_purpose": "DIAGNOSTIC",
    }
    payload.update(overrides)
    return payload


def sleep_study_results_payload(**overrides) -> dict:
    payload = {
        "performed_on": TIMELINE["study_performed_on"],
        "respiratory_events": 240,
        "recording_minutes": 480,
        "artifact_pct": 0,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(
    patient_id: str,
    referring_physician_id: str,
    treating_dentist_id: str,
    diagnostic_study_id: str,
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "referring_physician_id": referring_physician_id,
        "treating_dentist_id": treating_dentist_id,
        "diagnostic_study_id": diagnostic_study_id,
        "cpap_history": "FAILURE",
        "cpap_nights_used": 45,
        "cpap_documented_on": TIMELINE["cpap_documented_on"],
    }
    payload.update(overrides)
    # An optional field the caller explicitly clears is omitted rather than sent as
    # a JSON null: the PRD declares cpap_documented_on optional, not nullable.
    return {key: value for key, value in payload.items() if value is not None}


def create_written_order_payload(
    patient_id: str, ordering_physician_id: str, expected_patient_version: int, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "ordering_physician_id": ordering_physician_id,
        "item_hcpcs": "E0486",
        "order_date": TIMELINE["order_date"],
        "f2f_encounter_date": TIMELINE["f2f_encounter_date"],
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def create_prior_auth_payload(
    patient_id: str, payer_id: str, referral_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "payer_id": payer_id,
        "referral_id": referral_id,
        "requested_hcpcs": "E0486",
    }
    payload.update(overrides)
    return payload


def create_lab_order_payload(referral_id: str, lab_provider_id: str, **overrides) -> dict:
    payload = {
        "referral_id": referral_id,
        "lab_provider_id": lab_provider_id,
        "appliance_kind": "CUSTOM_FABRICATED",
        "capture_method": "DIGITAL_SCAN",
        "max_protrusive_mm": TEST_DEFAULTS["max_protrusive_mm"],
        "promised_turnaround_days": TEST_DEFAULTS["promised_turnaround_days"],
    }
    payload.update(overrides)
    return payload


def create_appliance_lot_payload(**overrides) -> dict:
    payload = {"manufacturer": "SomnoCorp", "lot_code": "LOT-A"}
    payload.update(overrides)
    return payload


def create_appliance_payload(lab_order_id: str, lot_id: str, **overrides) -> dict:
    payload = {
        "lab_order_id": lab_order_id,
        "lot_id": lot_id,
        "serial_number": "SN-0001",
        "has_microrecorder": True,
    }
    payload.update(overrides)
    return payload


def create_titration_visit_payload(
    appliance_id: str,
    performed_by_dentist_id: str,
    expected_appliance_version: int,
    **overrides,
) -> dict:
    payload = {
        "appliance_id": appliance_id,
        "performed_by_dentist_id": performed_by_dentist_id,
        "scheduled_for": TIMELINE["visit_1"],
        "requested_increment_mm": 1.00,
        "expected_appliance_version": expected_appliance_version,
    }
    payload.update(overrides)
    return payload


def create_adherence_download_payload(appliance_id: str, **overrides) -> dict:
    payload = {
        "appliance_id": appliance_id,
        "source": "OBJECTIVE_MICRORECORDER",
        "window_start": "2026-07-08",
        "window_end": "2026-08-06",
        "nights_recorded": 30,
        "nights_at_or_above_min_hours": 21,
        "mean_hours_per_worn_night": 6.1,
    }
    payload.update(overrides)
    return payload


def create_efficacy_report_payload(
    referral_id: str, appliance_id: str, efficacy_study_id: str,
    expected_referral_version: int, **overrides,
) -> dict:
    payload = {
        "referral_id": referral_id,
        "appliance_id": appliance_id,
        "efficacy_study_id": efficacy_study_id,
        "expected_referral_version": expected_referral_version,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(
    patient_id: str, payer_id: str, appliance_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "payer_id": payer_id,
        "appliance_id": appliance_id,
        "claim_type": "INITIAL_DEVICE",
        "hcpcs_code": "E0486",
        "date_of_service": TIMELINE["delivered_on"],
        "billed_cents": TEST_DEFAULTS["billed_cents_device"],
    }
    payload.update(overrides)
    return payload


def create_repair_order_payload(appliance_id: str, **overrides) -> dict:
    payload = {
        "appliance_id": appliance_id,
        "reason": "WEAR",
        "reported_on": "2026-06-10",
        "labor_minutes": 45,
    }
    payload.update(overrides)
    return payload


def create_audit_hold_payload(patient_id: str, payer_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "payer_id": payer_id,
        "scope_note": "Records audit",
    }
    payload.update(overrides)
    return payload
