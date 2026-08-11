"""Validation-pipeline corner cases: auth, role, ownership, shape, temporal rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_request,
    create_confirmed_request,
    create_listing_payload,
    create_showing_request,
    create_showing_request_payload,
    create_seller_payload,
    issue_credential,
    make_admin_headers,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    make_seller_headers,
    redeem_credential,
    register_agent,
    register_and_verify_agent,
    run_sweep,
    set_clock,
    setup_occupied_manual_world,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def test_create_listing_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that arrives without these headers, or carrying a
    role value the platform does not recognize, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/create_listing_missing_auth_headers_unauthenticated
    """
    resp = api_client.create_listing(
        create_listing_payload("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                               address="1 NoAuth St", occupancy_type="VACANT"),
        headers={},
    )
    assert resp.status_code == 401
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_seller_create_showing_forbidden_role(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    POST /showing-desk/showing-requests is authorized for BuyerAgent only.

    Design: Corner/validations/seller_create_showing_forbidden_role
    """
    seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="FR S", contact_email="fr@x.com"),
        make_admin_headers()), expected_status=201)
    resp = api_client.create_showing_request(
        create_showing_request_payload("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                                       "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z"),
        make_seller_headers(seller["id"]),
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_not_owner_seller_cannot_approve(api):
    """PRD §2.1: "When a role is entity-backed and the caller does not own the
    resource being acted upon, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)." PRD §3.4: "The seller who owns the
    listing approves a request sitting in PENDING_APPROVAL."

    Design: Corner/validations/not_owner_seller_cannot_approve
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")

    other_seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="Other", contact_email="o2@x.com"),
        make_admin_headers()), expected_status=201)
    resp = api_client.approve_showing_request(req["id"], make_seller_headers(other_seller["id"]))
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_create_listing_invalid_enum_occupancy(api):
    """PRD §2.7 stage 2: "Request shape: required fields are present, types are
    correct, enum values are valid, and unknown fields are rejected, else
    `ERR_INVALID_REQUEST`." PRD §3.2: "an `occupancy_type` of either VACANT or
    OCCUPIED."

    'LOFT' is not a valid occupancy_type; the shape stage precedes seller
    existence.

    Design: Corner/validations/create_listing_invalid_enum_occupancy
    """
    la = register_agent(name="EN LA", license_number="LIC-EN-LA")
    resp = api_client.create_listing(
        create_listing_payload("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                               address="2 Enum St", occupancy_type="LOFT"),
        make_listing_agent_headers(la["id"]),
    )
    assert resp.status_code == 400
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_end_before_start_invalid_time_range(api):
    """PRD §3.3: "The window itself must be sane: `end_at` strictly later than
    `start_at` and the duration no longer than 120 minutes, else
    `ERR_INVALID_TIME_RANGE` (HTTP 422)."

    Design: Corner/validations/end_before_start_invalid_time_range
    """
    world = setup_vacant_auto_world()
    resp = api_client.create_showing_request(
        create_showing_request_payload(world["listing"]["id"],
                                       "2026-05-02T10:30:00Z", "2026-05-02T10:00:00Z"),
        world["ba_headers"],
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


def test_insufficient_lead_time_rejected(api):
    """PRD §3.3: "The start must respect the listing's notice floor — the gap
    between now and `start_at` must be at least `min_notice_minutes`, else
    `ERR_INSUFFICIENT_LEAD_TIME` (HTTP 422)."

    Design: Corner/validations/insufficient_lead_time_rejected
    """
    world = setup_vacant_auto_world()  # min_notice default 120
    resp = api_client.create_showing_request(
        create_showing_request_payload(world["listing"]["id"],
                                       "2026-05-01T00:30:00Z", "2026-05-01T01:00:00Z"),
        world["ba_headers"],
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LEAD_TIME)


def test_rating_out_of_range_rejected(api):
    """PRD §2.7 stage 2: "Within this stage, rating answers `q1` through `q5`
    must be integers from 1 to 5 inclusive; a rating outside that range is
    reported as `ERR_RATING_OUT_OF_RANGE`."

    The shape stage runs before existence, so even a non-existent feedback id
    with q1=6 yields ERR_RATING_OUT_OF_RANGE.

    Design: Corner/validations/rating_out_of_range_rejected
    """
    ba = register_agent(name="RQ BA", license_number="LIC-RQ-BA")
    resp = api_client.submit_feedback(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
        {"q1": 6, "q2": 5, "q3": 5, "q4": 5, "q5": 5},
        make_buyer_agent_headers(ba["id"]),
    )
    assert resp.status_code == 400
    validate_error(resp, ApiErrorId.ERR_RATING_OUT_OF_RANGE)


def test_verification_case_open_conflict(api):
    """PRD §3.1: "An agent may have at most one case in flight: filing while
    another of the agent's cases is still SUBMITTED is rejected with
    `ERR_VERIFICATION_CASE_OPEN` (HTTP 409)."

    Design: Corner/validations/verification_case_open_conflict
    """
    agent = register_agent(name="VC BA", license_number="LIC-VC-BA")
    ba_headers = make_buyer_agent_headers(agent["id"])
    validate_success(api_client.create_verification_case(
        agent["id"], {"license_document_ref": "doc-vc-1"}, ba_headers), expected_status=201)

    resp = api_client.create_verification_case(
        agent["id"], {"license_document_ref": "doc-vc-2"}, ba_headers)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_CASE_OPEN)


def test_credential_already_issued_rejected(api):
    """PRD §3.5: "is refused when a credential in ISSUED or USED status already
    exists for the request, drawing `ERR_CREDENTIAL_ALREADY_ISSUED` (HTTP
    409)."

    Design: Corner/validations/credential_already_issued_rejected
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    issue_credential(req["id"], world["listing_agent"]["id"], "LOCKBOX_CODE")

    resp = api_client.issue_access_credential(
        req["id"], {"credential_type": "DOOR_CODE"}, world["la_headers"])
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_ALREADY_ISSUED)


def test_approval_deadline_passed_then_sweep_expires(api):
    """PRD §3.4: "Approval is also time-boxed: once now reaches the request's
    `approval_deadline`, approval is rejected with
    `ERR_APPROVAL_DEADLINE_PASSED` (HTTP 422), because the occupant's decision
    window has closed." PRD §3.4: "a request still PENDING_APPROVAL once now
    reaches its `approval_deadline` moves to EXPIRED."

    Seller timeout 60, OCCUPIED listing, request created at 00:00 for a 10:00
    start: deadline = max(00:00+30m, min(00:00+60m, 10:00-120m)) == 01:00.

    Design: Corner/validations/approval_deadline_passed_then_sweep_expires
    """
    world = setup_occupied_manual_world()
    seller = world["seller"]
    # Tighten the seller's approval timeout to 60 minutes via the OCC-guarded write.
    seller = validate_success(api_client.update_seller_approval_settings(
        seller["id"],
        {"approval_timeout_minutes": 60, "expected_seller_version": seller["version"]},
        world["seller_headers"]))

    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    assert req["approval_deadline"] == "2026-05-01T01:00:00Z", req

    set_clock("2026-05-01T02:00:00Z")
    resp = api_client.approve_showing_request(req["id"], world["seller_headers"])
    validate_error(resp, ApiErrorId.ERR_APPROVAL_DEADLINE_PASSED)

    sweep = run_sweep()
    assert sweep["requests_expired_count"] == 1, sweep
    after = validate_success(api_client.get_showing_request(req["id"], world["seller_headers"]))
    assert after["status"] == "EXPIRED", after


def test_confirm_deadline_passed_rejected(api):
    """PRD §3.5: "The action must also beat the clock: once now reaches the
    `confirm_by_deadline`, confirmation is rejected with
    `ERR_CONFIRM_DEADLINE_PASSED` (HTTP 422)." PRD §3.3: "The
    `confirm_by_deadline` is always one hour (60 minutes) before the window's
    `start_at`." PRD §3.4: "a request sitting APPROVED once now reaches its
    `confirm_by_deadline` likewise moves to EXPIRED."

    Design: Corner/validations/confirm_deadline_passed_rejected
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    assert req["confirm_by_deadline"] == "2026-05-01T09:00:00Z", req
    approve_request(req["id"], world["seller"]["id"])

    set_clock("2026-05-01T09:30:00Z")
    resp = api_client.confirm_showing_request(req["id"], world["ba_headers"])
    validate_error(resp, ApiErrorId.ERR_CONFIRM_DEADLINE_PASSED)

    run_sweep()
    after = validate_success(api_client.get_showing_request(req["id"], world["seller_headers"]))
    assert after["status"] == "EXPIRED", after


def test_no_show_too_early_rejected(api):
    """PRD §3.6: "Declaring before `end_at` has passed is premature and fails
    with `ERR_NO_SHOW_TOO_EARLY` (HTTP 422)."

    Design: Corner/validations/no_show_too_early_rejected
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    set_clock("2026-05-01T10:15:00Z")
    resp = api_client.declare_no_show(req["id"], world["la_headers"])
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_NO_SHOW_TOO_EARLY)


def test_no_show_blocked_when_credential_used(api):
    """PRD §3.6: "declaring when any credential of the request has been USED is
    contradictory and fails with `ERR_NO_SHOW_NOT_DECLARABLE` (HTTP 409)."

    Design: Corner/validations/no_show_blocked_when_credential_used
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    cred = issue_credential(req["id"], world["listing_agent"]["id"], "SMART_LOCK")
    set_clock("2026-05-01T10:05:00Z")
    redeem_credential(cred["id"], world["buyer_agent"]["id"])

    set_clock("2026-05-01T10:45:00Z")
    resp = api_client.declare_no_show(req["id"], world["la_headers"])
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_NO_SHOW_NOT_DECLARABLE)
