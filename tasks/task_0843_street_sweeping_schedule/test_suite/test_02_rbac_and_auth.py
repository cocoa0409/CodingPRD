"""Authentication, authorization, and complaint ownership.

Translates queue B (Corner) rbac instances.
"""
from test_helpers import (
    validate_error,
    create_route_payload,
    TEST_USERS, make_resident_headers,
    create_route, create_block, create_resident,
    file_complaint, resolve_complaint,
)

OFFICER = TEST_USERS["enforcement_officer_headers"]


def test_enforcement_officer_cannot_create_route(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/enforcement_officer_cannot_create_route
    """
    res = api.create_route(create_route_payload(), OFFICER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_role_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    res = api.create_route(create_route_payload(), {})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_resident_cannot_reopen_others_complaint(api):
    """PRD §2.1: "A resident acting on a complaint that is not their own is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.8: "The owning resident may reopen a resolved complaint, advancing it `RESOLVED → REOPENED` (permitted only from `RESOLVED`, and only when the caller's `X-User-ID` equals the complaint's `resident_id`)"

    Design: Corner/rbac/resident_cannot_reopen_others_complaint
    """
    route = create_route()
    block = create_block(route["id"])
    res_a = create_resident(block["id"], email="a@x.com", full_name="A")
    res_b = create_resident(block["id"], email="b@x.com", full_name="B")
    complaint = file_complaint(res_a["id"], block["id"], category="OTHER")
    resolve_complaint(complaint["id"], resolution_note="done")

    res = api.reopen_complaint(complaint["id"], {}, make_resident_headers(res_b["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
