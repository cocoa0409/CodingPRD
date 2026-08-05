"""Payload factories — one per entity, carrying only input fields."""

from .constants import TEST_DEFAULTS

_DEFAULT_WEIGHTS = {"FOOD": 40, "HOUSING": 40, "TRANSPORT": 20}


def create_worker_payload(**overrides) -> dict:
    payload = {"full_name": "Ana Reyes", "employee_code": "W-001"}
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "mrn": "MRN-001",
        "full_name": "Rosa Diaz",
        "household_size": TEST_DEFAULTS["HOUSEHOLD_SIZE"],
        "monthly_income_cents": TEST_DEFAULTS["MONTHLY_INCOME_CENTS"],
        "residence_zip": TEST_DEFAULTS["ZIP"],
    }
    payload.update(overrides)
    return payload


def create_instrument_payload(**overrides) -> dict:
    payload = {
        "name": "PRAPARE-Local",
        "version_label": "v2.1",
        "domain_weights": dict(_DEFAULT_WEIGHTS),
        "effective_from": "2026-05-01T00:00:00Z",
        "rescreen_cadence_days": 90,
    }
    payload.update(overrides)
    return payload


def create_screening_payload(patient_id, instrument_id, expected_patient_version,
                             **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "instrument_id": instrument_id,
        "domain_scores": {"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def create_resource_org_payload(**overrides) -> dict:
    payload = {
        "name": "Northside Pantry",
        "org_type": "FOOD",
        "service_zips": [TEST_DEFAULTS["ZIP"]],
        "contact_email": "ops@northside.example",
    }
    payload.update(overrides)
    return payload


def create_offering_payload(resource_org_id, **overrides) -> dict:
    payload = {
        "resource_org_id": resource_org_id,
        "unit_type": "FOOD_BOX",
        "capacity_total": TEST_DEFAULTS["OFFERING_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_criterion_payload(criterion_type, **overrides) -> dict:
    payload = {"criterion_type": criterion_type}
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id, offering_id, opened_by_chw_id,
                            expected_offering_version, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "offering_id": offering_id,
        "opened_by_chw_id": opened_by_chw_id,
        "urgency": "ROUTINE",
        "units_requested": 1,
        "expected_offering_version": expected_offering_version,
    }
    payload.update(overrides)
    return payload


def create_reroute_payload(offering_id, expected_offering_version, **overrides) -> dict:
    payload = {
        "offering_id": offering_id,
        "urgency": "ROUTINE",
        "units_requested": 1,
        "expected_offering_version": expected_offering_version,
    }
    payload.update(overrides)
    return payload


def create_home_visit_payload(patient_id, assigned_chw_id, scheduled_start,
                              scheduled_end, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "assigned_chw_id": assigned_chw_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_goal_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "domain": "FOOD",
        "direction": "INCREASE_GOOD",
        "baseline_value": 2,
        "target_value": 10,
    }
    payload.update(overrides)
    return payload


def create_encounter_payload(patient_id, chw_id, encounter_date, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "chw_id": chw_id,
        "encounter_date": encounter_date,
        "direct_minutes": 50,
        "indirect_minutes": 5,
        "travel_minutes": 0,
        "documentation_minutes": 5,
    }
    payload.update(overrides)
    return payload


def create_payer_claim_payload(patient_id, service_month, basis, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "service_month": service_month,
        "basis": basis,
    }
    payload.update(overrides)
    return payload


def create_grant_award_payload(**overrides) -> dict:
    payload = {
        "funder_name": "City Health Fund",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "budget_cap_cents": TEST_DEFAULTS["GRANT_BUDGET_CAP_CENTS"],
        "indirect_rate_pct": 10,
    }
    payload.update(overrides)
    return payload


def create_charge_line_payload(grant_award_id, encounter_id,
                               expected_grant_award_version, **overrides) -> dict:
    payload = {
        "grant_award_id": grant_award_id,
        "encounter_id": encounter_id,
        "expected_grant_award_version": expected_grant_award_version,
    }
    payload.update(overrides)
    return payload


def create_escalation_payload(patient_id, **overrides) -> dict:
    payload = {"patient_id": patient_id}
    payload.update(overrides)
    return payload
