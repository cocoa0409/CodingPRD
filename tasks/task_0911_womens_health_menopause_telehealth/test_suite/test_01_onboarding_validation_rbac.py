"""Onboarding validation, not-found, RBAC, and list-envelope corners.

Each test translates exactly one corner-design instance (queue B).
"""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    validate_error, validate_paginated,
    build_user_headers, TEST_USERS,
    create_patient_payload, create_insurance_policy_payload,
    register_patient, attach_policy,
    billing_admin_headers, care_coordinator_headers,
)


def test_patient_create_missing_full_name_returns_validation(api):
    """PRD §2.10: "Body validation — request-body types, enum members, and
    required fields must be well-formed, else ERR_VALIDATION (422). Applies to
    every write endpoint."
    PRD §3.1: "A care coordinator registers a Patient by supplying her
    full_name, email (which is unique across patients), date_of_birth as an ISO
    date, state_code as the two-letter U.S. state of residence (a licensure
    gate), a billing_mode of either CASH or INSURANCE, and a menopause_stage of
    PERIMENOPAUSE, MENOPAUSE, POSTMENOPAUSE, or UNKNOWN."

    Design: Corner/entities/patient_create_missing_required_full_name_returns_validation
    """
    payload = create_patient_payload()
    payload.pop("full_name")
    resp = api.create_patient(payload, care_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_patient_get_unknown_id_returns_not_found(api):
    """PRD §2.9: "The server validates path identifiers left to right and
    rejects the request at the first identifier that does not resolve,
    returning the not-found error specific to that resource type:
    ERR_PATIENT_NOT_FOUND, ..."

    Design: Corner/entities/patient_get_unknown_id_returns_not_found
    """
    resp = api.get_patient(NON_EXISTENT_UUID, care_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND)


def test_second_insurance_policy_returns_already_exists(api):
    """PRD §3.1: "Because a patient may hold only one policy, a second attach
    attempt is rejected with ERR_POLICY_ALREADY_EXISTS (409)."

    Design: Corner/validations/second_insurance_policy_returns_already_exists
    """
    patient = register_patient(api, billing_mode="INSURANCE")
    attach_policy(api, patient["id"], deductible_cents=25000,
                  coinsurance_rate=0.20, out_of_pocket_max_cents=500000)
    resp = api.create_insurance_policy(
        patient["id"],
        create_insurance_policy_payload(payer_name="OtherPayer", deductible_cents=10000,
                                        coinsurance_rate=0.10, out_of_pocket_max_cents=300000),
        billing_admin_headers())
    validate_error(resp, ApiErrorId.ERR_POLICY_ALREADY_EXISTS)


def test_patient_cannot_write_prescription_returns_role_not_permitted(api):
    """PRD §2.1: "When the headers are present and valid but the role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_ROLE_NOT_PERMITTED (HTTP 403)."
    PRD §4 lists POST /prescriptions as authorized for Provider only.

    Design: Corner/rbac/patient_cannot_write_prescription_returns_role_not_permitted
    """
    resp = api.create_prescription({}, TEST_USERS["patient_headers"])
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


def test_request_missing_auth_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role, is rejected with ERR_MISSING_AUTH_CONTEXT (HTTP 401)."

    Design: Corner/rbac/request_missing_auth_returns_unauthenticated
    """
    resp = api.get_patient(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)


def test_list_visits_returns_array_envelope_with_pagination(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the envelope's meta object."
    PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_visits_returns_array_envelope_with_pagination
    """
    resp = api.list_visits(TEST_USERS["provider_headers"])
    data, meta = validate_paginated(resp)
    assert isinstance(data, list), "GET /visits data must be a list"
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination field {field} must be present in meta"
