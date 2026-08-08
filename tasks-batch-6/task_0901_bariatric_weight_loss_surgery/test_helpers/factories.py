"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MRN": "MRN-0001",
    "PATIENT_NAME": "Test Patient",
    "DOB": "1985-01-01",
    "HEIGHT_CM": 170,
    "BASELINE_WEIGHT_KG": 120,
    "PLAN_NAME": "Test Payer",
    "PAYER_CODE": "TP",
    "ROOM_CODE": "OR-TEST",
    "TURNOVER_BUFFER_MINUTES": 30,
    "SURGEON_NAME": "Dr Test",
    "NPI": "1999999999",
}

_mrn_counter = {"n": 0}
_npi_counter = {"n": 0}
_room_counter = {"n": 0}


def _next_mrn() -> str:
    _mrn_counter["n"] += 1
    return f"MRN-{_mrn_counter['n']:05d}"


def _next_npi() -> str:
    _npi_counter["n"] += 1
    return f"20000{_npi_counter['n']:05d}"


def _next_room_code() -> str:
    _room_counter["n"] += 1
    return f"OR-{_room_counter['n']:04d}"


def create_patient_payload(**overrides) -> dict:
    payload = {
        "mrn": _next_mrn(),
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "sex": "FEMALE",
        "height_cm": DEFAULTS["HEIGHT_CM"],
        "baseline_weight_kg": DEFAULTS["BASELINE_WEIGHT_KG"],
    }
    payload.update(overrides)
    return payload


def create_insurance_plan_payload(**overrides) -> dict:
    payload = {
        "plan_name": DEFAULTS["PLAN_NAME"],
        "payer_code": DEFAULTS["PAYER_CODE"],
        "required_supervised_diet_months": 3,
        "qualifying_comorbidities": ["TYPE_2_DIABETES"],
    }
    payload.update(overrides)
    return payload


def create_operating_room_payload(**overrides) -> dict:
    payload = {
        "room_code": _next_room_code(),
        "turnover_buffer_minutes": DEFAULTS["TURNOVER_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_surgeon_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["SURGEON_NAME"],
        "npi": _next_npi(),
        "credentialed_procedures": ["SLEEVE_GASTRECTOMY"],
    }
    payload.update(overrides)
    return payload


def create_program_payload(patient_id, payment_pathway="SELF_PAY", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "payment_pathway": payment_pathway,
        "comorbidities": [],
    }
    payload.update(overrides)
    return payload


def create_diet_visit_payload(month_index, **overrides) -> dict:
    payload = {
        "month_index": month_index,
        "visit_date": "2026-02-01",
        "weight_kg": 118,
        "attended": True,
    }
    payload.update(overrides)
    return payload


def create_psych_evaluation_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_nutrition_clearance_payload(**overrides) -> dict:
    payload = {
        "decision": "CLEARED",
        "diet_readiness_score": 80,
    }
    payload.update(overrides)
    return payload


def create_milestone_payload(milestone_code, **overrides) -> dict:
    payload = {
        "milestone_code": milestone_code,
        "completed": True,
    }
    payload.update(overrides)
    return payload


def schedule_surgery_case_payload(operating_room_id, surgeon_id, expected_program_version,
                                  procedure_type="SLEEVE_GASTRECTOMY", **overrides) -> dict:
    payload = {
        "operating_room_id": operating_room_id,
        "surgeon_id": surgeon_id,
        "procedure_type": procedure_type,
        "scheduled_start": "2026-06-15T08:00:00Z",
        "scheduled_end": "2026-06-15T09:30:00Z",
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def complete_surgery_case_payload(actual_or_minutes=95, **overrides) -> dict:
    payload = {"actual_or_minutes": actual_or_minutes}
    payload.update(overrides)
    return payload


def cancel_surgery_case_payload(**overrides) -> dict:
    payload = {"cancellation_reason": "test cancel"}
    payload.update(overrides)
    return payload


def create_complication_payload(complication_type="INFECTION", severity="MINOR",
                                requires_readmission=False, onset_date="2026-06-16", **overrides) -> dict:
    payload = {
        "complication_type": complication_type,
        "severity": severity,
        "requires_readmission": requires_readmission,
        "onset_date": onset_date,
    }
    payload.update(overrides)
    return payload


def record_follow_up_visit_payload(recorded_weight_kg=100, **overrides) -> dict:
    payload = {"recorded_weight_kg": recorded_weight_kg}
    payload.update(overrides)
    return payload


def create_financing_plan_payload(expected_program_version, procedure_type="SLEEVE_GASTRECTOMY",
                                  down_payment_cents=400000, term_months=12, apr_bps=1200, **overrides) -> dict:
    payload = {
        "procedure_type": procedure_type,
        "down_payment_cents": down_payment_cents,
        "term_months": term_months,
        "apr_bps": apr_bps,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload
