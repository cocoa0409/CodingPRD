"""Payload factories — one per entity, input fields only."""


def create_procedure_payload(**overrides) -> dict:
    defaults = {
        "code": "RHINO01",
        "name": "Rhinoplasty",
        "surgical_fee_cents": 500000,
        "facility_fee_cents": 200000,
        "anesthesia_fee_cents": 150000,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1990-01-01",
        "age_years": 34,
        "bmi": 24,
    }
    defaults.update(overrides)
    return defaults


def create_consultation_payload(patient_id, surgeon_user_id="surgeon-1",
                                chief_complaint="nose", **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "surgeon_user_id": surgeon_user_id,
        "chief_complaint": chief_complaint,
    }
    defaults.update(overrides)
    return defaults


def create_quote_package_payload(consultation_id, **overrides) -> dict:
    defaults = {"consultation_id": consultation_id}
    defaults.update(overrides)
    return defaults


def create_line_item_payload(procedure_id, **overrides) -> dict:
    defaults = {"procedure_id": procedure_id}
    defaults.update(overrides)
    return defaults


def create_deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_consent_payload(before_photo_ref="s3://b/1", photo_consent_signed=True,
                           surgical_consent_signed=True, **overrides) -> dict:
    defaults = {
        "before_photo_ref": before_photo_ref,
        "photo_consent_signed": photo_consent_signed,
        "surgical_consent_signed": surgical_consent_signed,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(tier_provided="STANDARD", **overrides) -> dict:
    defaults = {"tier_provided": tier_provided}
    defaults.update(overrides)
    return defaults


def create_surgery_booking_payload(quote_package_id, expected_quote_package_version,
                                   surgeon_user_id="surgeon-1", or_room="OR1",
                                   scheduled_start="2026-08-01T00:00:00Z",
                                   scheduled_end="2026-08-01T03:00:00Z",
                                   **overrides) -> dict:
    defaults = {
        "quote_package_id": quote_package_id,
        "surgeon_user_id": surgeon_user_id,
        "or_room": or_room,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_quote_package_version": expected_quote_package_version,
    }
    defaults.update(overrides)
    return defaults


def create_financing_payload(quote_package_id, lender="CARECREDIT",
                             requested_amount_cents=500000, **overrides) -> dict:
    defaults = {
        "quote_package_id": quote_package_id,
        "lender": lender,
        "requested_amount_cents": requested_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_complication_case_payload(surgery_booking_id, line_item_id,
                                     attribution="SURGICAL_ORIGIN", **overrides) -> dict:
    defaults = {
        "surgery_booking_id": surgery_booking_id,
        "line_item_id": line_item_id,
        "attribution": attribution,
    }
    defaults.update(overrides)
    return defaults
