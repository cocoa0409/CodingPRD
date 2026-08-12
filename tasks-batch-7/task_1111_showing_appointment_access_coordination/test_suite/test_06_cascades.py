"""Transitive cascades: withdraw CASCADE A (depth 3) and no-show CASCADE B (depth 4)."""
import pytest

from test_helpers import (
    api_client,
    cancel_request,
    create_confirmed_request,
    create_listing,
    create_showing_request,
    get_agent_strikes,
    get_success_data,
    issue_credential,
    make_admin_headers,
    make_seller_headers,
    set_clock,
    setup_basic_world,
    setup_occupied_manual_world,
    validate_success,
)


def _feedback_of(world, request_id):
    resp = api_client.get_feedback_request_of_showing(request_id, world["la_headers"])
    return get_success_data(resp)


def _credentials_of(world, request_id):
    resp = api_client.list_access_credentials(request_id, world["la_headers"])
    return get_success_data(resp)


def test_withdraw_cascade_cancels_requests_and_marks_system_actor(api):
    """PRD §3.2: "Hop 1: every showing request of this listing in
    PENDING_APPROVAL, APPROVED, or CONFIRMED moves to CANCELLED with
    `cancel_actor` set to SYSTEM and `cancelled_at` stamped to now."

    Design: Difficulty/transitive_cascade/withdraw_cascade_depth3
    """
    world = setup_occupied_manual_world()
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]
    seller_id = world["seller"]["id"]

    r1 = create_confirmed_request(listing_id, ba_id, seller_id,
                                  "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    issue_credential(r1["id"], world["listing_agent"]["id"], "LOCKBOX_CODE")
    r2 = create_showing_request(listing_id, ba_id,
                                "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")

    validate_success(api_client.withdraw_listing(listing_id, world["la_headers"]))

    r1_after = validate_success(api_client.get_showing_request(r1["id"], world["la_headers"]))
    r2_after = validate_success(api_client.get_showing_request(r2["id"], world["la_headers"]))
    assert r1_after["status"] == "CANCELLED" and r1_after["cancel_actor"] == "SYSTEM", r1_after
    assert r2_after["status"] == "CANCELLED" and r2_after["cancel_actor"] == "SYSTEM", r2_after

    listing_after = validate_success(api_client.get_listing(listing_id, world["la_headers"]))
    assert listing_after["status"] == "WITHDRAWN", listing_after
    assert listing_after["confirmed_showing_count"] == 0, listing_after


def test_withdraw_cascade_revokes_credential_and_cancels_feedback(api):
    """PRD §3.2: "Hop 2: for each of those requests that had been CONFIRMED,
    its credential in ISSUED status moves to REVOKED with a
    `CREDENTIAL_REVOKED` event, and the listing's `confirmed_showing_count` is
    decremented once per such confirmed cancellation. Hop 3: each cancelled
    request's feedback request still in SCHEDULED moves to CANCELLED, and a
    `CANCELLED` event is appended per request."

    Design: Difficulty/transitive_cascade/withdraw_cascade_depth3
    """
    world = setup_occupied_manual_world()
    listing_id = world["listing"]["id"]
    r1 = create_confirmed_request(listing_id, world["buyer_agent"]["id"],
                                  world["seller"]["id"],
                                  "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    issue_credential(r1["id"], world["listing_agent"]["id"], "LOCKBOX_CODE")

    validate_success(api_client.withdraw_listing(listing_id, world["la_headers"]))

    creds = _credentials_of(world, r1["id"])
    assert creds and creds[0]["status"] == "REVOKED", creds
    feedback = _feedback_of(world, r1["id"])
    assert feedback and feedback[0]["status"] == "CANCELLED", feedback


def _setup_suspension_cascade_world():
    """Verified buyer with: a LATE_CANCEL strike (10), a CONFIRMED request R2
    on L2 whose window has passed, and a future CONFIRMED request R3 on L3 with
    an ISSUED credential. Returns (world, l1, l2, l3, r2, r3)."""
    world = setup_basic_world(occupancy_type="VACANT", auto_approve=True)
    seller_id = world["seller"]["id"]
    la_id = world["listing_agent"]["id"]
    ba_id = world["buyer_agent"]["id"]

    l1 = world["listing"]
    l2 = create_listing(seller_id, la_id, occupancy_type="VACANT")
    l3 = create_listing(seller_id, la_id, occupancy_type="VACANT")

    # R1: confirm then cancel at t0 (10h before start < 24h) -> LATE_CANCEL (10)
    r1 = create_confirmed_request(l1["id"], ba_id, seller_id,
                                  "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    cancel_request(r1["id"], ba_id, reason="buyer cold feet")

    # R2: confirmed on L2, window passes without redemption
    r2 = create_confirmed_request(l2["id"], ba_id, seller_id,
                                  "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")

    # R3: future confirmed on L3 with a credential issued
    r3 = create_confirmed_request(l3["id"], ba_id, seller_id,
                                  "2026-05-03T10:00:00Z", "2026-05-03T10:30:00Z")
    issue_credential(r3["id"], la_id, "DOOR_CODE")

    set_clock("2026-05-01T12:45:00Z")
    return world, l1, l2, l3, r2, r3


def test_no_show_declaration_issues_strike_and_suspends_at_35_points(api):
    """PRD §3.6: "Hop 1: a StrikeRecord of `strike_type` NO_SHOW, `weight` 25,
    is created against the buyer agent ... with a `STRIKE_ISSUED` event. Hop 2:
    the agent's standing is recomputed from the new point total." and "An agent
    at 30 points or more is SUSPENDED."

    Design: Difficulty/transitive_cascade/no_show_suspension_cascade_depth4
    """
    world, l1, l2, l3, r2, r3 = _setup_suspension_cascade_world()
    ba_id = world["buyer_agent"]["id"]

    resp = api_client.declare_no_show(r2["id"], world["la_headers"])
    declared = validate_success(resp)
    assert declared["status"] == "NO_SHOW", declared

    agent_after = validate_success(api_client.get_agent(ba_id, make_admin_headers()))
    assert agent_after["standing"] == "SUSPENDED", agent_after
    assert agent_after["active_strike_points"] == 35, agent_after  # 10 + 25


def test_no_show_suspension_cancels_future_confirmed_and_revokes_credential(api):
    """PRD §3.6: "Hop 3: if the recompute transitioned the agent INTO
    SUSPENDED, every other showing request of that agent in PENDING_APPROVAL,
    APPROVED, or CONFIRMED whose `start_at` lies in the future is moved to
    CANCELLED with `cancel_actor` SYSTEM. Hop 4: for each of those hop-3
    cancellations that had been CONFIRMED, the request's ISSUED credential is
    revoked, its SCHEDULED feedback request is cancelled, and its listing's
    `confirmed_showing_count` is decremented."

    Design: Difficulty/transitive_cascade/no_show_suspension_cascade_depth4
    """
    world, l1, l2, l3, r2, r3 = _setup_suspension_cascade_world()

    validate_success(api_client.declare_no_show(r2["id"], world["la_headers"]))

    r3_after = validate_success(api_client.get_showing_request(r3["id"], world["la_headers"]))
    assert r3_after["status"] == "CANCELLED", r3_after
    assert r3_after["cancel_actor"] == "SYSTEM", r3_after

    creds = _credentials_of(world, r3["id"])
    assert creds and creds[0]["status"] == "REVOKED", creds

    l3_after = validate_success(api_client.get_listing(l3["id"], world["la_headers"]))
    assert l3_after["confirmed_showing_count"] == 0, l3_after
