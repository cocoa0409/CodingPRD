"""Entity creation, retrieval, and input-validation basics.

Queue B (Corner) — section: entities.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_program_payload, create_curriculum_payload, create_dietitian_payload,
    assert_program,
)

COORD = TEST_USERS["coordinator_headers"]


def test_program_create_defaults_accredited_and_version_one(api):
    """PRD §3.1: "Its `accreditation_status` is one of `ACCREDITED`, `PROBATION`,
    or `LAPSED` and defaults to `ACCREDITED` when omitted".
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments
    by 1 on every mutation of that resource."

    Design: Corner/entities/entity_program_create_and_retrieve
    """
    created = validate_success(api.create_program(create_program_payload(), COORD), 201)
    assert_program(created)
    fetched = validate_success(api.get_program(created["id"], COORD), 200)
    assert fetched["accreditation_status"] == "ACCREDITED", \
        f"omitted accreditation_status must default to ACCREDITED, got {fetched['accreditation_status']}"
    assert fetched["version"] == 1, f"version must start at 1, got {fetched['version']}"


def test_get_unknown_patient_returns_not_found(api):
    """PRD §2.7: "every resource named in the path and in the body exists,
    validated left-to-right in path order and then body order, else the
    corresponding `ERR_{RESOURCE}_NOT_FOUND` (404)."

    Design: Corner/entities/entity_patient_get_not_found
    """
    resp = api.get_patient(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_curriculum_missing_required_hours_rejected(api):
    """PRD §2.7: "required fields present, enum members valid, numeric values in
    range, else `ERR_VALIDATION` (400)."

    Design: Corner/entities/entity_curriculum_missing_required_field
    """
    payload = create_curriculum_payload()
    payload.pop("required_hours")
    resp = api.create_curriculum(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_dietitian_invalid_credential_enum_rejected(api):
    """PRD §2.7: "required fields present, enum members valid, numeric values in
    range, else `ERR_VALIDATION` (400)."
    PRD §3.1: "a `credential` (one of `RD`, `RN`, `CDCES`, or `PHARMD`)".

    Design: Corner/entities/entity_dietitian_invalid_enum_credential
    """
    resp = api.create_dietitian(create_dietitian_payload(credential="WIZARD"), COORD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
