"""Foundational records: patient creation, required/enum validation, not-found,
append-only adherence logs, RBAC, and read-after-write consistency.

Queue B (Corner) instances only.
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_patient_payload,
    create_evaluation_payload,
    assert_patient,
    assert_adherence_log_shape,
    create_patient,
    setup_active_plan_scenario,
    create_finalized_evaluation,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
DME = TEST_USERS["dme_coordinator_headers"]
AUTHORIZER = TEST_USERS["authorizer_headers"]


def test_register_patient_returns_system_fields(api):
    """PRD §3.1: "A newly registered patient starts in status ACTIVE and remains
    ACTIVE throughout this system's scope."
    PRD §2.4: "version — an integer that begins at 1 on creation and increments by
    one on every mutation."

    Design: Corner/entities/creation_patient_returns_system_fields
    """
    resp = api.create_patient(create_patient_payload(full_name="New Patient"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_patient(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["created_at"]


def test_evaluation_missing_required_isl_stage_rejected(api):
    """PRD §2.5: "A missing/malformed/out-of-range field yields ERR_VALIDATION (422)."

    Design: Corner/entities/required_field_missing_on_evaluation_returns_validation
    """
    patient = create_patient()
    payload = create_evaluation_payload(patient["id"], patient["version"])
    del payload["isl_stage"]
    resp = api.create_evaluation(payload, CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_missing_patient_returns_not_found(api):
    """PRD §2.5: "The first unresolved identifier yields its specific not-found error:
    ERR_PATIENT_NOT_FOUND, ..."

    Design: Corner/entities/not_found_get_missing_patient
    """
    resp = api.get_patient(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND)


def test_evaluation_invalid_isl_stage_enum_rejected(api):
    """PRD §2.5: "an enum field carrying a value outside its declared set yields
    ERR_INVALID_ENUM (422)."

    Design: Corner/entities/invalid_enum_isl_stage_on_evaluation
    """
    patient = create_patient()
    payload = create_evaluation_payload(patient["id"], patient["version"], isl_stage="STAGE_IV")
    resp = api.create_evaluation(payload, CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_adherence_log_is_append_only_no_version(api):
    """PRD §2.4: "AdherenceLog is the sole exception: it is an append-only, immutable
    record and therefore carries only id and created_at. It has no updated_at and no
    version, and it is never modified after creation."

    Design: Corner/entities/adherence_log_is_immutable_no_version
    """
    scenario = setup_active_plan_scenario()
    resp = api.create_adherence_log(
        {"plan_id": scenario["plan"]["id"], "log_date": "2026-06-01",
         "minutes_completed": 60, "wore_garment": True},
        CLINICIAN,
    )
    data = validate_success(resp, expected_status=201)
    assert_adherence_log_shape(data)


def test_dme_coordinator_cannot_create_evaluation(api):
    """PRD §3.2: "A Clinician opens the clinical record by creating an evaluation for a
    patient."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/rbac_dme_coordinator_cannot_create_evaluation
    """
    patient = create_patient()
    payload = create_evaluation_payload(patient["id"], patient["version"])
    resp = api.create_evaluation(payload, DME)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role string outside the
    recognized set, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/rbac_missing_auth_headers_unauthenticated
    """
    resp = api.create_patient(create_patient_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_authorization_immediately_readable_after_create(api):
    """PRD §3.3: "On creation the authorization is DRAFT, visits_reserved and
    visits_used are 0, and visits_remaining equals visit_cap."

    Design: Corner/consistency_model/immediate_read_after_write_authorization
    """
    patient = create_patient()
    created = get_success_data(api.create_authorization(
        {"patient_id": patient["id"], "body_region": "LEFT_ARM", "payer_name": "Acme",
         "auth_number": "AUTH-CONS-1", "visit_cap": 7,
         "effective_start_date": "2026-05-01", "effective_end_date": "2026-12-31"},
        AUTHORIZER,
    ))
    fetched = validate_success(api.get_authorization(created["id"], AUTHORIZER))
    assert fetched["visit_cap"] == 7
    assert fetched["visits_remaining"] == 7
    assert fetched["status"] == "DRAFT"
