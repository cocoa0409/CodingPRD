"""State-machine corner cases: initial states, invalid transitions, terminal lockdowns."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_request,
    cancel_request,
    create_confirmed_request,
    create_showing_request,
    create_showing_request_payload,
    get_agent_strikes,
    get_feedback_request_id,
    issue_credential,
    make_admin_headers,
    make_buyer_agent_headers,
    redeem_credential,
    register_agent,
    register_and_verify_agent,
    run_sweep,
    set_clock,
    setup_basic_world,
    setup_completed_showing,
    setup_occupied_manual_world,
    setup_vacant_auto_world,
    setup_withdrawn_listing_world,
    validate_error,
    validate_success,
)


def test_showing_request_initial_state_pending_on_occupied(api):
    """PRD §3.3: "In every other case the request is born PENDING_APPROVAL and
    the deadline is a clamped window." (every case other than VACANT +
    auto_approve)

    Design: Corner/state_machines/showing_request_initial_state_pending_on_occupied
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    assert req["status"] == "PENDING_APPROVAL", req


def test_approve_twice_rejected(api):
    """PRD §3.4: "The seller who owns the listing approves a request sitting in
    PENDING_APPROVAL; a request in any other state cannot be approved
    (`ERR_SHOWING_NOT_PENDING_APPROVAL`)."

    Design: Corner/state_machines/approve_twice_rejected
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    approve_request(req["id"], world["seller"]["id"])

    resp = api_client.approve_showing_request(req["id"], world["seller_headers"])
    validate_error(resp, ApiErrorId.ERR_SHOWING_NOT_PENDING_APPROVAL)


def test_cancel_completed_returns_already_terminal(api):
    """PRD §3.4: "one that has already reached a terminal state draws
    `ERR_SHOWING_ALREADY_TERMINAL`."

    Design: Corner/state_machines/cancel_completed_returns_already_terminal
    """
    world = setup_vacant_auto_world()
    req, _cred = setup_completed_showing(world)

    resp = api_client.cancel_showing_request(req["id"], world["ba_headers"], payload={})
    validate_error(resp, ApiErrorId.ERR_SHOWING_ALREADY_TERMINAL)

    after = validate_success(api_client.get_showing_request(req["id"], world["la_headers"]))
    assert after["status"] == "COMPLETED", after


def test_pause_withdrawn_listing_rejected(api):
    """PRD §3.2: "once WITHDRAWN, no further lifecycle action is possible, and
    any pause, resume, or re-withdraw attempt is rejected with
    `ERR_LISTING_ALREADY_WITHDRAWN`."

    Design: Corner/state_machines/pause_withdrawn_listing_rejected
    """
    world = setup_withdrawn_listing_world()
    resp = api_client.pause_listing(world["listing"]["id"], world["la_headers"])
    validate_error(resp, ApiErrorId.ERR_LISTING_ALREADY_WITHDRAWN)


def test_reschedule_non_declined_rejected(api):
    """PRD §3.4: "Rescheduling is the buyer agent's recovery move from
    DECLINED, and only from DECLINED — attempting it from any other state fails
    with `ERR_SHOWING_NOT_DECLINED`."

    Design: Corner/state_machines/reschedule_non_declined_rejected
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    assert req["status"] == "PENDING_APPROVAL"

    resp = api_client.reschedule_showing_request(
        req["id"],
        {"start_at": "2026-05-02T12:00:00Z", "end_at": "2026-05-02T12:30:00Z"},
        world["ba_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SHOWING_NOT_DECLINED)


def test_feedback_submit_before_sent_unavailable(api):
    """PRD §3.7: "A feedback request still SCHEDULED, already EXPIRED, or
    CANCELLED answers with `ERR_FEEDBACK_NOT_AVAILABLE` (HTTP 409)."

    Design: Corner/state_machines/feedback_submit_before_sent_unavailable
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    f_id = get_feedback_request_id(world, req["id"])

    feedback = validate_success(api_client.get_feedback_request_of_showing(req["id"], world["ba_headers"]))
    assert feedback[0]["status"] == "SCHEDULED", feedback

    resp = api_client.submit_feedback(
        f_id, {"q1": 5, "q2": 5, "q3": 5, "q4": 5, "q5": 5}, world["ba_headers"])
    validate_error(resp, ApiErrorId.ERR_FEEDBACK_NOT_AVAILABLE)


def test_credential_redeem_before_active_window(api):
    """PRD §3.5: "now must be at or after `active_from`, else
    `ERR_CREDENTIAL_NOT_YET_ACTIVE` (HTTP 422)."

    Design: Corner/state_machines/credential_redeem_before_active_window
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    cred = issue_credential(req["id"], world["listing_agent"]["id"], "DOOR_CODE")
    assert cred["active_from"] == "2026-05-01T09:00:00Z", cred

    set_clock("2026-05-01T08:00:00Z")
    resp = api_client.redeem_access_credential(cred["id"], world["ba_headers"])
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_YET_ACTIVE)


def test_strike_double_forgive_rejected(api):
    """PRD §3.6: "forgiving anything not currently ACTIVE fails with
    `ERR_STRIKE_NOT_ACTIVE`."

    Design: Corner/state_machines/strike_double_forgive_rejected
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    cancel_request(req["id"], world["buyer_agent"]["id"])  # late cancel -> strike
    strike_id = get_agent_strikes(world["buyer_agent"]["id"])[0]["id"]

    validate_success(api_client.forgive_strike(strike_id, {}, make_admin_headers()))
    resp = api_client.forgive_strike(strike_id, {}, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_STRIKE_NOT_ACTIVE)


def test_review_already_reviewed_case_rejected(api):
    """PRD §3.1: "a case that is no longer SUBMITTED cannot be reviewed, and
    the attempt fails with `ERR_CASE_NOT_SUBMITTED`."

    Design: Corner/state_machines/review_already_reviewed_case_rejected
    """
    agent = register_agent(name="RR BA", license_number="LIC-RR-BA")
    ba_headers = make_buyer_agent_headers(agent["id"])
    case = validate_success(api_client.create_verification_case(
        agent["id"], {"license_document_ref": "doc-rr"}, ba_headers), expected_status=201)
    validate_success(api_client.review_verification_case(
        case["id"], {"decision": "APPROVE"}, make_admin_headers()))

    resp = api_client.review_verification_case(
        case["id"], {"decision": "REJECT"}, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_SUBMITTED)
