"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BASE_PRICE_CENTS": 500000,
    "DEPOSIT_CENTS": 50000,
    "ENHANCEMENT_WINDOW_DAYS": 365,
    "OUTCOME_GUARANTEE_VA": 1.0,
    "CORNEAL_THICKNESS_UM": 550,
    "TOPOGRAPHY_K_MAX": 44.0,
    "REFRACTIVE_ERROR_DIOPTERS": 3.0,
    "DATE_OF_BIRTH": "2000-01-01",
    "TURNAROUND_BUFFER_MINUTES": 15,
    "DAILY_CASE_CAP": 5,
    "MAX_DAILY_CASES": 5,
}


def create_package_payload(**overrides) -> dict:
    payload = {
        "tier": "STANDARD",
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
        "enhancement_window_days": DEFAULTS["ENHANCEMENT_WINDOW_DAYS"],
        "outcome_guarantee_uncorrected_va": DEFAULTS["OUTCOME_GUARANTEE_VA"],
        "refund_mode": "PRO_RATA",
    }
    payload.update(overrides)
    return payload


def create_suite_payload(**overrides) -> dict:
    payload = {
        "name": "Suite 1",
        "turnaround_buffer_minutes": DEFAULTS["TURNAROUND_BUFFER_MINUTES"],
        "daily_case_cap": DEFAULTS["DAILY_CASE_CAP"],
    }
    payload.update(overrides)
    return payload


def create_surgeon_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dr A",
        "max_daily_cases": DEFAULTS["MAX_DAILY_CASES"],
    }
    payload.update(overrides)
    return payload


def create_optometrist_payload(**overrides) -> dict:
    payload = {"full_name": "OD A"}
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": "P1",
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    payload.update(overrides)
    return payload


def create_screening_payload(patient_id, performed_by_optometrist_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "performed_by_optometrist_id": performed_by_optometrist_id,
        "corneal_thickness_um": DEFAULTS["CORNEAL_THICKNESS_UM"],
        "topography_k_max": DEFAULTS["TOPOGRAPHY_K_MAX"],
        "refractive_error_diopters": DEFAULTS["REFRACTIVE_ERROR_DIOPTERS"],
    }
    payload.update(overrides)
    return payload


def create_case_payload(patient_id, screening_id, package_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "screening_id": screening_id,
        "package_id": package_id,
    }
    payload.update(overrides)
    return payload


def create_financing_payload(down_payment_cents, term_months=1, apr_bps=0, **overrides) -> dict:
    payload = {
        "down_payment_cents": down_payment_cents,
        "term_months": term_months,
        "apr_bps": apr_bps,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(suite_id, surgeon_id, slot_start, slot_end,
                           expected_case_version, **overrides) -> dict:
    payload = {
        "suite_id": suite_id,
        "surgeon_id": surgeon_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def create_consent_payload(signed_by_patient_id, drops_regimen_started=True, **overrides) -> dict:
    payload = {
        "drops_regimen_started": drops_regimen_started,
        "signed_by_patient_id": signed_by_patient_id,
    }
    payload.update(overrides)
    return payload


def create_enhancement_payload(origin_case_id, patient_id, reason="regression", **overrides) -> dict:
    payload = {
        "origin_case_id": origin_case_id,
        "patient_id": patient_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def create_refund_claim_payload(case_id, **overrides) -> dict:
    payload = {"case_id": case_id}
    payload.update(overrides)
    return payload
