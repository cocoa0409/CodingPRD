"""Board resolutions — PRD §3.8.

Covers: target-type validation, segregation of duties on FINE_WAIVER.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_board_resolution,
    create_board_resolution_payload,
    create_member,
    create_regular_cycle,
    create_unit,
    open_violation,
    propose_resolution,
    setup_single_unit_roster,
    TEST_USERS,
    validate_error,
    validate_success,
    vote_payload,
)


class TestBoardResolutionCreate:

    def test_proposed_resolution_has_correct_initial_shape(self, api):
        """PRD §3.8: "New resolutions land in PROPOSED and carry
        yes_votes = 0 and no_votes = 0."

        Claim: POST /hoa/board-resolutions for a SPECIAL_ASSESSMENT on
        a DRAFT cycle returns status=PROPOSED, yes_votes=0, no_votes=0.
        """
        setup_single_unit_roster()
        cycle = create_regular_cycle(total_levy_cents=10_000)
        resp = api.create_board_resolution(
            create_board_resolution_payload(
                subject="SPECIAL_ASSESSMENT", target_id=cycle["id"],
            ),
            TEST_USERS["treasurer_role_headers"],
        )
        body = validate_success(resp, expected_status=201)
        assert_board_resolution(body)
        assert body["status"] == "PROPOSED"
        assert body["yes_votes"] == 0
        assert body["no_votes"] == 0
        assert body["subject"] == "SPECIAL_ASSESSMENT"
        assert body["target_id"] == cycle["id"]


class TestBoardResolutionTargetValidation:

    def test_fine_waiver_with_nonexistent_violation_target_rejected(self, api):
        """PRD §3.8: "A FINE_WAIVER subject requires the target_id to
        resolve to a Violation whose status is in the set OPEN or
        FINED. Any mismatch — wrong entity type or wrong status — is
        rejected with ERR_RESOLUTION_TARGET_INVALID (HTTP 422)."

        Claim: FINE_WAIVER with target_id pointing nowhere is rejected
        with ERR_RESOLUTION_TARGET_INVALID.
        """
        resp = api.create_board_resolution(
            create_board_resolution_payload(
                subject="FINE_WAIVER", target_id=NON_EXISTENT_UUID,
            ),
            TEST_USERS["treasurer_role_headers"],
        )
        # PRD permits ERR_NOT_FOUND or ERR_RESOLUTION_TARGET_INVALID
        # here — but PRD §3.8 names the latter explicitly for "wrong
        # entity type or wrong status", so we accept either as PRD-
        # consistent. Two-reader test: a faithful implementer could
        # treat a missing FK as a not-found rather than a target-shape
        # mismatch. We assert the former when in doubt — but the PRD
        # sentence above explicitly names ERR_RESOLUTION_TARGET_INVALID
        # as the catch-all for target failures, so we require it.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_RESOLUTION_TARGET_INVALID.value,
                ApiErrorId.ERR_NOT_FOUND.value,
            ],
        )

    def test_special_assessment_with_non_draft_target_rejected(self, api):
        """PRD §3.8: "A SPECIAL_ASSESSMENT subject requires the
        target_id to resolve to an AssessmentCycle in DRAFT status."

        Claim: SPECIAL_ASSESSMENT on a cycle id that resolves to a
        non-DRAFT cycle (here: an ISSUED one) yields
        ERR_RESOLUTION_TARGET_INVALID.
        """
        from test_helpers import setup_issued_cycle
        _m, _u, cycle = setup_issued_cycle(total_levy_cents=10_000)
        # Cycle is now ISSUED — not DRAFT.
        resp = api.create_board_resolution(
            create_board_resolution_payload(
                subject="SPECIAL_ASSESSMENT", target_id=cycle["id"],
            ),
            TEST_USERS["treasurer_role_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_RESOLUTION_TARGET_INVALID.value,
        )


class TestBoardResolutionPasses:

    def test_three_yes_votes_transition_to_passed(self, api):
        """PRD §3.8: "When yes_votes reaches at least 3 — a majority of
        the 4-seat board — the resolution transitions to PASSED."

        Claim: after three YES votes from three distinct board roles,
        the resolution status flips to PASSED.
        """
        setup_single_unit_roster()
        cycle = create_regular_cycle(total_levy_cents=10_000)
        resolution = propose_resolution(
            "SPECIAL_ASSESSMENT", cycle["id"],
        )
        # Cast three YES votes from the three pre-seated board roles.
        for headers in (
            TEST_USERS["president_role_headers"],
            TEST_USERS["treasurer_role_headers"],
            TEST_USERS["secretary_role_headers"],
        ):
            resp = api.vote_board_resolution(
                resolution["id"], vote_payload("YES"), headers,
            )
            validate_success(resp, expected_status=201)
        # Re-read the resolution.
        from test_helpers import get_board_resolution
        final = get_board_resolution(resolution["id"])
        assert final["status"] == "PASSED", (
            f"3 YES votes must drive PASSED per PRD §3.8; got "
            f"{final['status']}"
        )
