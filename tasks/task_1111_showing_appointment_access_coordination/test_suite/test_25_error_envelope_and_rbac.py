"""Error-envelope contract, per-resource 404s, and RBAC denials."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_confirmed_request,
    create_showing_request,
    create_seller_payload,
    issue_credential,
    make_admin_headers,
    make_buyer_agent_headers,
    make_seller_headers,
    register_agent,
    register_and_verify_agent,
    setup_occupied_manual_world,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def test_showing_request_not_found_returns_404(api):
    """PRD §2.6: "The server confirms each path identifier in sequence and
    rejects the request immediately with the 404 error corresponding to the
    first identifier that does not resolve: ... `ERR_SHOWING_REQUEST_NOT_FOUND`
    ..."

    Design: Corner/errors/showing_request_not_found_returns_404
    """
    seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="ENF S", contact_email="enf@x.com"),
        make_admin_headers()), expected_status=201)
    resp = api_client.get_showing_request(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_seller_headers(seller["id"]))
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_SHOWING_REQUEST_NOT_FOUND)


def test_credential_redeem_not_found_returns_404(api):
    """PRD §2.6: "The server confirms each path identifier in sequence and
    rejects the request immediately with the 404 error corresponding to the
    first identifier that does not resolve: ... `ERR_ACCESS_CREDENTIAL_NOT_FOUND`
    ..."

    Design: Corner/errors/credential_redeem_not_found_returns_404
    """
    ba = register_agent(name="CNF BA", license_number="LIC-CNF-BA")
    resp = api_client.redeem_access_credential(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_buyer_agent_headers(ba["id"]))
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_ACCESS_CREDENTIAL_NOT_FOUND)


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with `response_type` "error", a `data` object
    carrying `error_id` and `message`, and "The `meta` object for error
    responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    resp = api_client.get_agent(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_admin_headers())
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("response_type") == "error", body
    data = body.get("data") or {}
    assert data.get("error_id") == "ERR_AGENT_NOT_FOUND", body
    assert isinstance(data.get("message"), str) and data["message"], body
    assert body.get("meta", {}).get("api_request_id"), body


def test_buyer_agent_cannot_approve(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.4: "The seller who owns the listing approves a request sitting in
    PENDING_APPROVAL."

    Design: Corner/rbac/buyer_agent_cannot_approve
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    resp = api_client.approve_showing_request(req["id"], world["ba_headers"])
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_platform_admin_cannot_decline(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Decline is authorized for Seller only.

    Design: Corner/rbac/platform_admin_cannot_decline
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    resp = api_client.decline_showing_request(
        req["id"], make_admin_headers(), payload={"reason": "admin override attempt"})
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_redeem_by_other_buyer_not_owner(api):
    """PRD §2.1: "When `X-User-Role` is `BuyerAgent`, `X-User-ID` is likewise
    the `id` of the acting `Agent`; ownership checks on showing requests,
    access credentials, and feedback requests compare the relevant
    `buyer_agent_id` — held directly on the showing request, and reached
    through the parent showing request for credentials and feedback — to
    `X-User-ID`." PRD §2.7 stage 5: "an entity-backed caller owns the target
    resource ... else `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/redeem_by_other_buyer_not_owner
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    cred = issue_credential(req["id"], world["listing_agent"]["id"], "LOCKBOX_CODE")

    other = register_and_verify_agent(name="Other Buyer", license_number="LIC-RO-BA2")
    resp = api_client.redeem_access_credential(cred["id"], make_buyer_agent_headers(other["id"]))
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
