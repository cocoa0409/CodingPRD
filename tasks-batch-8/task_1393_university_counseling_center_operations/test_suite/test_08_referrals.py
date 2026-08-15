"""Community referrals: matching, decline/rematch loop, lapse, engagement,
and the acceptance cascade into the care episode."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    decline_and_rematch,
    match_referral,
    setup_exhausted_episode,
    setup_pending_referral_high,
    validate_error,
    validate_success,
)

RC = TEST_USERS["referral_coordinator_headers"]
FD = TEST_USERS["front_desk_headers"]


class TestDeclineRematchLoop:

    def test_first_decline_rematch_returns_to_pending(self):
        """PRD section 3.9: "Decline is not the end of the road: a rematch
        action returns a `DECLINED` referral to `PENDING`, clears the recorded
        `provider_name`, and increments `rematch_count`, which starts at zero
        on every new referral."

        Design: Difficulty/non_linear_state_machine/referral_decline_rematch_loop
        """
        counselor, student, referral = setup_pending_referral_high(
            counselor_license="LIC-6", student_number="S600")
        assert referral["status"] == "PENDING"
        assert referral["rematch_count"] == 0
        matched = match_referral(referral["id"], "ProvA")
        assert matched["status"] == "MATCHED"
        declined = validate_success(
            api_client.decline_referral(referral["id"], RC))
        assert declined["status"] == "DECLINED"
        rematched = validate_success(
            api_client.rematch_referral(referral["id"], RC))
        assert rematched["status"] == "PENDING"
        assert rematched["rematch_count"] == 1
        assert rematched["provider_name"] is None, \
            "rematch clears the recorded provider for re-matching"

    def test_fourth_rematch_rejected_loop_exhausted(self):
        """PRD section 3.9: "The loop is capped — a referral whose
        `rematch_count` has already reached three rejects a further rematch
        with `ERR_REFERRAL_LOOP_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/referral_decline_rematch_loop
        """
        counselor, student, referral = setup_pending_referral_high(
            counselor_license="LIC-6", student_number="S600")
        rid = referral["id"]
        for i, provider in enumerate(("ProvA", "ProvB", "ProvC"), start=1):
            match_referral(rid, provider)
            rematched = decline_and_rematch(rid, provider)
            assert rematched["rematch_count"] == i
            assert rematched["status"] == "PENDING"
        # Loop count is now 3: one more match/decline leaves it DECLINED.
        match_referral(rid, "ProvD")
        validate_success(api_client.decline_referral(rid, RC))
        resp = api_client.rematch_referral(rid, RC)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_LOOP_EXHAUSTED)
        current = validate_success(api_client.get_referral(rid, RC))
        assert current["status"] == "DECLINED", \
            "a rejected rematch leaves the referral DECLINED"
        assert current["rematch_count"] == 3


class TestReferralLapse:

    def test_referral_lapses_after_thirty_days(self):
        """PRD section 3.9: "A referral that sits `PENDING` for thirty days
        without a match lapses automatically — the next clock advance that
        finds the logical clock at or past thirty days from the referral's
        last update moves it to `LAPSED`."

        Design: Corner/state_machines/referral_lapse_after_window
        """
        counselor, student, referral = setup_pending_referral_high(
            counselor_license="LIC-S7", student_number="SS700")
        assert referral["status"] == "PENDING"
        advance_clock("2026-09-15T00:00:00Z")  # 45 days later
        current = validate_success(api_client.get_referral(referral["id"], RC))
        assert current["status"] == "LAPSED"


class TestEngagementWindow:

    def test_engagement_confirmation_window_enforced(self):
        """PRD section 3.9: "Once a referral is `ACCEPTED`, the coordinator
        confirms that the student actually engaged with the community
        provider, but only after fourteen days have elapsed since acceptance
        (measured from the referral's `updated_at`); an earlier confirmation
        is rejected with `ERR_ENGAGEMENT_WINDOW`, and a timely one moves the
        referral to its terminal `COMPLETED`."

        Design: Corner/validations/engagement_confirmation_window_enforced
        """
        counselor, student, referral = setup_pending_referral_high(
            counselor_license="LIC-V5", student_number="V500")
        rid = referral["id"]
        match_referral(rid, "ProvZ")
        validate_success(api_client.accept_referral(rid, RC))
        early = api_client.confirm_referral_engagement(rid, RC)
        validate_error(early, ApiErrorId.ERR_ENGAGEMENT_WINDOW)
        advance_clock("2026-08-16T00:00:00Z")  # 15 days after acceptance
        done = validate_success(api_client.confirm_referral_engagement(rid, RC))
        assert done["status"] == "COMPLETED"


class TestAcceptCascade:

    def test_exhaustion_cascade_creates_referral_and_cancels_sessions(self):
        """PRD section 3.4: "When the recount reaches the episode's limit and
        no exemption has been granted (`exemption_granted` starts false on
        every episode), the episode exhausts: its `status` moves from `OPEN`
        to `EXHAUSTED`, its `version` increments, the system creates a
        `PENDING` CommunityReferral linked to this episode (the exhaustion
        referral), and every remaining `SCHEDULED` session on the episode is
        cancelled as `CANCELLED_TIMELY` with `cancellation_reason` recorded
        as `EPISODE_EXHAUSTED`."

        The fourth completion drives completion -> ledger recount -> EXHAUSTED
        -> referral creation + future-session cancellation end to end.

        Design: Difficulty/transitive_cascade/referral_accept_episode_session_cascade
        """
        ctx = setup_exhausted_episode(student_number="S800",
                                      license_id="LIC-8",
                                      base_session_limit=4)
        episode = ctx["episode"]
        assert episode["status"] == "EXHAUSTED"
        assert episode["sessions_consumed"] == 4
        referral = ctx["referral"]
        assert referral is not None, "the exhaustion referral must be created"
        assert referral["status"] == "PENDING"
        assert referral["episode_id"] == episode["id"]
        future = validate_success(api_client.get_session(
            ctx["future_session"]["id"], FD))
        assert future["status"] == "CANCELLED_TIMELY"
        assert future["cancellation_reason"] == "EPISODE_EXHAUSTED"

    def test_referral_acceptance_transitions_episode_to_referred_out(self):
        """PRD section 3.9: "From `MATCHED`, acceptance moves the referral to
        `ACCEPTED` and fires the care-side cascade: when the referral links an
        episode, that episode transitions to `REFERRED_OUT` — from `OPEN`
        cancelling any remaining `SCHEDULED` sessions with
        `cancellation_reason` recorded as `REFERRED_OUT`, and from either
        `OPEN` or `EXHAUSTED` releasing the primary counselor's caseload
        points."

        Design: Difficulty/transitive_cascade/referral_accept_episode_session_cascade
        """
        ctx = setup_exhausted_episode(student_number="S800",
                                      license_id="LIC-8",
                                      base_session_limit=4)
        rid = ctx["referral"]["id"]
        match_referral(rid, "ProvX")
        accepted = validate_success(api_client.accept_referral(rid, RC))
        assert accepted["status"] == "ACCEPTED"
        episode = validate_success(
            api_client.get_episode(ctx["episode"]["id"], FD))
        assert episode["status"] == "REFERRED_OUT", \
            "acceptance flips the linked EXHAUSTED episode to REFERRED_OUT"
