"""Lockbox state machine and showing approval workflow.

Cites PRD §2.8 (Lockbox Discipline), §3.5 (Showings and the Lockbox).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    ACCESS_CODE_LENGTH,
    approve_showing,
    arm_lockbox,
    create_listing_with_armed_lockbox,
    disarm_lockbox,
    iso_from_now,
    iso_in_future,
    iso_in_past,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    request_showing,
    request_showing_payload,
    setup_listing_and_buyer,
    setup_scheduled_showing,
    validate_error,
    validate_success,
)


class TestLockboxStateMachine:
    """PRD §2.8 and PRD §3.5 lockbox state machine."""

    def test_create_lockbox_armed_with_six_digit_code(self, api):
        """PRD §3.5: 'Mounting a lockbox on an ACTIVE listing ...
        creates the lockbox row in ARMED status; the server mints the
        initial access_code and records code_rotated_at.'
        PRD §2.8: 'A lockbox's access_code is a server-minted 6-digit
        numeric string.'

        Claim: POST /listings/{id}/lockbox returns a lockbox in ARMED
        status with a 6-digit numeric access_code and code_rotated_at.
        """
        la, listing, lockbox = create_listing_with_armed_lockbox()
        assert lockbox["status"] == "ARMED"
        code = lockbox["access_code"]
        assert isinstance(code, str)
        assert len(code) == ACCESS_CODE_LENGTH
        assert code.isdigit(), (
            f"PRD §2.8 access_code must be a 6-digit numeric string, got {code!r}"
        )

    def test_arm_already_armed_lockbox_returns_lockbox_state(self, api):
        """PRD §2.8: 'Asking to arm a box that is already ARMED ... is
        rejected with ERR_LOCKBOX_STATE.'

        Claim: POST /lockbox/arm on ARMED → ERR_LOCKBOX_STATE.
        """
        la, listing, lockbox = create_listing_with_armed_lockbox()
        res = api.arm_lockbox(
            listing["id"], make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOCKBOX_STATE.value)

    def test_disarm_disarmed_lockbox_returns_lockbox_state(self, api):
        """PRD §2.8: 'or to disarm a box that is already DISARMED ...
        is rejected with ERR_LOCKBOX_STATE.'

        Claim: POST /lockbox/disarm on DISARMED → ERR_LOCKBOX_STATE.
        """
        la, listing, lockbox = create_listing_with_armed_lockbox()
        disarm_lockbox(listing, la)
        res = api.disarm_lockbox(
            listing["id"], make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOCKBOX_STATE.value)

    def test_retire_armed_lockbox_returns_lockbox_state(self, api):
        """PRD §2.8: 'or to retire a box that is still ARMED ... is
        rejected with ERR_LOCKBOX_STATE.'

        Claim: POST /lockbox/retire on ARMED → ERR_LOCKBOX_STATE.
        """
        la, listing, lockbox = create_listing_with_armed_lockbox()
        res = api.retire_lockbox(
            listing["id"], make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOCKBOX_STATE.value)

    def test_arm_rotates_access_code(self, api):
        """PRD §3.5: 'Arming a lockbox that is DISARMED (only valid
        while the listing is ACTIVE) rotates the access_code to a new
        server-minted 6-digit string and updates code_rotated_at.'

        Claim: ARM after DISARM regenerates access_code (new value)
        and refreshes code_rotated_at.
        """
        la, listing, lockbox = create_listing_with_armed_lockbox()
        original_code = lockbox["access_code"]
        original_rotated = lockbox["code_rotated_at"]
        disarm_lockbox(listing, la)
        armed = arm_lockbox(listing, la)
        assert armed["status"] == "ARMED"
        assert armed["access_code"] != original_code, (
            "PRD §3.5: re-arm must regenerate access_code"
        )
        assert armed["code_rotated_at"] != original_rotated


class TestShowingRequestValidation:
    """PRD §3.5 showing window validation."""

    def test_showing_below_min_duration_rejected(self, api):
        """PRD §3.5: 'The window must be at least 15 minutes and no
        more than 4 hours long, ... otherwise the request is rejected
        with ERR_INVALID_SHOWING_WINDOW.'

        Claim: A 14-minute showing window → ERR_INVALID_SHOWING_WINDOW.
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        payload = request_showing_payload(
            buyer_agent_id=ba["id"], buyer_id=buyer["id"],
            duration_minutes=14, offset_seconds=3600,
        )
        res = api.request_showing(
            listing["id"], payload, make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_SHOWING_WINDOW.value)

    def test_showing_above_max_duration_rejected(self, api):
        """PRD §3.5: 'The window must be at least 15 minutes and no
        more than 4 hours long.'

        Claim: A 4h+1m (= 241-minute) showing → ERR_INVALID_SHOWING_WINDOW.
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        payload = request_showing_payload(
            buyer_agent_id=ba["id"], buyer_id=buyer["id"],
            duration_minutes=241, offset_seconds=3600,
        )
        res = api.request_showing(
            listing["id"], payload, make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_SHOWING_WINDOW.value)

    def test_showing_start_in_past_rejected(self, api):
        """PRD §3.5: 'start_at must be strictly in the future at the
        moment the request is made; otherwise the request is rejected
        with ERR_INVALID_SHOWING_WINDOW.'

        Claim: start_at in the past → ERR_INVALID_SHOWING_WINDOW.
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        start = iso_in_past(3600)
        end = iso_in_past(60)
        payload = request_showing_payload(
            buyer_agent_id=ba["id"], buyer_id=buyer["id"],
            start_at=start, end_at=end,
        )
        res = api.request_showing(
            listing["id"], payload, make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_SHOWING_WINDOW.value)


class TestShowingApproval:
    """PRD §3.5 showing approval preconditions."""

    def test_approve_with_disarmed_lockbox_returns_lockbox_not_armed(
        self, api,
    ):
        """PRD §3.5: 'A lockbox that is not ARMED causes
        ERR_LOCKBOX_NOT_ARMED.'

        Claim: Showing approval with the lockbox DISARMED →
        ERR_LOCKBOX_NOT_ARMED.

        # difficulty: cross_entity_state_dependency/showing_approval_requires_listing_active_and_lockbox_armed
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        # Disarm the lockbox.
        disarm_lockbox(listing, la)
        showing = request_showing(listing, buyer, ba)
        res = api.approve_showing(
            listing["id"], showing["id"],
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOCKBOX_NOT_ARMED.value)

    def test_approve_after_rearming_succeeds(self, api):
        """PRD §3.5: 'A lockbox that is not ARMED causes
        ERR_LOCKBOX_NOT_ARMED.' (so re-arming restores eligibility)

        Claim: After re-arming the lockbox, showing approval returns
        200 and the showing transitions to SCHEDULED.

        # difficulty: cross_entity_state_dependency/showing_approval_requires_listing_active_and_lockbox_armed
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        disarm_lockbox(listing, la)
        showing = request_showing(listing, buyer, ba)
        # Re-arm.
        arm_lockbox(listing, la)
        res = api.approve_showing(
            listing["id"], showing["id"],
            make_listing_agent_headers(la["id"]),
        )
        approved = validate_success(res, 200)
        assert approved["status"] == "SCHEDULED"
        assert approved["lockbox_access_granted_at"] is not None

    def test_approve_returns_access_code_in_response(self, api):
        """PRD §3.5: 'On approval the server vends the lockbox's
        current access_code in the response body, stamps the
        appointment's lockbox_access_granted_at with the current
        logical time.'

        Claim: The approve response carries the lockbox access_code AND
        sets lockbox_access_granted_at.
        """
        state = setup_scheduled_showing()
        approved = state["scheduled_showing"]
        assert approved["lockbox_access_granted_at"] is not None
        # The access_code should appear somewhere in the response body.
        # The PRD says it is "delivered in response body"; the simplest
        # contract is the showing record carries it.
        ac = approved.get("access_code")
        # Accept either field placement: directly on showing or on a
        # nested lockbox object. PRD does not pin the exact key — only
        # that it appears.
        ac_nested = approved.get("lockbox", {}).get("access_code") if isinstance(
            approved.get("lockbox"), dict,
        ) else None
        assert ac or ac_nested, (
            "PRD §3.5: 'the server vends the lockbox's current "
            "access_code in the response body' — no access_code "
            f"found in approve response: keys={list(approved.keys())}"
        )

    def test_approve_increments_showing_count(self, api):
        """PRD §3.5: 'showing_count always equals the number of
        showings on the listing whose status is SCHEDULED or
        COMPLETED.'

        Claim: After approving a showing, the listing's showing_count
        increases by 1 (from 0 to 1 for the first SCHEDULED showing).
        """
        state = setup_scheduled_showing()
        from test_helpers import get_listing_state
        listing_after = get_listing_state(state["listing"]["id"])
        assert listing_after["showing_count"] == 1, (
            f"showing_count expected 1, got {listing_after['showing_count']}"
        )


class TestShowingOverlap:
    """PRD §3.5 overlap detection — half-open intervals; adjacency
    allowed."""

    def test_strict_overlap_rejected(self, api):
        """PRD §3.5: 'no other SCHEDULED showing on the same listing
        may occupy a time interval that overlaps [start_at, end_at) ...
        a colliding interval causes ERR_SHOWING_TIME_OVERLAP.'

        Claim: Approving a second showing whose [start, end) strictly
        overlaps an existing SCHEDULED showing → ERR_SHOWING_TIME_OVERLAP.

        # difficulty: resource_temporal_overlap/showing_overlap_half_open_with_adjacency_allowed
        """
        state = setup_scheduled_showing(
            duration_minutes=60, offset_seconds=3600,
        )
        listing = state["listing"]
        la = state["listing_agent"]
        ba = state["buyer_agent"]
        buyer = state["buyer"]
        # Original window: [T+1h, T+2h). Overlap with [T+1h30m, T+2h30m).
        overlap_start = iso_from_now(seconds=3600 + 1800)
        overlap_end = iso_from_now(seconds=3600 + 1800 + 3600)
        payload = request_showing_payload(
            buyer_agent_id=ba["id"], buyer_id=buyer["id"],
            start_at=overlap_start, end_at=overlap_end,
        )
        showing_resp = api.request_showing(
            listing["id"], payload, make_buyer_agent_headers(ba["id"]),
        )
        body = showing_resp.json()
        assert showing_resp.status_code == 201, body
        showing2 = body["data"]
        res = api.approve_showing(
            listing["id"], showing2["id"],
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SHOWING_TIME_OVERLAP.value)

    def test_adjacency_allowed(self, api):
        """PRD §3.5: 'these are half-open intervals, so an appointment
        whose end_at equals another's start_at, or whose start_at
        equals another's end_at, is adjacent and allowed.'

        Claim: A showing whose start_at == an existing SCHEDULED
        showing's end_at can be approved successfully.

        # difficulty: resource_temporal_overlap/showing_overlap_half_open_with_adjacency_allowed
        """
        state = setup_scheduled_showing(
            duration_minutes=60, offset_seconds=3600,
        )
        listing = state["listing"]
        la = state["listing_agent"]
        ba = state["buyer_agent"]
        buyer = state["buyer"]
        # Original window: [T+1h, T+2h). Adjacent at T+2h.
        adj_start = state["scheduled_showing"]["end_at"]
        # Build adj_end = adj_start + 60min.
        from datetime import datetime, timedelta, timezone
        start_dt = datetime.fromisoformat(adj_start.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(minutes=60)
        from test_helpers import iso_at
        adj_end = iso_at(end_dt)
        payload = request_showing_payload(
            buyer_agent_id=ba["id"], buyer_id=buyer["id"],
            start_at=adj_start, end_at=adj_end,
        )
        showing_resp = api.request_showing(
            listing["id"], payload, make_buyer_agent_headers(ba["id"]),
        )
        showing2 = validate_success(showing_resp, 201)
        res = api.approve_showing(
            listing["id"], showing2["id"],
            make_listing_agent_headers(la["id"]),
        )
        approved = validate_success(res, 200)
        assert approved["status"] == "SCHEDULED"


class TestShowingCancellation:
    """PRD §3.5 cancellation & showing_count side effect."""

    def test_cancel_scheduled_decrements_showing_count(self, api):
        """PRD §3.5: 'either side may cancel a SCHEDULED appointment
        any time strictly before start_at; the row becomes CANCELLED
        and showing_count is decremented.'

        Claim: Cancelling a SCHEDULED showing decrements showing_count
        by 1.
        """
        state = setup_scheduled_showing(
            duration_minutes=60, offset_seconds=24 * 3600,
        )
        listing = state["listing"]
        la = state["listing_agent"]
        from test_helpers import get_listing_state
        before = get_listing_state(listing["id"])
        assert before["showing_count"] == 1
        res = api.cancel_showing(
            listing["id"], state["scheduled_showing"]["id"],
            make_listing_agent_headers(la["id"]),
        )
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"
        after = get_listing_state(listing["id"])
        assert after["showing_count"] == before["showing_count"] - 1
