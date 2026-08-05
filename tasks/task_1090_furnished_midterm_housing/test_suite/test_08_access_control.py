"""Role-based access control: peer-role separation and authentication.

Queue B (Corner): rbac.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    register_host, register_tenant, register_tenant_with_pending_verification,
    create_unit, request_booking,
    ANONYMOUS_HEADERS, make_host_headers, make_tenant_headers,
)


def test_tenant_cannot_confirm_booking(api):
    """PRD §3.4: "A host accepts a requested booking by transitioning it from
    `REQUESTED` to `CONFIRMED`."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership-bound role acts on a resource
    it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/tenant_cannot_confirm_booking
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    resp = api.transition_booking(booking["id"], {"to_status": "CONFIRMED"}, make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_host_cannot_approve_verification(api):
    """PRD §3.1: "A `ComplianceReviewer` adjudicates it, moving a `PENDING`
    verification either to `APPROVED` or to `REJECTED` and optionally attaching a
    `reviewer_note`."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership-bound role acts on a resource
    it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/host_cannot_approve_verification
    """
    host = register_host(api, verify_payout=False)
    tenant, ver = register_tenant_with_pending_verification(api)
    resp = api.transition_verification(ver["id"], {"to_status": "APPROVED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_read_as_anonymous_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/read_as_anonymous_returns_unauthenticated
    """
    host = register_host(api, verify_payout=False)
    resp = api.get_host(host["id"], ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
