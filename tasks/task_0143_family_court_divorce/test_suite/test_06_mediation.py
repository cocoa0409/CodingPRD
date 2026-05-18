"""Mediation: scheduling, start window, completion, outcomes, cap,
overlap, impose by judge.

PRD §3.4.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    advance_clock_safe,
    advance_clock_to,
    api_client,
    assert_mediation_session,
    complete_mediation_session,
    complete_mediation_session_payload,
    iso_utc,
    make_judge_headers,
    make_mediator_headers,
    parse_iso,
    re_get_case,
    re_get_parenting_plan,
    run_one_full_mediation_session,
    schedule_mediation_session,
    schedule_mediation_session_payload,
    server_now_dt,
    server_offset_iso,
    setup_case_in_mediation_with_proposed_plan,
    setup_case_mediation_round_3_impasse,
    start_mediation,
    start_mediation_session,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Mediator double-booking — PRD §3.4 / §2.10
# ===========================================================================
class TestMediatorDoubleBooked:

    def test_overlapping_sessions_for_same_mediator_rejected(
        self, api, mediator_headers,
    ):
        """PRD §3.4: 'The scheduler must not overlap any other
        SCHEDULED or IN_PROGRESS session on the same mediator_user_id;
        overlap is checked against the half-open interval
        [scheduled_start_at, scheduled_end_at) and on conflict the
        request is rejected with ERR_MEDIATOR_DOUBLE_BOOKED (HTTP
        409).'

        Claim: scheduling a second session whose interval strictly
        overlaps the first (same mediator) is
        ERR_MEDIATOR_DOUBLE_BOOKED.
        """
        ctx_a = setup_case_in_mediation_with_proposed_plan()
        ctx_b = setup_case_in_mediation_with_proposed_plan()
        start = server_offset_iso(hours=1)
        end = server_offset_iso(hours=2)
        # First schedule succeeds.
        first = schedule_mediation_session(
            ctx_a["case"]["id"],
            mediator_user_id="mediator-001",
            scheduled_start_at=start, scheduled_end_at=end,
        )
        assert_mediation_session(first)
        # Second schedule with overlapping interval on SAME mediator.
        overlap_start = server_offset_iso(hours=1, minutes=30)
        overlap_end = server_offset_iso(hours=2, minutes=30)
        res = api.schedule_mediation_session(
            ctx_b["case"]["id"],
            schedule_mediation_session_payload(
                mediator_user_id="mediator-001",
                scheduled_start_at=overlap_start,
                scheduled_end_at=overlap_end,
            ),
            mediator_headers,
        )
        validate_error(
            res, "ERR_MEDIATOR_DOUBLE_BOOKED",
            expected_status=409,
        )

    def test_back_to_back_sessions_permitted_half_open(
        self, api, mediator_headers,
    ):
        """PRD §3.4: 'overlap is checked against the half-open
        interval [scheduled_start_at, scheduled_end_at)'.

        Claim: a second session whose start_at == first session's
        end_at is NOT an overlap (half-open semantics) and is
        accepted.
        """
        ctx_a = setup_case_in_mediation_with_proposed_plan()
        ctx_b = setup_case_in_mediation_with_proposed_plan()
        start1 = server_offset_iso(hours=1)
        end1 = server_offset_iso(hours=2)
        schedule_mediation_session(
            ctx_a["case"]["id"],
            mediator_user_id="mediator-001",
            scheduled_start_at=start1, scheduled_end_at=end1,
        )
        # Back-to-back: starts at end1 (boundary).
        end2 = server_offset_iso(hours=3)
        res = api.schedule_mediation_session(
            ctx_b["case"]["id"],
            schedule_mediation_session_payload(
                mediator_user_id="mediator-001",
                scheduled_start_at=end1,
                scheduled_end_at=end2,
            ),
            mediator_headers,
        )
        body = validate_success(res, 201)
        assert_mediation_session(body)


# ===========================================================================
# Session start window — PRD §3.4
# ===========================================================================
class TestSessionStartWindow:

    def test_start_too_early_rejected(self, api):
        """PRD §3.4: 'this is only permitted when now is at or after
        scheduled_start_at - 15 minutes and at or before
        scheduled_end_at. Outside that window the start request is
        rejected with ERR_SESSION_OUT_OF_WINDOW (HTTP 409).'

        Claim: starting more than 15 minutes before scheduled_start_at
        is rejected.
        """
        ctx = setup_case_in_mediation_with_proposed_plan()
        start = server_offset_iso(hours=2)  # well in the future
        end = server_offset_iso(hours=3)
        session = schedule_mediation_session(
            ctx["case"]["id"],
            mediator_user_id="mediator-001",
            scheduled_start_at=start, scheduled_end_at=end,
        )
        # Do NOT advance the clock — now is ~2 hours before start, so
        # well outside the [-15min, end] start window.
        res = api.start_mediation_session(
            ctx["case"]["id"], session["id"],
            make_mediator_headers("mediator-001"),
        )
        validate_error(
            res, "ERR_SESSION_OUT_OF_WINDOW",
            expected_status=409,
        )


# ===========================================================================
# Completion outcome required — PRD §3.4
# ===========================================================================
class TestOutcomeRequired:

    def test_complete_without_outcome_rejected(self, api):
        """PRD §3.4: 'Completion requires an outcome in the request
        (AGREEMENT, PARTIAL, or IMPASSE); missing outcome is rejected
        with ERR_OUTCOME_REQUIRED (HTTP 422).'

        Claim: POST .../complete with empty body → ERR_OUTCOME_REQUIRED.
        """
        ctx = setup_case_in_mediation_with_proposed_plan()
        start = server_offset_iso(hours=1)
        end = server_offset_iso(hours=2)
        session = schedule_mediation_session(
            ctx["case"]["id"],
            mediator_user_id="mediator-001",
            scheduled_start_at=start, scheduled_end_at=end,
        )
        # Advance into window and start.
        advance_clock_safe(start)
        start_mediation_session(
            ctx["case"]["id"], session["id"],
            mediator_user_id="mediator-001",
        )
        # Complete with empty body.
        res = api.complete_mediation_session(
            ctx["case"]["id"], session["id"], {},
            make_mediator_headers("mediator-001"),
        )
        validate_error(
            res, "ERR_OUTCOME_REQUIRED", expected_status=422,
        )


# ===========================================================================
# Cancellation — PRD §3.4
# ===========================================================================
class TestCancel:

    def test_cancel_after_start_rejected(self, api, mediator_headers):
        """PRD §3.4: 'A session can also be cancelled before it starts
        (rejected with ERR_SESSION_ALREADY_STARTED, HTTP 409, if now
        is at or after scheduled_start_at)'.

        Claim: advancing past start and then cancelling is
        ERR_SESSION_ALREADY_STARTED.
        """
        ctx = setup_case_in_mediation_with_proposed_plan()
        start = server_offset_iso(hours=1)
        end = server_offset_iso(hours=2)
        session = schedule_mediation_session(
            ctx["case"]["id"],
            mediator_user_id="mediator-001",
            scheduled_start_at=start, scheduled_end_at=end,
        )
        # Advance to >= scheduled_start_at (at exact start).
        advance_clock_safe(start)
        res = api.cancel_mediation_session(
            ctx["case"]["id"], session["id"], mediator_headers,
        )
        validate_error(
            res, "ERR_SESSION_ALREADY_STARTED",
            expected_status=409,
        )


# ===========================================================================
# No-show — PRD §3.4
# ===========================================================================
class TestNoShow:

    def test_no_show_before_end_rejected(self, api, mediator_headers):
        """PRD §3.4: 'a no-show request submitted earlier is rejected
        with ERR_SESSION_NOT_OVER (HTTP 409).'

        Claim: POST .../no-show before scheduled_end_at is
        ERR_SESSION_NOT_OVER.
        """
        ctx = setup_case_in_mediation_with_proposed_plan()
        start = server_offset_iso(hours=1)
        end = server_offset_iso(hours=2)
        session = schedule_mediation_session(
            ctx["case"]["id"],
            mediator_user_id="mediator-001",
            scheduled_start_at=start, scheduled_end_at=end,
        )
        # Don't advance — now is before end.
        res = api.no_show_mediation_session(
            ctx["case"]["id"], session["id"], mediator_headers,
        )
        validate_error(
            res, "ERR_SESSION_NOT_OVER", expected_status=409,
        )


# ===========================================================================
# Mediation cap — PRD §3.4
# ===========================================================================
class TestMediationCap:

    def test_fourth_session_after_three_completed_rejected(
        self, api, mediator_headers,
    ):
        """PRD §3.4: 'when Case.mediation_round has already reached 3,
        a fourth scheduling attempt is rejected with
        ERR_MEDIATION_CAP_REACHED (HTTP 409)'.

        Claim: after three COMPLETED sessions, scheduling a fourth is
        ERR_MEDIATION_CAP_REACHED.
        """
        ctx = setup_case_mediation_round_3_impasse()
        case_after = re_get_case(ctx["case"]["id"])
        assert case_after["mediation_round"] == 3, (
            f"setup invariant: mediation_round must be 3 after 3 "
            f"IMPASSE sessions; got {case_after['mediation_round']!r}"
        )
        # Attempt 4th session.
        start = server_offset_iso(hours=1)
        end = server_offset_iso(hours=2)
        res = api.schedule_mediation_session(
            ctx["case"]["id"],
            schedule_mediation_session_payload(
                mediator_user_id="mediator-001",
                scheduled_start_at=start,
                scheduled_end_at=end,
            ),
            mediator_headers,
        )
        validate_error(
            res, "ERR_MEDIATION_CAP_REACHED",
            expected_status=409,
        )


# ===========================================================================
# Mediation -> Contested plan after 3rd impasse — PRD §3.4
# ===========================================================================
class TestImpasseAfterCapMarksPlanContested:

    def test_third_impasse_transitions_plan_to_contested(self, api):
        """PRD §3.4: 'If the outcome is IMPASSE and
        Case.mediation_round has now reached 3, the latest active plan
        in PROPOSED or COUNTERED transitions to CONTESTED.'

        Claim: after the 3rd IMPASSE, the still-PROPOSED plan
        cascades to CONTESTED.
        """
        ctx = setup_case_mediation_round_3_impasse()
        plan = re_get_parenting_plan(
            ctx["case"]["id"], ctx["parenting_plan"]["id"],
        )
        assert plan["status"] == "CONTESTED", (
            f"plan must be CONTESTED after 3rd IMPASSE; got "
            f"{plan['status']!r}"
        )


# ===========================================================================
# Impose — PRD §3.4
# ===========================================================================
class TestImposeByJudge:

    def test_impose_requires_mediation_round_3(self, api, judge_headers):
        """PRD §3.4: 'a CONTESTED plan may be court-imposed by a
        Judge; the request requires the plan to be in CONTESTED status
        and Case.mediation_round to be at least 3 (otherwise
        ERR_MEDIATION_NOT_EXHAUSTED, HTTP 409).'

        Claim: attempting to impose before round 3 fires
        ERR_MEDIATION_NOT_EXHAUSTED. Note: PRD also requires the plan
        to be in CONTESTED — to isolate the round check, the plan must
        first be CONTESTED, which only happens via IMPASSE at round 3.
        Since the two preconditions cannot both fail simultaneously
        in an isolatable way, this test uses an AGREED plan (status
        not CONTESTED) and accepts either ERR_INVALID_STATE (state
        precondition) or ERR_MEDIATION_NOT_EXHAUSTED. PRD §2.11 pins
        state-precondition checks at priority 5 (before
        business_constraint at priority 16), so
        ERR_INVALID_STATE is the deterministic outcome here.
        """
        # Setup AGREED plan, round=0; impose attempt.
        from test_helpers import setup_case_with_agreed_plan
        ctx = setup_case_with_agreed_plan()
        plan = ctx["parenting_plan"]
        res = api.impose_parenting_plan(
            ctx["case"]["id"], plan["id"], judge_headers,
        )
        # Per PRD §2.11 ordering, ERR_INVALID_STATE precedes business-
        # constraint ERR_MEDIATION_NOT_EXHAUSTED. PRD §2.11: 'state-
        # transition legality (ERR_INVALID_STATE); ... then business-
        # constraint checks'.
        validate_error(
            res, "ERR_INVALID_STATE", expected_status=409,
        )

    def test_impose_after_round_3_with_contested_plan_succeeds(
        self, api, judge_headers,
    ):
        """PRD §3.4: 'On success the plan transitions to
        COURT_IMPOSED.'

        Claim: imposing the CONTESTED plan (round=3) yields
        status=COURT_IMPOSED.
        """
        ctx = setup_case_mediation_round_3_impasse()
        # The plan should be CONTESTED at this point.
        plan = re_get_parenting_plan(
            ctx["case"]["id"], ctx["parenting_plan"]["id"],
        )
        assert plan["status"] == "CONTESTED"
        res = api.impose_parenting_plan(
            ctx["case"]["id"], plan["id"], judge_headers,
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "COURT_IMPOSED"


# ===========================================================================
# Session completion increments mediation_round — PRD §3.4
# ===========================================================================
class TestMediationRoundIncrements:

    def test_completion_increments_round(self, api):
        """PRD §3.4: 'On completion the session transitions from
        IN_PROGRESS to COMPLETED and Case.mediation_round is
        incremented by one.'

        Claim: after one COMPLETED session, Case.mediation_round == 1.
        """
        ctx = setup_case_in_mediation_with_proposed_plan()
        run_one_full_mediation_session(
            ctx["case"]["id"], outcome="IMPASSE",
        )
        case_after = re_get_case(ctx["case"]["id"])
        assert case_after["mediation_round"] == 1, (
            f"expected mediation_round == 1 after one COMPLETED "
            f"session; got {case_after['mediation_round']!r}"
        )
