"""Payload factories — one per entity, input fields only."""
import itertools

_npi_counter = itertools.count(9000000001)
_dea_counter = itertools.count(1)
_email_counter = itertools.count(1)


def unique_npi() -> str:
    return str(next(_npi_counter))


def unique_dea() -> str:
    return "DEA{:07d}".format(next(_dea_counter))


def unique_email() -> str:
    return "patient{}@example.com".format(next(_email_counter))


def create_clinician_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dr Test Clinician",
        "npi": unique_npi(),
        "dea_number": unique_dea(),
    }
    payload.update(overrides)
    return payload


def create_pharmacist_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Pharmacist",
        "license_number": "PH-TEST-1",
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01",
        "sex": "MALE",
        "email": unique_email(),
    }
    payload.update(overrides)
    return payload


def create_membership_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "PLUS",
        "monthly_fee_cents": 9000,
        "cycle_days": 30,
        "included_refills_per_cycle": 4,
        "included_lab_draw_credits": 4,
        "refill_discount_pct": 0.25,
        "titration_visit_fee_cents": 4500,
    }
    payload.update(overrides)
    return payload


def create_membership_payload(patient_id, plan_id, **overrides) -> dict:
    payload = {"patient_id": patient_id, "plan_id": plan_id}
    payload.update(overrides)
    return payload


def create_draw_station_payload(**overrides) -> dict:
    payload = {"name": "Test Station", "concurrent_capacity": 5}
    payload.update(overrides)
    return payload


def create_lab_panel_payload(patient_id, clinician_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "panel_type": "BASELINE",
    }
    payload.update(overrides)
    return payload


def result_lab_panel_payload(**overrides) -> dict:
    payload = {
        "total_testosterone_ng_dl": 320,
        "psa_ng_ml": 1.2,
        "hematocrit_pct": 45.0,
        "drawn_at": "2026-04-20T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_lab_draw_appointment_payload(patient_id, draw_station_id, start_at, end_at, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "draw_station_id": draw_station_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_telehealth_visit_payload(patient_id, clinician_id, start_at, end_at, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_treatment_plan_payload(patient_id, clinician_id, baseline_panel_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "baseline_panel_id": baseline_panel_id,
        "protocol_type": "TRT_INJECTION",
        "starting_dose_mg": 100,
    }
    payload.update(overrides)
    return payload


def create_prescription_payload(plan_id, patient_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "patient_id": patient_id,
        "drug_name": "Testosterone Cypionate",
        "unit_price_cents": 5000,
        "quantity_per_fill": 8,
        "refills_authorized": 3,
        "is_controlled": True,
    }
    payload.update(overrides)
    return payload


def create_refill_order_payload(prescription_id, membership_id, patient_id, expected_prescription_version, **overrides) -> dict:
    payload = {
        "prescription_id": prescription_id,
        "membership_id": membership_id,
        "patient_id": patient_id,
        "requested_quantity_units": 8,
        "expected_prescription_version": expected_prescription_version,
    }
    payload.update(overrides)
    return payload


def create_adverse_event_payload(patient_id, plan_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "plan_id": plan_id,
        "description": "reported adverse event",
    }
    payload.update(overrides)
    return payload
