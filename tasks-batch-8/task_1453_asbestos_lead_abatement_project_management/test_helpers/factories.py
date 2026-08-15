"""Payload factories — one per resource family, input fields only."""

FUTURE_EXPIRY = "2027-01-01T00:00:00Z"


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "P-1",
        "site_address": "1 Elm St",
        "work_type": "RENOVATION",
        "hazard_class": "ASBESTOS",
        "planned_start": "2026-08-11T00:00:00Z",
        "base_abatement_cost_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "surveyor_name": "Insp A",
        "survey_date": "2026-07-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(survey_id, **overrides) -> dict:
    defaults = {
        "survey_id": survey_id,
        "material": "pipe insulation",
        "location_desc": "basement",
        "quantity_sq_ft": 100,
        "friable": True,
    }
    defaults.update(overrides)
    return defaults


def create_sample_result_payload(**overrides) -> dict:
    defaults = {"lab_result": "POSITIVE", "asbestos_pct": 40}
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Worker One",
        "certification_level": "SUPERVISOR",
        "cert_expires_at": FUTURE_EXPIRY,
        "medical_clearance_expires_at": FUTURE_EXPIRY,
        "respirator_fit_expires_at": FUTURE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(project_id, worker_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "worker_id": worker_id,
        "role_on_site": "HANDLER",
        "start_at": "2026-08-11T00:00:00Z",
        "end_at": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_notification_payload(project_id, expected_project_version,
                                **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "notification_type": "INITIAL",
        "declared_acm_sq_ft": 100,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_containment_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "work_area_volume_cuft": 240_000,
        "containment_class": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_air_test_payload(project_id, phase, collected_at,
                            **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "phase": phase,
        "collected_at": collected_at,
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(project_id, facility_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "facility_id": facility_id,
        "bags_count": 2,
        "gross_weight_lbs": 100,
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Fac A",
        "epa_id": "EPA-1",
        "accepted_hazards": ["ASBESTOS"],
        "monthly_capacity_tons": 50,
    }
    defaults.update(overrides)
    return defaults


def create_relocation_unit_payload(**overrides) -> dict:
    defaults = {"unit_label": "U1", "capacity_persons": 4}
    defaults.update(overrides)
    return defaults


def create_relocation_payload(project_id, unit_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "unit_id": unit_id,
        "household_name": "Household H",
        "persons": 3,
        "move_out_at": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
