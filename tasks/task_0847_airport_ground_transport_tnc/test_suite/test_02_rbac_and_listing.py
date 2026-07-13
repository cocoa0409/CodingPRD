"""Role-based access control and list-endpoint envelope/pagination validation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_operator_payload, create_vehicle_payload, create_staging_lot_payload,
    create_permit_payload, build_user_headers,
    TEST_USERS, make_operator_headers,
    create_operator, register_vehicle,
)

AA = TEST_USERS["airport_authority_headers"]
CC = TEST_USERS["curb_coordinator_headers"]


def test_operator_cannot_create_staging_lot(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation — or an operator attempts to act
    on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/operator_cannot_create_staging_lot_unauthorized
    """
    headers = make_operator_headers("22222222-2222-4222-8222-222222222222")
    resp = api.create_staging_lot(create_staging_lot_payload(name="Illegal"), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_curb_coordinator_cannot_issue_permit(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation — or an operator attempts to act
    on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/curb_coordinator_cannot_issue_permit_unauthorized
    """
    op = create_operator(api, operator_type="TNC", legal_name="CC Co")
    veh = register_vehicle(api, op["id"], plate="CCV1")
    resp = api.create_permit(
        create_permit_payload(veh["id"], veh["version"], avi_tag_id="AVI-CCV1"), CC
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_operator_cannot_register_vehicle_for_other_operator(api):
    """PRD §2.1: "An operator registering a vehicle must supply an `operator_id`
    equal to its own `X-User-ID`; an operator queuing, dispatching, or driving a
    trip must own the vehicle involved; an operator appealing, paying, or settling
    must own the underlying resource's operator."

    Design: Corner/rbac/operator_cannot_register_vehicle_for_other_operator
    """
    op1 = create_operator(api, operator_type="TNC", legal_name="Own1", contact_email="o1@x.com")
    op2 = create_operator(api, operator_type="TNC", legal_name="Own2", contact_email="o2@x.com")
    # Acting as op1 but supplying op2 as the owning operator.
    resp = api.create_vehicle(
        create_vehicle_payload(op2["id"], plate="STEAL"), make_operator_headers(op1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` names a role the
    system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_operator(
        create_operator_payload(legal_name="NoAuth", operator_type="TNC", contact_email="na@x.com"),
        {"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_register_vehicle_unknown_operator_returns_not_found(api):
    """PRD §2.4: "Identifiers appearing in a request path, and every foreign-key
    reference carried in a request body, are resolved left to right; the first
    identifier that does not resolve to an existing resource causes the request to
    be rejected with `ERR_NOT_FOUND` before any later identifier or business rule
    is evaluated."

    Design: Corner/entities/create_vehicle_unknown_operator_returns_not_found
    """
    fake = "11111111-1111-4111-8111-111111111111"
    resp = api.create_vehicle(create_vehicle_payload(fake, plate="X"), make_operator_headers(fake))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_vehicles_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_vehicles_pagination_envelope
    """
    op = create_operator(api, operator_type="TNC", legal_name="List Co")
    veh = register_vehicle(api, op["id"], plate="LP1")
    resp = api.list_vehicles(AA, params={"operator_id": op["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"
    assert data[0]["id"] == veh["id"]


def test_list_vehicles_limit_zero_returns_validation(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`,
    is a malformed request and is rejected with `ERR_VALIDATION`."

    Design: Corner/validations/list_vehicles_limit_zero_returns_invalid_request
    """
    resp = api.list_vehicles(AA, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)
