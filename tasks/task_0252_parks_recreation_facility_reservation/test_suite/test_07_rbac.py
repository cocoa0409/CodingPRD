"""Role-based access control: authentication, authorization, ownership.

Covers corner instances under section rbac.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    set_clock, create_facility, create_patron, apply_permit,
    create_facility_payload, build_user_headers,
    make_patron_headers, TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If the X-User-Role header is missing or names a role the system
    does not recognize, the request is rejected with ERR_UNAUTHENTICATED (HTTP
    401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    headers = build_user_headers("someone", "Nobody")
    res = api.create_facility(create_facility_payload(name="NoAuth"), headers)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_patron_cannot_create_facility(api):
    """PRD §2.1: "When the header names a valid role but that role is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."
    PRD §4 (endpoint table): "POST | /facilities | Create a facility |
    RecCoordinator".

    Design: Corner/rbac/patron_cannot_create_facility_forbidden
    """
    patron = create_patron(residency="RESIDENT")
    res = api.create_facility(
        create_facility_payload(name="Sneak"), make_patron_headers(patron["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_patron_cannot_grant_permit(api):
    """PRD §3.5: "Granting is the heart of the workflow and is performed by a
    RecCoordinator."
    PRD §4 (endpoint table): "POST |
    /facilities/{facility_id}/permits/{permit_id}/grant | Grant a permit |
    RecCoordinator".

    A Patron attempting to grant -> ERR_FORBIDDEN.

    Design: Corner/rbac/patron_cannot_grant_permit_forbidden
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(name="Grant Field", facility_type="FIELD")
    patron = create_patron(residency="NON_RESIDENT")
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z")
    v = facility["version"]
    res = api.grant_permit(
        facility["id"], permit["id"], {"expected_facility_version": v},
        make_patron_headers(patron["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_patron_cannot_cancel_other_patrons_permit(api):
    """PRD §2.1: "Ownership checks compare the targeted resource's owning-patron
    foreign key to X-User-ID: for a permit, the patron_id ... When a Patron attempts
    to cancel a permit ... on a resource whose owning patron is not X-User-ID — the
    request is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    P_owner has an APPLIED permit; P_other tries to cancel it -> not resource owner.

    Design: Corner/rbac/patron_cannot_cancel_other_patrons_permit_not_owner
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(name="Own Field", facility_type="FIELD")
    owner = create_patron(residency="NON_RESIDENT")
    other = create_patron(residency="NON_RESIDENT")
    permit = apply_permit(facility["id"], owner["id"],
                          "2026-09-03T10:00:00Z", "2026-09-03T12:00:00Z")
    res = api.cancel_permit(
        facility["id"], permit["id"], {"refund_destination": "ORIGINAL"},
        make_patron_headers(other["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED"
