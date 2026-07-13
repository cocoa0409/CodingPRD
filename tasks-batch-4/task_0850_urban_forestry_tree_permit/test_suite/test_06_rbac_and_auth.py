"""Authentication, role authorization, and ownership."""
from test_helpers import (
    validate_error,
    create_zone_payload, create_tree_payload,
    setup_tree, setup_zone_species, new_permit,
    make_applicant_headers, unauthenticated_headers,
    TEST_USERS, APPLICANT_1, APPLICANT_2,
)

STAFF = TEST_USERS["forestry_staff_headers"]


def test_zone_create_by_staff_unauthorized(api):
    """PRD §2.1: "If the headers are valid but the named role is not permitted to invoke
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/zone_create_as_staff_unauthorized
    """
    res = api.create_zone(create_zone_payload(name="Z1"), STAFF)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_submit_permit_by_non_owner_forbidden(api):
    """PRD §3.4: "Submit requires that the acting `Applicant`'s `X-User-ID` equal the
    permit's `requested_by_user_id` (otherwise `ERR_NOT_OWNER`), and it enforces the
    protected-tree rule".

    Design: Corner/rbac/submit_permit_by_non_owner_forbidden
    """
    zone, species, tree = setup_tree(dbh=20.0)
    permit = new_permit(tree["id"], permit_type="REMOVAL", reason="decay", user_id=APPLICANT_1)
    res = api.submit_permit(permit["id"], make_applicant_headers(APPLICANT_2))
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


def test_tree_create_with_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a known
    role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/tree_create_missing_auth_unauthenticated
    """
    zone, species = setup_zone_species()
    res = api.create_tree(
        create_tree_payload(zone["id"], species["id"], dbh_inches=12.0),
        unauthenticated_headers())
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
