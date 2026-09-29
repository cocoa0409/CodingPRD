"""Payload builders. Each returns only client-supplied input fields."""

from .constants import TEST_DEFAULTS


def create_enrollment_payload(**overrides) -> dict:
    payload = {
        "program_type": "PRIVATE_FAMILY",
        "primary_parent_name": "Avery Lin",
        "expected_delivery_date": TEST_DEFAULTS["EXPECTED_DELIVERY_DATE"],
        "collection_site_code": "SITE-01",
    }
    payload.update(overrides)
    return payload


def create_consent_payload(**overrides) -> dict:
    payload = {"consent_document_hash": "hash-aaa-v1"}
    payload.update(overrides)
    return payload


def create_consent_amendment_payload(**overrides) -> dict:
    payload = {"amendment_reason_code": "RESEARCH_USE_CHANGE"}
    payload.update(overrides)
    return payload


def create_withdrawal_payload(**overrides) -> dict:
    payload = {"withdrawal_reason_code": "FAMILY_REQUEST"}
    payload.update(overrides)
    return payload


def create_storage_account_payload(enrollment_id: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "billing_contact_email": TEST_DEFAULTS["BILLING_CONTACT_EMAIL"],
        "plan_term_years": 5,
        "prepaid_through_date": TEST_DEFAULTS["PREPAID_THROUGH_DATE"],
    }
    payload.update(overrides)
    return payload


def create_collection_kit_payload(enrollment_id: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "kit_lot_code": "LOT-2026-A",
        "courier_tracking_code": "TRK-0001",
    }
    payload.update(overrides)
    return payload


def create_collection_payload(kit_id: str, **overrides) -> dict:
    payload = {
        "kit_id": kit_id,
        "collected_at": TEST_DEFAULTS["COLLECTED_AT"],
        "collection_volume_ml": TEST_DEFAULTS["COLLECTION_VOLUME_ML"],
        "anticoagulant_volume_ml": TEST_DEFAULTS["ANTICOAGULANT_VOLUME_ML"],
        "delivery_mode": "VAGINAL",
    }
    payload.update(overrides)
    return payload


def create_receive_payload(**overrides) -> dict:
    payload = {"transport_temp_c": TEST_DEFAULTS["TRANSPORT_TEMP_C"]}
    payload.update(overrides)
    return payload


def create_maternal_screening_payload(enrollment_id: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "collected_at": TEST_DEFAULTS["COLLECTED_AT"],
        "hiv_result": "NON_REACTIVE",
        "hbv_result": "NON_REACTIVE",
        "hcv_result": "NON_REACTIVE",
        "htlv_result": "NON_REACTIVE",
        "syphilis_result": "NON_REACTIVE",
    }
    payload.update(overrides)
    return payload


def create_processing_run_payload(unit_id: str, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "method": "HES_SEDIMENTATION",
        "pre_tnc_millions": 1100,
    }
    payload.update(overrides)
    return payload


def create_run_completion_payload(**overrides) -> dict:
    payload = {
        "outcome": "COMPLETED",
        "post_volume_ml": 25.0,
        "post_tnc_millions": 1000,
    }
    payload.update(overrides)
    return payload


def create_quality_test_payload(unit_id: str, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "test_kind": "POST_PROCESSING",
        "tnc_millions": 1000,
        "cd34_thousands": 2400,
        "viability_pct": 88.0,
        "volume_ml": 25.0,
        "sterility_result": "NEGATIVE",
    }
    payload.update(overrides)
    return payload


def create_eligibility_determination_payload(**overrides) -> dict:
    payload = {"decision_note": "routine determination"}
    payload.update(overrides)
    return payload


def create_cryopreserve_payload(tank_id: str, **overrides) -> dict:
    payload = {
        "tank_id": tank_id,
        "slot_code": "A-01",
        "freeze_at": TEST_DEFAULTS["FREEZE_AT"],
    }
    payload.update(overrides)
    return payload


def create_disposal_payload(**overrides) -> dict:
    payload = {"reason": "QUALITY_FAILURE"}
    payload.update(overrides)
    return payload


def create_storage_tank_payload(**overrides) -> dict:
    payload = {
        "tank_code": "TANK-A",
        "tank_class": "STANDARD",
        "capacity_slots": 5,
    }
    payload.update(overrides)
    return payload


def create_temperature_reading_payload(**overrides) -> dict:
    payload = {
        "reading_c": -190.0,
        "reading_at": TEST_DEFAULTS["RECEIPT_CLOCK"],
    }
    payload.update(overrides)
    return payload


def create_excursion_acknowledge_payload(**overrides) -> dict:
    payload = {"acknowledgement_note": "engineer on site"}
    payload.update(overrides)
    return payload


def create_excursion_resolve_payload(**overrides) -> dict:
    payload = {
        "disposition": "NO_IMPACT",
        "peak_temperature_c": -140.0,
    }
    payload.update(overrides)
    return payload


def create_registry_listing_payload(unit_id: str, expected_unit_version: int, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "registry_code": TEST_DEFAULTS["REGISTRY_CODE"],
        "hla_a": TEST_DEFAULTS["HLA_A"],
        "hla_b": TEST_DEFAULTS["HLA_B"],
        "hla_drb1": TEST_DEFAULTS["HLA_DRB1"],
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def create_listing_suspend_payload(**overrides) -> dict:
    payload = {"suspension_note": "registry audit in progress"}
    payload.update(overrides)
    return payload


def create_storage_invoice_payload(account_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "billing_period_start": "2026-09-01",
        "billing_period_end": "2027-08-31",
        "prorated_days": 365,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "payment_reference": "WIRE-2027-0001",
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(unit_id: str, expected_unit_version: int, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "requesting_center_name": "Center One",
        "patient_weight_kg": 35.0,
        "patient_hla_match_count": 6,
        "hold_from": "2026-09-01T00:00:00Z",
        "hold_until": "2026-09-05T00:00:00Z",
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def create_reservation_confirm_payload(**overrides) -> dict:
    payload = {"intended_transplant_date": "2026-09-03"}
    payload.update(overrides)
    return payload


def create_reservation_decline_payload(**overrides) -> dict:
    payload = {"reason_code": "ALTERNATIVE_UNIT_SELECTED"}
    payload.update(overrides)
    return payload


def create_reservation_release_payload(**overrides) -> dict:
    payload = {"release_note": "release authorised"}
    payload.update(overrides)
    return payload


def create_reservation_cancel_payload(**overrides) -> dict:
    payload = {"reason_code": "PATIENT_DECEASED"}
    payload.update(overrides)
    return payload
