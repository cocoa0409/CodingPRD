"""CRUD defaults, input validation, and role-based access control.

Translates SCAFFOLD_CORNER_DESIGN.yaml sections `entities` and `rbac`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    create_defendant_payload, create_assessment_payload,
    TEST_USERS, make_defendant_headers, create_defendant,
)

INTAKE = TEST_USERS["intake_headers"]
SUPERVISING = TEST_USERS["supervising_headers"]


def test_create_defendant_defaults_indigent_false(api):
    """PRD §3.1: "an optional `indigent` flag that defaults to false. A new defendant
    begins with `supervision_status` of `PRETRIAL_PENDING`."

    Design: Corner/entities/defendant_create_defaults_indigent_false
    """
    payload = create_defendant_payload()
    payload.pop("indigent", None)
    data = validate_success(api.create_defendant(payload, INTAKE), 201)
    assert data["indigent"] is False, "omitted indigent must default to false"
    assert data["supervision_status"] == "PRETRIAL_PENDING"

    fetched = validate_success(api.get_defendant(data["id"], INTAKE), 200)
    assert fetched["indigent"] is False
    assert fetched["supervision_status"] == "PRETRIAL_PENDING"


def test_get_defendant_not_found(api):
    """PRD §2.10: "the first identifier that does not resolve to an existing resource
    yields `ERR_NOT_FOUND` (HTTP 404) before any deeper identifier or body rule is considered."

    Design: Corner/entities/defendant_get_not_found
    """
    resp = api.get_defendant(NON_EXISTENT_UUID, INTAKE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_list_defendants_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/defendant_list_pagination_envelope
    """
    create_defendant()
    create_defendant()
    data, meta = validate_paginated(api.list_defendants(INTAKE, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True, "limit 1 over >=2 defendants must set has_more true"
    assert len(data) == 1


def test_create_assessment_missing_instrument_type_returns_validation(api):
    """PRD §2.10: "Body validation — required fields present, types and ranges valid,
    else `ERR_VALIDATION` (400)."

    Design: Corner/entities/assessment_create_missing_required_returns_validation
    """
    defendant = create_defendant()
    payload = create_assessment_payload(defendant["id"])
    payload.pop("instrument_type")
    resp = api.create_assessment(payload, INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_create_assessment_invalid_instrument_enum(api):
    """PRD §2.10: "Enum membership — every enum field value is a member of its declared
    set, else `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/assessment_create_invalid_instrument_enum
    """
    defendant = create_defendant()
    payload = create_assessment_payload(defendant["id"], instrument_type="QUICK")
    resp = api.create_assessment(payload, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, 422)


def test_supervising_officer_cannot_adjudicate_violation(api):
    """PRD §2.1: "If the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.7: "All violation transitions are performed by a `JudicialOfficer`."

    Design: Corner/rbac/supervising_officer_cannot_adjudicate_violation
    """
    from test_helpers import create_reported_violation
    defendant = create_defendant()
    violation = create_reported_violation(defendant["id"], reporter_id="u_sup")
    resp = api.transition_violation(violation["id"], "UNDER_REVIEW", SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_defendant_role_cannot_create_assessment(api):
    """PRD §2.1: "If the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "The same intake officer authors a **risk assessment** for a defendant."

    Design: Corner/rbac/defendant_role_cannot_create_assessment
    """
    defendant = create_defendant()
    headers = make_defendant_headers(defendant["id"])
    payload = create_assessment_payload(defendant["id"])
    resp = api.create_assessment(payload, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_unknown_role_rejected_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_unknown_role_rejected
    """
    headers = build_user_headers("someone", "Anonymous")
    resp = api.create_defendant(create_defendant_payload(), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
