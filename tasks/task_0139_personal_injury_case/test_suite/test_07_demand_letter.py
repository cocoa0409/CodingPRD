"""Demand letter lifecycle: draft, send, withdraw; snapshot and stale-
snapshot semantics.

PRD §3.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_demand_letter,
    create_demand_letter,
    create_demand_letter_payload,
    get_case,
    get_damages,
    send_demand_letter,
    send_demand_letter_payload,
    setup_demand_sent,
    setup_ready_for_demand,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestDemandLetterDrafting:

    def test_draft_letter_returns_201_in_draft_state(self, api):
        """PRD §3.5: "A newly drafted letter sits in DRAFT with
        snapshot_total_damages_cents of 0 and snapshot_damages_version
        of 0."

        Claim: New letter is DRAFT with zero snapshots.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        letter = create_demand_letter(
            case["id"], damages["total_damages_cents"],
        )
        assert_demand_letter(letter)
        assert letter["status"] == "DRAFT"
        assert letter["snapshot_total_damages_cents"] == 0
        assert letter["snapshot_damages_version"] == 0

    def test_demanded_below_damages_rejected(
        self, api, attorney_headers,
    ):
        """PRD §3.5: "Drafting captures demanded_amount_cents, which
        must be greater than or equal to the current
        Damages.total_damages_cents on the linked damages row; a value
        below the damages total is rejected with
        ERR_DEMAND_BELOW_DAMAGES."

        Claim: demanded_amount_cents < total_damages_cents at draft
        → ERR_DEMAND_BELOW_DAMAGES.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        below = damages["total_damages_cents"] - 1
        resp = api.create_demand_letter(
            case["id"],
            create_demand_letter_payload(below),
            attorney_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEMAND_BELOW_DAMAGES.value)

    def test_second_active_letter_rejected(
        self, api, attorney_headers,
    ):
        """PRD §3.5: "At most one active letter — one whose status is
        DRAFT or SENT — may exist on a case at a time; a second draft
        is rejected with ERR_ACTIVE_DEMAND_EXISTS."

        Claim: Second POST /demand-letters (with a DRAFT letter still
        active) → ERR_ACTIVE_DEMAND_EXISTS.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        create_demand_letter(case["id"], damages["total_damages_cents"])
        resp = api.create_demand_letter(
            case["id"],
            create_demand_letter_payload(damages["total_damages_cents"]),
            attorney_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_DEMAND_EXISTS.value)


class TestDemandLetterSending:

    def test_send_flips_letter_and_case(self, api):
        """PRD §3.5: "the letter's sent_at is stamped to the server's
        current time, its response_due_at is stamped at exactly 30
        calendar days after sent_at, its snapshot_total_damages_cents
        is pinned to the current Damages.total_damages_cents, and its
        snapshot_damages_version is pinned to the current
        Damages.version; the letter advances to SENT and the case
        advances to DEMAND_SENT."

        Claim: After send, letter.status==SENT, case.status==DEMAND_SENT,
        sent_at populated, response_due_at populated.
        """
        _, case, _, _, damages, letter = setup_demand_sent()
        assert letter["status"] == "SENT"
        assert letter["sent_at"] is not None
        assert letter["response_due_at"] is not None
        assert letter["snapshot_total_damages_cents"] == damages["total_damages_cents"]
        assert letter["snapshot_damages_version"] == damages["version"]
        refreshed = get_case(case["id"])
        assert refreshed["status"] == "DEMAND_SENT"

    def test_send_non_draft_letter_rejected(
        self, api, attorney_headers,
    ):
        """PRD §3.5: "The send operation requires the letter to be in
        DRAFT (a non-draft letter is rejected with
        ERR_DEMAND_NOT_DRAFT)".

        Claim: Sending a letter twice → 2nd call ERR_DEMAND_NOT_DRAFT.
        """
        _, case, _, _, damages, letter = setup_demand_sent()
        # First send already done by fixture.
        resp = api.send_demand_letter(
            case["id"], letter["id"], attorney_headers,
            send_demand_letter_payload(),
        )
        validate_error(resp, ApiErrorId.ERR_DEMAND_NOT_DRAFT.value)


class TestStaleDamagesSnapshot:

    def test_send_with_mismatched_expected_damages_version_rejected(
        self, api, attorney_headers,
    ):
        """PRD §3.5: "The caller may optionally supply
        expected_damages_version in the request body to assert which
        version of the damages row they intend to snapshot; if the
        supplied value does not match the current Damages.version, the
        send is rejected with ERR_STALE_DAMAGES_SNAPSHOT."

        Claim: send with expected_damages_version mismatching
        Damages.version → ERR_STALE_DAMAGES_SNAPSHOT.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        letter = create_demand_letter(case["id"], damages["total_damages_cents"])
        resp = api.send_demand_letter(
            case["id"], letter["id"], attorney_headers,
            send_demand_letter_payload(
                expected_damages_version=damages["version"] + 99,
            ),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DAMAGES_SNAPSHOT.value)


class TestDemandLetterWithdraw:

    def test_withdraw_draft_letter_terminal(self, api, attorney_headers):
        """PRD §3.5: "A letter that is still in DRAFT may be withdrawn
        by an Attorney, transitioning it to the terminal state
        WITHDRAWN."

        Claim: POST /withdraw on DRAFT → status WITHDRAWN.
        """
        _, case, _, _, damages = setup_ready_for_demand()
        letter = create_demand_letter(case["id"], damages["total_damages_cents"])
        resp = api.withdraw_demand_letter(
            case["id"], letter["id"], attorney_headers,
        )
        withdrawn = validate_success(resp)
        assert withdrawn["status"] == "WITHDRAWN"

    def test_withdraw_sent_letter_rejected(
        self, api, attorney_headers,
    ):
        """PRD §3.5: "A letter that is still in DRAFT may be
        withdrawn".

        Claim: withdraw on SENT letter → 409 (state-precondition fails).
        Because PRD does not commit to a more specific error code for
        withdraw-on-non-draft, accept ERR_DEMAND_NOT_DRAFT or
        ERR_INVALID_STATE.
        """
        from test_helpers import validate_error_is_one_of
        _, case, _, _, _, letter = setup_demand_sent()
        resp = api.withdraw_demand_letter(
            case["id"], letter["id"], attorney_headers,
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_DEMAND_NOT_DRAFT.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])
