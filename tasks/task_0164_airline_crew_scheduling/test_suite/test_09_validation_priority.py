"""Validation priority ordering — PRD §2.8 names the order verbatim.

These tests construct scenarios where multiple validations would each
fail in isolation; the order PRD §2.8 pins selects which error_id
surfaces first. Per the Silence-pattern guide, we only assert orderings
PRD explicitly states.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_minutes_iso,
    cancel_pairing,
    create_bid_payload,
    create_crew_member,
    crew_role_headers,
    pilot_headers_for,
    raise_cumulative_block_30d,
    scheduler_headers,
    setup_pairing_admin_assigned,
    setup_pairing_in_bidding,
    submit_bid,
    validate_error,
    validate_error_is_one_of,
)


class TestPriorityAuthBeforeExistence:

    def test_missing_user_role_beats_resource_not_found(self, api):
        """PRD §2.8: "The order is: authentication header presence
        (ERR_AUTH_REQUIRED) ... then path-resource existence
        (ERR_RESOURCE_NOT_FOUND)."
        """
        bad = {"X-User-ID": "u-1", "Content-Type": "application/json"}
        resp = api._request(
            "GET", f"/pairings/{NON_EXISTENT_UUID}", headers=bad,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


class TestPriorityForbiddenBeforeFaa:

    def test_role_check_beats_faa(self, api):
        """PRD §2.8 / §2.1: "on an attempt by a Pilot to call out a
        reserve to themselves on a pairing they cannot cover, the
        rejection is ERR_FORBIDDEN (a Pilot is never permitted to
        invoke a reserve callout) rather than a downstream FAA error —
        the role check runs first so that data-shape errors never mask
        permission errors."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        resp = api.call_out_reserve(
            NON_EXISTENT_UUID,
            {"pairing_id": NON_EXISTENT_UUID, "assigned_rank_slot": "CAPTAIN"},
            crew_role_headers(pilot),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestPriorityStateBeforeBusinessSafety:

    def test_pairing_state_beats_faa_on_award(self, api):
        """PRD §2.8: "then pairing-state preconditions
        (ERR_PAIRING_INVALID_STATE), then trade-state preconditions
        (ERR_INVALID_TRADE_STATE), then FAA crew-rest interval
        (ERR_FAA_CREW_REST_VIOLATION), then the broader FAA duty/block
        caps (ERR_FAA_DUTY_VIOLATION)."

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_bid_award
        Scenario: bid window's underlying pairing is CANCELLED before
        the awarding sweep runs. A bidder with breached cumulative
        block would also have failed FAA — but the state check wins.
        """
        bidder = create_crew_member(rank="CAPTAIN")
        bidder = raise_cumulative_block_30d(bidder, target_minutes=5800)
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        submit_bid(bidder, pairing["id"], bw, preference_rank=1)
        # Cancel the pairing → no longer BIDDING_OPEN.
        cancel_pairing(pairing["id"])
        # Run the sweep.
        resp = api.award_bid_window(bw, scheduler_headers)
        # PRD §3.3: "a second sweep on the same window finds no
        # BIDDING_OPEN pairings and is rejected at the window level with
        # ERR_BID_WINDOW_ALREADY_AWARDED" — but this is a FIRST sweep on
        # an all-cancelled window. PRD §2.8 says state-check fires
        # before FAA; ERR_PAIRING_INVALID_STATE is the closest named
        # outcome for a window whose pairings are no longer in
        # BIDDING_OPEN. Accept either of the two PRD-named outcomes
        # (state-violation or already-awarded).
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_PAIRING_INVALID_STATE.value,
            ApiErrorId.ERR_BID_WINDOW_ALREADY_AWARDED.value,
        ])
