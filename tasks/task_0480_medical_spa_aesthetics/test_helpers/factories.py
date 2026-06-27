"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the input fields the PRD declares for that
creation endpoint. Optional fields are omitted unless supplied via overrides;
**overrides lets a test control any single field while defaulting the rest.
"""

DEFAULT_EXP = "2026-12-01T00:00:00Z"
DEFAULT_DOB = "1990-01-01T00:00:00Z"


def create_provider_payload(full_name="Test Provider", license_number="L-TEST",
                            role_kind="INJECTOR", **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "license_number": license_number,
        "role_kind": role_kind,
    }
    payload.update(overrides)
    return payload


def create_membership_package_payload(tier="PLUS", member_discount_pct=0.15,
                                      loyalty_program="ALLE",
                                      monthly_fee_cents=9900, **overrides) -> dict:
    payload = {
        "tier": tier,
        "member_discount_pct": member_discount_pct,
        "loyalty_program": loyalty_program,
        "monthly_fee_cents": monthly_fee_cents,
    }
    payload.update(overrides)
    return payload


def create_injectable_lot_payload(product="BOTOX", lot_number="LOT-1",
                                  expiration_date=DEFAULT_EXP,
                                  total_units=100, **overrides) -> dict:
    payload = {
        "product": product,
        "lot_number": lot_number,
        "expiration_date": expiration_date,
        "total_units": total_units,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(full_name="Test Patient", date_of_birth=DEFAULT_DOB,
                           membership_id=None, **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
    }
    if membership_id is not None:
        payload["membership_id"] = membership_id
    payload.update(overrides)
    return payload


def create_loyalty_account_payload(patient_id, program="ALLE", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "program": program,
    }
    payload.update(overrides)
    return payload


def create_consultation_payload(patient_id, exam_provider_id,
                                chief_complaint="glabellar lines", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "exam_provider_id": exam_provider_id,
        "chief_complaint": chief_complaint,
    }
    payload.update(overrides)
    return payload


def create_standing_order_payload(consultation_id, director_provider_id,
                                  product="BOTOX", max_units_authorized=30,
                                  valid_until_utc=DEFAULT_EXP, **overrides) -> dict:
    payload = {
        "consultation_id": consultation_id,
        "director_provider_id": director_provider_id,
        "product": product,
        "max_units_authorized": max_units_authorized,
        "valid_until_utc": valid_until_utc,
    }
    payload.update(overrides)
    return payload


def create_consent_photo_payload(patient_id, kind="CONSENT", storage_uri="s3://photo",
                                 treatment_session_id=None, signed=None, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "kind": kind,
        "storage_uri": storage_uri,
    }
    if treatment_session_id is not None:
        payload["treatment_session_id"] = treatment_session_id
    if signed is not None:
        payload["signed"] = signed
    payload.update(overrides)
    return payload


def create_treatment_plan_payload(patient_id, consultation_id, product="BOTOX",
                                  planned_sessions=1, planned_units_per_session=20,
                                  list_price_per_unit_cents=1000,
                                  required_deposit_cents=0, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "consultation_id": consultation_id,
        "product": product,
        "planned_sessions": planned_sessions,
        "planned_units_per_session": planned_units_per_session,
        "list_price_per_unit_cents": list_price_per_unit_cents,
        "required_deposit_cents": required_deposit_cents,
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(treatment_plan_id, amount_cents,
                           expected_treatment_plan_version, **overrides) -> dict:
    payload = {
        "treatment_plan_id": treatment_plan_id,
        "amount_cents": amount_cents,
        "expected_treatment_plan_version": expected_treatment_plan_version,
    }
    payload.update(overrides)
    return payload


def create_treatment_session_payload(treatment_plan_id, standing_order_id,
                                     injector_provider_id, injectable_lot_id,
                                     planned_units, expected_treatment_plan_version,
                                     loyalty_points_redeemed=None, **overrides) -> dict:
    payload = {
        "treatment_plan_id": treatment_plan_id,
        "standing_order_id": standing_order_id,
        "injector_provider_id": injector_provider_id,
        "injectable_lot_id": injectable_lot_id,
        "planned_units": planned_units,
        "expected_treatment_plan_version": expected_treatment_plan_version,
    }
    if loyalty_points_redeemed is not None:
        payload["loyalty_points_redeemed"] = loyalty_points_redeemed
    payload.update(overrides)
    return payload


def create_complication_case_payload(treatment_session_id, severity="MODERATE",
                                     **overrides) -> dict:
    payload = {
        "treatment_session_id": treatment_session_id,
        "severity": severity,
    }
    payload.update(overrides)
    return payload
