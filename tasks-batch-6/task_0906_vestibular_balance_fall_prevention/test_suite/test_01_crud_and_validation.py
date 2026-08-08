"""CRUD, input validation, and not-found corners.

Covers corner-design instances for entity creation, required-field and enum
validation, system-field stamping, per-entity not-found, and the clinician
not-found existence check on assessment create.
"""
from test_helpers import (
    api_client as _c,  # noqa: F401  (kept for parity; tests use `api` fixture)
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_patient,
    create_patient_payload, create_referral_payload, create_clinician_payload,
    register_patient, register_referral, register_clinician,
    reset_clock,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


def test_create_patient_minimal_returns_201_active_v1(api):
    """PRD §3.1: "A newly registered patient enters ACTIVE status; the only other
    patient status is DISCHARGED."
    PRD §2.4: "The version field is an integer that begins at its initial value on
    creation and increments by one on every mutation of the resource."

    Design: Corner/entities/corner_create_patient_minimal
    """
    reset_clock(api)
    resp = api.create_patient(
        create_patient_payload(full_name="Amy Anvil", date_of_birth="1950-01-01",
                               insurance_member_id="MEM-C-01"),
        INTAKE,
    )
    data = validate_success(resp, 201)
    assert_patient(data)
    assert data["full_name"] == "Amy Anvil"
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_get_unknown_patient_returns_404(api):
    """PRD §2.7: "rejects the request at the first reference that does not resolve,
    using the not-found error specific to that entity: ERR_PATIENT_NOT_FOUND ...
    Each of these carries HTTP 404."

    Design: Corner/entities/corner_patient_not_found_on_get
    """
    resp = api.get_patient("00000000-0000-0000-0000-000000000000", INTAKE)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND, 404)


def test_assessment_missing_gait_returns_validation(api):
    """PRD §2.8: "a missing required field or a value of the wrong type yields
    ERR_VALIDATION".

    Design: Corner/entities/corner_assessment_missing_required_gait_returns_validation
    """
    patient = register_patient(api, insurance_member_id="MEM-C-02")
    referral = register_referral(api, patient["id"])
    clinician = register_clinician(api)
    from test_helpers import make_clinician_headers
    payload = {
        "patient_id": patient["id"], "referral_id": referral["id"],
        "clinician_id": clinician["id"],
        "tug_seconds": 12.0, "berg_balance_score": 30,
        "medication_count": 2, "self_report_fall_count": 1,
    }  # gait_speed_m_s omitted
    resp = api.create_assessment(payload, make_clinician_headers(clinician["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_room_invalid_enum_room_type_returns_422(api):
    """PRD §2.8: "an enum-typed field carrying a value outside its declared set
    yields ERR_INVALID_ENUM."

    Design: Corner/entities/corner_room_invalid_enum_room_type
    """
    resp = api.create_room({"name": "Closet", "room_type": "CLOSET"}, SUPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, 422)


def test_patient_system_fields_input_ignored(api):
    """PRD §3.1: "A newly registered patient enters ACTIVE status".
    PRD §2.4: "The version field is an integer that begins at its initial value on
    creation".

    Design: Corner/entities/corner_patient_system_fields_input_ignored
    """
    resp = api.create_patient(
        {"full_name": "Cal Cupula", "date_of_birth": "1952-03-03",
         "insurance_member_id": "MEM-C-03", "status": "DISCHARGED", "version": 99},
        INTAKE,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_assessment_unknown_clinician_id_returns_404(api):
    """PRD §2.7: "rejects the request at the first reference that does not resolve,
    using the not-found error specific to that entity: ... ERR_CLINICIAN_NOT_FOUND".

    Design: Corner/errors/corner_clinician_not_found_on_assessment_create
    """
    from test_helpers import make_clinician_headers
    patient = register_patient(api, insurance_member_id="MEM-C-15")
    referral = register_referral(api, patient["id"])
    clinician = register_clinician(api)  # acting clinician exists
    payload = {
        "patient_id": patient["id"], "referral_id": referral["id"],
        "clinician_id": "00000000-0000-0000-0000-000000000000",
        "gait_speed_m_s": 0.55, "tug_seconds": 14.0, "berg_balance_score": 18,
        "medication_count": 5, "self_report_fall_count": 2,
    }
    resp = api.create_assessment(payload, make_clinician_headers(clinician["id"]))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_NOT_FOUND, 404)
