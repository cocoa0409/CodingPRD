"""Cyclic state machines: showing-request decline/reschedule and verification-case reject/resubmit."""
import pytest

from test_helpers import (
    api_client,
    approve_request,
    create_showing_request,
    decline_request,
    get_success_data,
    make_admin_headers,
    make_buyer_agent_headers,
    register_agent,
    setup_occupied_manual_world,
    validate_success,
)


def test_decline_then_reschedule_recomputes_deadline_and_counts(api):
    """PRD §3.4: "A successful reschedule replaces the window, recomputes both
    `approval_deadline` and `confirm_by_deadline`, increments
    `reschedule_count` by one, appends a `RESCHEDULED` event, and bumps the
    `version`."

    At clock 00:00 with timeout 240 / min_notice 120 the rescheduled window
    14:00-14:30 recomputes approval_deadline to max(min(00:00+240m, 14:00-120m),
    00:00+30m) == 2026-05-01T04:00:00Z.

    Design: Difficulty/non_linear_state_machine/showing_request_decline_reschedule_cycle
    """
    world = setup_occupied_manual_world()  # min_notice default 120, timeout default 240
    req = create_showing_request(
        world["listing"]["id"], world["buyer_agent"]["id"],
        "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z",
    )
    assert req["status"] == "PENDING_APPROVAL"
    decline_request(req["id"], world["seller"]["id"], reason="occupied then")

    resp = api_client.reschedule_showing_request(
        req["id"],
        {"start_at": "2026-05-01T14:00:00Z", "end_at": "2026-05-01T14:30:00Z"},
        world["ba_headers"],
    )
    rescheduled = validate_success(resp)
    assert rescheduled["status"] == "PENDING_APPROVAL", rescheduled
    assert rescheduled["reschedule_count"] == 1, rescheduled
    assert rescheduled["approval_deadline"] == "2026-05-01T04:00:00Z", rescheduled
    assert rescheduled["start_at"] == "2026-05-01T14:00:00Z", rescheduled


def test_decline_reschedule_cycle_completes_back_to_approved(api):
    """PRD §3.4: "Rescheduling is the buyer agent's recovery move from
    DECLINED, and only from DECLINED — attempting it from any other state fails
    with `ERR_SHOWING_NOT_DECLINED`." and "The target state is normally
    PENDING_APPROVAL, reopening the occupant's decision."

    Design: Difficulty/non_linear_state_machine/showing_request_decline_reschedule_cycle
    """
    world = setup_occupied_manual_world()
    req = create_showing_request(
        world["listing"]["id"], world["buyer_agent"]["id"],
        "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z",
    )
    decline_request(req["id"], world["seller"]["id"], reason="occupied then")

    resp = api_client.reschedule_showing_request(
        req["id"],
        {"start_at": "2026-05-01T14:00:00Z", "end_at": "2026-05-01T14:30:00Z"},
        world["ba_headers"],
    )
    assert validate_success(resp)["status"] == "PENDING_APPROVAL"

    approved = approve_request(req["id"], world["seller"]["id"])
    assert approved["status"] == "APPROVED", approved


def test_verification_case_reject_resubmit_returns_to_submitted(api):
    """PRD §3.1: "The owning agent may resubmit a REJECTED case with a fresh
    `license_document_ref`, cycling the case back to SUBMITTED while
    incrementing `resubmission_count` by one."

    Design: Difficulty/non_linear_state_machine/verification_case_reject_resubmit_cycle
    """
    agent = register_agent(name="BA Six", license_number="LIC-BA-6")
    ba_headers = make_buyer_agent_headers(agent["id"])
    case = validate_success(api_client.create_verification_case(
        agent["id"], {"license_document_ref": "doc-v1"}, ba_headers), expected_status=201)
    rejected = validate_success(api_client.review_verification_case(
        case["id"], {"decision": "REJECT", "review_notes": "blurry scan"},
        make_admin_headers()))
    assert rejected["status"] == "REJECTED"

    resubmitted = validate_success(api_client.resubmit_verification_case(
        case["id"], {"license_document_ref": "doc-v2"}, ba_headers))
    assert resubmitted["status"] == "SUBMITTED", resubmitted
    assert resubmitted["resubmission_count"] == 1, resubmitted
    assert resubmitted["license_document_ref"] == "doc-v2", resubmitted


def test_verification_case_resubmit_then_approve_flips_agent_verified(api):
    """PRD §3.1: "An APPROVE decision stamps `reviewed_at` with the current
    time, records the notes, and recomputes the agent's `verification_status`
    to VERIFIED." and "an agent is VERIFIED exactly when at least one of that
    agent's VerificationCases sits in APPROVED status, and UNVERIFIED
    otherwise."

    Design: Difficulty/non_linear_state_machine/verification_case_reject_resubmit_cycle
    """
    agent = register_agent(name="BA Six", license_number="LIC-BA-6")
    ba_headers = make_buyer_agent_headers(agent["id"])
    case = validate_success(api_client.create_verification_case(
        agent["id"], {"license_document_ref": "doc-v1"}, ba_headers), expected_status=201)
    api_client.review_verification_case(case["id"], {"decision": "REJECT"},
                                        make_admin_headers())
    api_client.resubmit_verification_case(case["id"], {"license_document_ref": "doc-v2"},
                                          ba_headers)

    approved = validate_success(api_client.review_verification_case(
        case["id"], {"decision": "APPROVE"}, make_admin_headers()))
    assert approved["status"] == "APPROVED"

    agent_after = validate_success(api_client.get_agent(agent["id"], make_admin_headers()))
    assert agent_after["verification_status"] == "VERIFIED", agent_after
