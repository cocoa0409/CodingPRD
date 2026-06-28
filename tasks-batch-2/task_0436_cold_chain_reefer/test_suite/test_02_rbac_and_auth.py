"""Authentication and role-based access control.

Translates corner-design instances from the rbac section.
"""
from test_helpers import (
    validate_error,
    build_user_headers,
    ApiErrorId,
    make_shipper_headers,
    fixtures as fx,
    factories as F,
)


def test_shipper_cannot_accept_shipment_returns_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST   | `/shipments/{id}/accept` | Carrier accepts the tender onto a named unit (OCC) | Carrier |" — accept is authorized for Carrier only, so a Shipper caller is unpermitted.

    Design: Corner/rbac/shipper_cannot_accept_shipment_returns_forbidden
    """
    ctx = fx.setup_tendered_with_compartments(num_compartments=1, carrier_op="carrier-c24",
                                              shipper_op="shipper-c24")
    sid = ctx["shipment"]["id"]
    sv = fx.current_version(sid, ctx["carrier_headers"])
    resp = api.accept_shipment(
        sid, F.accept_payload(ctx["unit"]["id"], sv), make_shipper_headers("shipper-c24")
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "When either header is absent, or when `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_carriers(build_user_headers("nobody", "Intruder"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_non_owner_shipper_cannot_cancel_returns_forbidden(api):
    """PRD §3.3: "Cancellation requires that the caller's `X-User-ID` match the shipment's `shipper_user_id`."
    PRD §2.1: "ownership of shipper-only actions (cancelling a shipment, withdrawing a claim) is enforced by comparing the caller's `X-User-ID` against that stored field rather than against any record's `id`."

    Design: Corner/rbac/non_owner_shipper_cannot_cancel_returns_forbidden
    """
    ctx = fx.setup_accepted(num_compartments=1, carrier_op="carrier-c25", shipper_op="shipper-c25a")
    resp = api.cancel_shipment(ctx["shipment"]["id"], make_shipper_headers("shipper-c25b"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
