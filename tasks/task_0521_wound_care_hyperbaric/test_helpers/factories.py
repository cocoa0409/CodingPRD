"""Payload factories — one per entity, input fields only."""


def create_center_payload(**overrides) -> dict:
    defaults = {"name": "Test Center"}
    defaults.update(overrides)
    return defaults


def create_clinician_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "name": "Dr Wound",
        "role_kind": "WOUND",
    }
    defaults.update(overrides)
    return defaults


def create_chamber_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "label": "CH1",
    }
    defaults.update(overrides)
    return defaults


def create_payer_policy_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "payer_name": "Acme",
        "max_covered_hbo_sessions": 4,
        "per_session_cents": 45000,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(center_id, payer_policy_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "mrn": "MRN-1",
        "full_name": "Test Patient",
        "payer_policy_id": payer_policy_id,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "source_provider": "GP",
        "reason": "chronic ulcer",
    }
    defaults.update(overrides)
    return defaults


def create_wound_assessment_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "stage": "STAGE_2",
        "length_cm": 2,
        "width_cm": 2,
        "tissue_type": "GRANULATION",
    }
    defaults.update(overrides)
    return defaults


def create_photo_document_payload(wound_assessment_id, patient_id, **overrides) -> dict:
    defaults = {
        "wound_assessment_id": wound_assessment_id,
        "patient_id": patient_id,
        "image_uri": "s3://images/photo-1.jpg",
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(patient_id, baseline_assessment_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "baseline_assessment_id": baseline_assessment_id,
        "debridement_supply_budget_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(treatment_plan_id, **overrides) -> dict:
    defaults = {
        "treatment_plan_id": treatment_plan_id,
        "requested_hbo_sessions": 4,
        "clinical_justification": "hypoxic wound",
    }
    defaults.update(overrides)
    return defaults


def create_debridement_procedure_payload(treatment_plan_id, clinician_id, **overrides) -> dict:
    defaults = {
        "treatment_plan_id": treatment_plan_id,
        "clinician_id": clinician_id,
        "window_start": "2026-05-02T09:00:00Z",
        "window_end": "2026-05-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_hbo_session_payload(treatment_plan_id, chamber_id, expected_plan_version, **overrides) -> dict:
    defaults = {
        "treatment_plan_id": treatment_plan_id,
        "chamber_id": chamber_id,
        "window_start": "2026-05-02T09:00:00Z",
        "window_end": "2026-05-02T10:00:00Z",
        "treatment_pressure_ata": 2.4,
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_supply_order_payload(treatment_plan_id, expected_plan_version, **overrides) -> dict:
    defaults = {
        "treatment_plan_id": treatment_plan_id,
        "expected_plan_version": expected_plan_version,
        "supply_kind": "ADVANCED_DRESSING",
        "line_items": [
            {"unit_price_cents": 101, "qty": 1, "coverage_rate": 0.5},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_acute_transfer_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "destination_facility": "General ICU",
        "clinical_reason": "sepsis",
    }
    defaults.update(overrides)
    return defaults


# Reusable line-item bundle: three lines of 101c * 1 * 0.5 -> 51c each -> 153c.
THREE_LINES_153 = [
    {"unit_price_cents": 101, "qty": 1, "coverage_rate": 0.5},
    {"unit_price_cents": 101, "qty": 1, "coverage_rate": 0.5},
    {"unit_price_cents": 101, "qty": 1, "coverage_rate": 0.5},
]
