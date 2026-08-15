"""Cross-entity cascades and denormalized-counter conservation (PRD sections
2.9, 3.2, 3.3, 3.9)."""
from test_helpers import (
    advance_to_shortlisted,
    create_session,
    create_submission_payload,
    create_talent,
    make_agent_headers,
    place_hold,
    propose_appointment,
    set_clock,
    setup_confirmed_booking,
    setup_shortlisted_submission,
    setup_submission,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _cancel_confirmed_booking_ctx(api):
    """CONFIRMED booking (engagement 2026-08-20..22, guarantee 800000); clock
    parked at 2026-08-13 so cancellation lands 7 days out (25% tier)."""
    ctx = setup_confirmed_booking(
        role_overrides={
            "engagement_start": "2026-08-20T00:00:00Z",
            "engagement_end": "2026-08-22T00:00:00Z",
        },
        accept_overrides={
            "engagement_start": "2026-08-20T00:00:00Z",
            "engagement_end": "2026-08-22T00:00:00Z",
            "proration_mode": "CALENDAR_SPAN",
        },
    )
    set_clock("2026-08-13T00:00:00Z")
    return ctx


class TestBookingCancelCascade:
    def test_cancel_confirmed_booking_unwinds_memo_submission_role(self, api):
        """PRD section 3.9: "Cancelling a `CONFIRMED` booking is the full unwind.
        The server stamps `cancelled_at`, computes the penalty onto the memo
        (below), recomputes the talent's `union_engagement_count_365d` —
        decrementing it if this booking's engagement fell inside the rolling
        window — and transitions any `PENDING` Taft-Hartley report referencing
        this booking to `WAIVED`. The submission returns `BOOKED → NOT_BOOKED`,
        the role reopens `CAST → OPEN`, and the `version` of the booking, the
        memo, the submission, and the role each increment by one."

        Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth3
        """
        ctx = _cancel_confirmed_booking_ctx(api)
        resp = api.cancel_booking(ctx["booking"]["id"], {"cancellation_reason": "PRODUCTION_CANCELLED"}, COORDINATOR)
        booking = validate_success(resp)
        assert booking["status"] == "CANCELLED"
        memo = validate_success(api.get_deal_memo(ctx["memo"]["id"], DIRECTOR))
        assert memo["cancellation_penalty_cents"] == 200_000, "depth-1: penalty computed onto the memo (7 days out, 25%)"
        submission = validate_success(api.get_submission(ctx["submission"]["id"], DIRECTOR))
        assert submission["status"] == "NOT_BOOKED", "depth-2: booking cancellation drives the submission to NOT_BOOKED"
        role = validate_success(api.get_role(ctx["role"]["id"], DIRECTOR))
        assert role["status"] == "OPEN", "depth-3: the submission's unwind reopens the role CAST -> OPEN"

    def test_cancel_confirmed_booking_increments_all_four_versions(self, api):
        """PRD section 3.9: "The submission returns `BOOKED → NOT_BOOKED`, the
        role reopens `CAST → OPEN`, and the `version` of the booking, the memo,
        the submission, and the role each increment by one."
        PRD section 2.9: "every mutated entity's `version` increments by one and
        its `updated_at` refreshes, whether the mutation came from an explicit
        client call, a cascade, or a clock sweep."

        Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth3
        """
        ctx = _cancel_confirmed_booking_ctx(api)
        before = {
            "booking": validate_success(api.get_booking(ctx["booking"]["id"], COORDINATOR))["version"],
            "memo": validate_success(api.get_deal_memo(ctx["memo"]["id"], DIRECTOR))["version"],
            "submission": validate_success(api.get_submission(ctx["submission"]["id"], DIRECTOR))["version"],
            "role": validate_success(api.get_role(ctx["role"]["id"], DIRECTOR))["version"],
        }
        validate_success(api.cancel_booking(ctx["booking"]["id"], {"cancellation_reason": "PRODUCTION_CANCELLED"}, COORDINATOR))
        after = {
            "booking": validate_success(api.get_booking(ctx["booking"]["id"], COORDINATOR))["version"],
            "memo": validate_success(api.get_deal_memo(ctx["memo"]["id"], DIRECTOR))["version"],
            "submission": validate_success(api.get_submission(ctx["submission"]["id"], DIRECTOR))["version"],
            "role": validate_success(api.get_role(ctx["role"]["id"], DIRECTOR))["version"],
        }
        for name in before:
            assert after[name] == before[name] + 1, f"{name}.version must increment by exactly one on the cancel unwind"


class TestBreakdownCancelCascade:
    def test_cancel_released_breakdown_withdraws_submission_and_releases_hold(self, api):
        """PRD section 3.2: "When the cancel does proceed, it fires a four-part
        cascade: every child submission not already `WITHDRAWN`, `REJECTED`, or
        `NOT_BOOKED` transitions to `WITHDRAWN`; every availability hold linked to
        those submissions still `ACTIVE` transitions to `RELEASED`; every audition
        session of the breakdown still `SCHEDULED` transitions to `CANCELLED`,
        taking its `PROPOSED` and `CONFIRMED` appointments down to `CANCELLED`
        with it; and the production's `active_breakdown_count` is recomputed
        downward by one, with the breakdown's and production's `version` each
        incrementing."

        Design: Difficulty/transitive_cascade/breakdown_cancel_cascade_depth2
        """
        ctx = setup_submission()
        advance_to_shortlisted(ctx["submission"]["id"])
        hold = place_hold(ctx["submission"]["id"], ctx["talent"]["id"], hold_kind="AVAIL")
        resp = api.cancel_breakdown(ctx["breakdown"]["id"], DIRECTOR)
        breakdown = validate_success(resp)
        assert breakdown["status"] == "CANCELLED"
        submission = validate_success(api.get_submission(ctx["submission"]["id"], DIRECTOR))
        assert submission["status"] == "WITHDRAWN", "depth-1: breakdown cancel withdraws the active submission"
        hold_after = validate_success(api.get_hold(hold["id"], DIRECTOR))
        assert hold_after["status"] == "RELEASED", "depth-2: the withdrawal releases the submission's ACTIVE hold"

    def test_cancel_released_breakdown_cancels_sessions_and_appointments(self, api):
        """PRD section 3.2: "When the cancel does proceed, it fires a four-part
        cascade: every child submission not already `WITHDRAWN`, `REJECTED`, or
        `NOT_BOOKED` transitions to `WITHDRAWN`; every availability hold linked to
        those submissions still `ACTIVE` transitions to `RELEASED`; every audition
        session of the breakdown still `SCHEDULED` transitions to `CANCELLED`,
        taking its `PROPOSED` and `CONFIRMED` appointments down to `CANCELLED`
        with it; and the production's `active_breakdown_count` is recomputed
        downward by one, with the breakdown's and production's `version` each
        incrementing."

        Design: Difficulty/transitive_cascade/breakdown_cancel_cascade_depth2
        """
        ctx = setup_shortlisted_submission()
        session = create_session(ctx["breakdown"]["id"])
        appointment = propose_appointment(session["id"], ctx["submission"]["id"])
        pre_prod = validate_success(api.get_production(ctx["production"]["id"], DIRECTOR))
        assert pre_prod["active_breakdown_count"] == 1
        validate_success(api.cancel_breakdown(ctx["breakdown"]["id"], DIRECTOR))
        session_after = validate_success(api.get_session(session["id"], DIRECTOR))
        assert session_after["status"] == "CANCELLED", "SCHEDULED session cascades to CANCELLED"
        appt_after = validate_success(api.get_appointment(appointment["id"], DIRECTOR))
        assert appt_after["status"] == "CANCELLED", "the session takes its PROPOSED appointment down with it"
        submission = validate_success(api.get_submission(ctx["submission"]["id"], DIRECTOR))
        assert submission["status"] == "WITHDRAWN"
        prod_after = validate_success(api.get_production(ctx["production"]["id"], DIRECTOR))
        assert prod_after["active_breakdown_count"] == 0, "active_breakdown_count recomputed downward by one"


class TestSubmissionCountInvariant:
    def test_add_then_withdraw_restores_count(self, api):
        """PRD section 2.9: "A breakdown's `submission_count` is the count of its
        submissions in **any** status except `WITHDRAWN`."
        PRD section 3.3: "Withdrawal lands in `WITHDRAWN`, releases every `ACTIVE`
        hold on the submission, recomputes the breakdown's `submission_count`
        downward by one, and increments both the submission's and the breakdown's
        `version`."

        Design: Difficulty/compensating_invariant/submission_count_add_withdraw_invariant
        """
        ctx = setup_submission(agent=True)
        agent_id = ctx["agent"]["id"]
        breakdown_id = ctx["breakdown"]["id"]
        before = validate_success(api.get_breakdown(breakdown_id, DIRECTOR))
        assert before["submission_count"] == 1
        second_talent = create_talent(agent_id=agent_id)
        payload = create_submission_payload(second_talent["id"], before["version"], agent_id=agent_id)
        second = validate_success(api.create_submission(breakdown_id, payload, make_agent_headers(agent_id)), expected_status=201)
        after_add = validate_success(api.get_breakdown(breakdown_id, DIRECTOR))
        assert after_add["submission_count"] == 2, "forward action increments the counter by one"
        validate_success(api.withdraw_submission(second["id"], make_agent_headers(agent_id)))
        after_withdraw = validate_success(api.get_breakdown(breakdown_id, DIRECTOR))
        assert after_withdraw["submission_count"] == 1, (
            "the compensating withdrawal returns submission_count to its exact prior value"
        )

    def test_auto_rejected_duplicate_counts_until_withdrawn(self, api):
        """PRD section 3.3: "Because a duplicate persists as a real submission in
        `REJECTED`, it counts toward the breakdown's `submission_count` until
        withdrawn, per the counter rule in §2.9."
        PRD section 2.9: "Auto-rejected duplicates (submissions persisted as
        `REJECTED` with `duplicate_of_id` set) therefore **do** count until they
        are withdrawn; only withdrawal removes a submission from the count."

        Design: Difficulty/compensating_invariant/submission_count_add_withdraw_invariant
        """
        ctx = setup_submission()
        breakdown_id = ctx["breakdown"]["id"]
        talent_id = ctx["talent"]["id"]
        version = validate_success(api.get_breakdown(breakdown_id, DIRECTOR))["version"]
        payload = create_submission_payload(talent_id, version)
        duplicate = validate_success(api.create_submission(breakdown_id, payload, ASSOCIATE), expected_status=201)
        assert duplicate["status"] == "REJECTED"
        after_dup = validate_success(api.get_breakdown(breakdown_id, DIRECTOR))
        assert after_dup["submission_count"] == 2, "REJECTED duplicates still count; only WITHDRAWN is excluded"
