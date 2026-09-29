"""Patient medical records, role gating and malformed-request handling."""

from test_helpers import (
    HEADERS_WITHOUT_ROLE,
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    ApiErrorId,
    api_client,
    create_patient_payload,
    register_patient,
    setup_facility_with_staff,
    validate_error,
    validate_paginated,
)


def test_reading_a_patient_that_does_not_exist_is_a_not_found():
    """A real record exists, but the requested path identifier does not resolve.

    PRD §2.10: "Identifiers embedded in the URL path are resolved first, left to
    right, and the first one that does not resolve produces `ERR_NOT_FOUND` — a
    request naming a therapy week that does not exist fails on the week before
    any body field is inspected."

    Design: Corner/entities/patient_get_with_unknown_id_returns_not_found
    """
    env = setup_facility_with_staff(staff=("nurse",))
    register_patient(env)

    response = api_client.get_patient(NON_EXISTENT_UUID, OFFICER_HEADERS)

    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_patient_registration_with_an_unrecognised_comorbidity_tier_is_rejected():
    """An out-of-enum comorbidity tier fails the request-shape check.

    PRD §2.5: "required body fields present; enum values recognised; timestamps
    ISO 8601 UTC; dates written as `YYYY-MM-DD`"

    Design: Corner/entities/patient_create_with_unknown_comorbidity_tier_rejected
    """
    env = setup_facility_with_staff(staff=("nurse",))

    response = api_client.create_patient(
        create_patient_payload(env["facility_id"], comorbidity_tier="TIER_9"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api_client.list_patients(
        OFFICER_HEADERS, params={"facility_id": env["facility_id"]}
    ))
    assert meta["total_count"] == 0


def test_second_patient_reusing_a_medical_record_number_is_rejected():
    """The medical record number is unique inside the facility that owns it.

    PRD §3.1: "with the medical record number `mrn` — unique within that
    facility, a repeat being `ERR_MRN_DUPLICATE`"

    Design: Corner/validations/duplicate_mrn_in_same_facility_rejected
    """
    env = setup_facility_with_staff(staff=("nurse",))
    register_patient(env, mrn="MRN-A")

    response = api_client.create_patient(
        create_patient_payload(env["facility_id"], mrn="MRN-A",
                               full_name="Other Person",
                               birth_date="1970-01-01",
                               impairment_group_code="0110",
                               etiologic_diagnosis_code="M17.11",
                               comorbidity_tier="NONE"),
        env["nurse_headers"],
    )

    validate_error(response, ApiErrorId.ERR_MRN_DUPLICATE)
    _, meta = validate_paginated(api_client.list_patients(
        OFFICER_HEADERS,
        params={"facility_id": env["facility_id"], "mrn": "MRN-A"},
    ))
    assert meta["total_count"] == 1


def test_compliance_officer_may_not_open_a_patient_medical_record():
    """Patient registration belongs to the nurse case manager alone.

    PRD §2.1: "If the headers are well formed but the declared role is not
    authorised for the endpoint being called, the rejection is
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/compliance_officer_cannot_register_patient
    """
    env = setup_facility_with_staff(staff=("nurse",))

    response = api_client.create_patient(
        create_patient_payload(env["facility_id"], mrn="MRN-Z",
                               full_name="Zoe Patient",
                               birth_date="1955-05-05",
                               impairment_group_code="0008",
                               etiologic_diagnosis_code="I63.9",
                               comorbidity_tier="TIER_2"),
        OFFICER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    _, meta = validate_paginated(api_client.list_patients(
        OFFICER_HEADERS, params={"facility_id": env["facility_id"]}
    ))
    assert meta["total_count"] == 0


def test_request_without_a_role_header_is_unauthenticated():
    """A read that any role could perform still needs the role header present.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    five recognised role names, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/request_without_role_header_rejected
    """
    env = setup_facility_with_staff(staff=("nurse",))

    response = api_client.get_facility(env["facility_id"], HEADERS_WITHOUT_ROLE)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_admission_opened_without_a_screening_identifier_is_malformed():
    """The missing required field is reported before the unresolvable patient.

    PRD §2.5: "required body fields present; enum values recognised; timestamps
    ISO 8601 UTC; dates written as `YYYY-MM-DD`"

    Design: Corner/validations/admission_create_missing_screening_id_returns_invalid_request
    """
    env = setup_facility_with_staff(staff=("nurse",))

    response = api_client.create_admission({"patient_id": NON_EXISTENT_UUID},
                                           env["nurse_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api_client.list_admissions(
        OFFICER_HEADERS, params={"facility_id": env["facility_id"]}
    ))
    assert meta["total_count"] == 0
