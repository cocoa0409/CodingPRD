"""Authentication, authorization precedence, and ownership-scoped read access."""
from test_helpers import (
    validate_error, get_success_data, build_user_headers,
    TEST_USERS, ApiErrorId,
    create_owner_payload, make_guest_headers, make_vendor_headers, make_owner_headers,
    fixtures,
)

PM = TEST_USERS["property_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
BOGUS_STATEMENT = "00000000-0000-0000-0000-000000000001"
BOGUS_BOOKING = "00000000-0000-0000-0000-000000000002"


def test_mutation_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "When these headers are missing, or when `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/mutation_missing_auth_headers_returns_unauthenticated
    """
    nobody = build_user_headers("nobody-1", "Nobody")  # unrecognized role
    resp = api.create_owner(create_owner_payload(), nobody)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_guest_cannot_finalize_statement_unauthorized(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation — or an ownership-scoped role acts on a resource it does not own — the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." Authorization (priority 2)
    precedes existence (priority 3), so a bogus id still yields ERR_UNAUTHORIZED.

    Design: Corner/validations/guest_cannot_finalize_statement_unauthorized
    """
    guest = fixtures.create_guest(api)
    resp = api.finalize_statement(BOGUS_STATEMENT, make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_vendor_cannot_screen_booking_unauthorized(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation ... the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.6: authorization (priority 2) precedes existence (priority 3).

    Design: Corner/validations/vendor_cannot_screen_booking_unauthorized
    """
    vendor = fixtures.create_vendor(api, "CLEANER")
    resp = api.screen_booking(BOGUS_BOOKING, {"decision": "APPROVED"}, make_vendor_headers(vendor["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_owner_cannot_read_other_owners_statement(api):
    """PRD §2.1: "Ownership checks on any resource that references an `Owner` compare the
    resource's owning-owner foreign key to `X-User-ID` — an `Owner` may read only their own
    properties, statements, and work orders".

    Design: Corner/rbac/owner_cannot_read_other_owners_statement
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    owner_x = fixtures.create_owner(api)
    owner_y = fixtures.create_owner(api)
    statement = get_success_data(
        api.create_owner_statement({"owner_id": owner_x["id"], "period_year": 2026, "period_month": 6}, PM)
    )
    resp = api.get_owner_statement(statement["id"], make_owner_headers(owner_y["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
