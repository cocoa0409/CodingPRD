"""Authentication and role-based authorization denials.

Translates Corner/validations (unauthenticated) and Corner/rbac instances.
"""
from test_helpers import (
    validate_error,
    create_zone_payload, approve_payload, review_proof_payload,
    make_resident_headers, make_officer_headers,
)
from test_helpers.fixtures import (
    set_clock, create_zone, register_household, add_vehicle, submit_proof,
    setup_verified_household_with_vehicle,
    create_application, review_application, zone_version, CLERK,
)


# --------------------------------------------------------------------------
# Corner/validations/unauthenticated_missing_headers_returns_401
# --------------------------------------------------------------------------
def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the roles
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_headers_returns_401
    """
    zone = create_zone(api)
    resp = api.get_zone(zone["id"], {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, "ERR_UNAUTHENTICATED", expected_status=401)


# --------------------------------------------------------------------------
# Corner/rbac/resident_cannot_create_zone_returns_403
# --------------------------------------------------------------------------
def test_resident_cannot_create_zone(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/resident_cannot_create_zone_returns_403
    """
    resp = api.create_zone(create_zone_payload(name="RB1"), make_resident_headers("resident-z"))
    validate_error(resp, "ERR_UNAUTHORIZED", expected_status=403)


# --------------------------------------------------------------------------
# Corner/rbac/clerk_cannot_approve_application_returns_403
# --------------------------------------------------------------------------
def test_clerk_cannot_approve_application(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/clerk_cannot_approve_application_returns_403
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    zone = create_zone(api, permit_capacity=2)
    hh, veh = setup_verified_household_with_vehicle(api, zone["id"])
    app = create_application(api, zone["id"], hh["id"], veh["id"])
    review_application(api, app["id"])
    v = zone_version(api, zone["id"])
    resp = api.approve_permit_application(app["id"], approve_payload(v), CLERK)
    validate_error(resp, "ERR_UNAUTHORIZED", expected_status=403)


# --------------------------------------------------------------------------
# Corner/rbac/officer_cannot_review_proof_returns_403
# --------------------------------------------------------------------------
def test_officer_cannot_review_proof(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/officer_cannot_review_proof_returns_403
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    proof = submit_proof(api, hh["id"])
    resp = api.review_proof_submission(proof["id"], review_proof_payload("VERIFIED"),
                                       make_officer_headers("officer-1"))
    validate_error(resp, "ERR_UNAUTHORIZED", expected_status=403)
