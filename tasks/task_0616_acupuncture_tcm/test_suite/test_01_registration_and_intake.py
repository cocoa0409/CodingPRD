"""Patient registration, TCM intake, and access control.

Covers queue B corner instances for the entities/state_machines/validations/rbac
sections that concern patient creation and the intake lifecycle.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    is_valid_uuid, ApiErrorId, TEST_USERS, make_practitioner_headers, make_patient_headers,
    assert_patient,
    create_patient_payload, create_intake_payload,
    create_practitioner, create_patient, setup_finalized_intake,
    BOGUS_UUID,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
PHARM = TEST_USERS["pharmacist_headers"]


def test_register_patient_minimal_required_fields(api):
    """PRD 3.1: "A newly registered patient begins with intake_status of
    PENDING_INTAKE, membership_status of NONE, and strike_count of 0."

    Design: Corner/entities/create_patient_minimal_required_fields_201
    """
    resp = api.create_patient(
        create_patient_payload(full_name="Jane Doe", date_of_birth="1990-05-05"), ADMIN)
    data = validate_success(resp, 201)
    assert_patient(data)
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert data["intake_status"] == "PENDING_INTAKE"
    assert data["membership_status"] == "NONE"
    assert data["strike_count"] == 0
    assert data["payer_mode"] == "CASH"


def test_get_patient_returns_stored_record(api):
    """PRD 3.1: "A ClinicAdmin registers a patient by supplying the patient's
    full_name and date_of_birth (an ISO date in year-month-day form)."

    Design: Corner/entities/get_patient_returns_stored_record
    """
    created = create_patient(full_name="Read Back", date_of_birth="1991-02-03")
    data = validate_success(api.get_patient(created["id"], ADMIN), 200)
    assert data["full_name"] == "Read Back"
    assert data["date_of_birth"] == "1991-02-03"


def test_list_patients_pagination_envelope(api):
    """PRD 2.3: "Every list response carries limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/list_patients_pagination_envelope
    """
    create_patient(full_name="P1", date_of_birth="1990-01-01")
    create_patient(full_name="P2", date_of_birth="1990-01-02")
    data, meta = validate_paginated(api.list_patients(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_patient_not_found(api):
    """PRD 2.8: "Next, any resource identifiers embedded in the request path are
    checked for existence in left-to-right order, so that on a path naming more than one
    resource the earlier identifier's not-found error is returned before the later one is
    even consulted; depending on the resource this surfaces as ERR_PATIENT_NOT_FOUND,
    ERR_INTAKE_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_PACKAGE_NOT_FOUND, ERR_APPT_NOT_FOUND,
    ERR_DISPENSE_NOT_FOUND, ERR_PRACTITIONER_NOT_FOUND, ERR_ROOM_NOT_FOUND,
    ERR_FORMULA_NOT_FOUND, or ERR_HERB_NOT_FOUND."

    Design: Corner/entities/get_patient_not_found_404
    """
    validate_error(api.get_patient(BOGUS_UUID, ADMIN), ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_register_patient_missing_full_name_rejected(api):
    """PRD 2.8: "Only then is the body checked for well-formedness (ERR_INVALID_REQUEST):
    required fields present, enum values legal, the appointment's scheduled_end strictly
    after its scheduled_start, every numeric field at or above its minimum, and
    coinsurance_rate within the inclusive range from 0 to 1."

    Design: Corner/entities/create_patient_missing_required_returns_invalid_request
    """
    validate_error(api.create_patient({"date_of_birth": "1990-01-01"}, ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_patient_payer_mode_defaults_to_cash(api):
    """PRD 3.1: "The billing posture is captured at registration through payer_mode,
    which is either CASH or INSURANCE and defaults to CASH when omitted."
    PRD 3.1: "the rate defaults to 0.0 and is only meaningful when payer_mode is INSURANCE."

    Design: Corner/entities/patient_payer_mode_default_cash
    """
    data = validate_success(
        api.create_patient(create_patient_payload(full_name="Def Pat"), ADMIN), 201)
    assert data["payer_mode"] == "CASH"
    assert float(data["coinsurance_rate"]) == 0.0


def test_patient_system_fields_server_controlled(api):
    """PRD 2.4: "an integer version that begins at 1 and increases by one on every
    mutation, again including cascades."
    PRD 3.1: "A newly registered patient begins with intake_status of PENDING_INTAKE,
    membership_status of NONE, and strike_count of 0."

    Design: Corner/entities/patient_system_fields_input_ignored
    """
    data = validate_success(
        api.create_patient(create_patient_payload(full_name="Sys Pat"), ADMIN), 201)
    assert data["version"] == 1
    assert data["strike_count"] == 0


def test_intake_invalid_tongue_enum_rejected(api):
    """PRD 2.8: "Only then is the body checked for well-formedness (ERR_INVALID_REQUEST):
    required fields present, enum values legal, the appointment's scheduled_end strictly
    after its scheduled_start, every numeric field at or above its minimum, and
    coinsurance_rate within the inclusive range from 0 to 1."

    Design: Corner/entities/intake_invalid_enum_rejected
    """
    prac = create_practitioner()
    patient = create_patient(full_name="Enum Pat")
    payload = create_intake_payload(patient["id"], tongue_finding="GREEN")
    validate_error(
        api.create_intake(payload, make_practitioner_headers(prac["id"])),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_finalize_already_finalized_intake_rejected(api):
    """PRD 3.2: "Finalization is permitted only when the intake's status is DRAFT;
    an attempt to finalize an intake that is not in DRAFT is rejected with
    ERR_INTAKE_NOT_DRAFT."

    Design: Corner/state_machines/finalize_already_finalized_intake_rejected
    """
    prac = create_practitioner()
    patient = create_patient(full_name="S1 Pat")
    finalized = setup_finalized_intake(patient["id"], prac["id"])
    resp = api.finalize_intake(finalized["id"], make_practitioner_headers(prac["id"]))
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_DRAFT.value)


def test_finalize_flips_patient_intake_status(api):
    """PRD 3.2: "On success the intake's status moves from DRAFT to FINALIZED, and as
    a cross-entity side effect the owning patient's intake_status flips from
    PENDING_INTAKE to INTAKE_COMPLETE, with the patient's version incremented by one
    and the intake's own version incremented by one."

    Design: Corner/state_machines/finalize_already_finalized_intake_rejected
    """
    prac = create_practitioner()
    patient = create_patient(full_name="Flip Pat")
    assert patient["intake_status"] == "PENDING_INTAKE"
    finalized = setup_finalized_intake(patient["id"], prac["id"])
    assert finalized["status"] == "FINALIZED"
    reread = get_success_data(api.get_patient(patient["id"], ADMIN))
    assert reread["intake_status"] == "INTAKE_COMPLETE"
    assert reread["version"] == patient["version"] + 1


# ─── RBAC / auth / ownership (queue B rbac section) ───────────────────────
def test_missing_auth_headers_rejected(api):
    """PRD 2.1: "If either header is missing or malformed, the request is rejected
    with ERR_MISSING_AUTH."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    validate_error(api.list_patients({}), ApiErrorId.ERR_MISSING_AUTH.value)


def test_pharmacist_cannot_register_patient(api):
    """PRD 2.1: "When a request is authenticated but the declared role is not
    permitted to perform the requested operation, the system responds with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/pharmacist_cannot_register_patient
    """
    validate_error(
        api.create_patient(create_patient_payload(full_name="Bad"), PHARM),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_clinic_admin_cannot_finalize_intake(api):
    """PRD 2.1: "When a request is authenticated but the declared role is not
    permitted to perform the requested operation, the system responds with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/clinic_admin_cannot_finalize_intake
    """
    prac = create_practitioner()
    patient = create_patient(full_name="R1 Pat")
    intake = get_success_data(api.create_intake(
        create_intake_payload(patient["id"]), make_practitioner_headers(prac["id"])))
    validate_error(api.finalize_intake(intake["id"], ADMIN),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_patient_reading_other_patient_record_ownership_mismatch(api):
    """PRD 2.1: "When either an entity-backed actor's X-User-ID fails to match the
    owning entity's id on a resource they are required to own, the request is
    rejected with ERR_OWNERSHIP_MISMATCH."

    Design: Corner/rbac/patient_reads_other_patient_ownership_mismatch
    """
    pa = create_patient(full_name="PA")
    pb = create_patient(full_name="PB", date_of_birth="1990-01-02")
    validate_error(api.get_patient(pb["id"], make_patient_headers(pa["id"])),
                   ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)
