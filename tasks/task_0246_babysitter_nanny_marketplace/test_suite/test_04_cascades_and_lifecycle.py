"""Transitive cascades from clock-out (pay → earnings → wages → W-2) and from a
FLAGGED adjudication (suspend → cancel bookings → release escrow), plus session
generation, recurring cancellation cascade, and review-publish reputation
recomputation.

Translates difficulty instances under transitive_cascade, plus corner
state_machines side-effect instances and the recurring-cancel cascade.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    set_clock, create_family, create_cleared_available_caregiver,
    create_open_posting, offer_booking, confirm_booking, clear_background_check,
    setup_confirmed_one_time_booking, setup_completed_one_time_session,
    complete_session, sessions_for, first_session,
    submit_review, publish_review,
    make_family_headers, make_caregiver_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestClockoutCascadeDepth3:
    """transitive_cascade / clockout_cascade_pay_earnings_wages_w2_depth3."""

    def test_clockout_posts_pay_earnings_and_wages(self, api):
        """PRD §3.7: "the net of this session accrues to the caregiver's
        `pending_earnings_cents`, the session's `gross_pay_cents` is added to the
        family's `cash_wages_ytd_cents` with the family's `is_w2_obligated` flag
        recomputed".

        One-time booking, 1 child, rate 2000, 5h → gross 10000; net (after FICA
        round(10000*.0765)=765 and fee round(10000*.10)=1000) = 8235 to
        pending_earnings; cash_wages 10000; not obligated.

        Design: Difficulty/transitive_cascade/clockout_cascade_pay_earnings_wages_w2_depth3
        """
        ctx = setup_completed_one_time_session(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000, family_pay_rate_cents=2000, caregiver_tier="BASIC",
            scheduled_start="2026-03-18T08:00:00Z", scheduled_end="2026-03-18T13:00:00Z",
            clock_in="2026-03-18T08:00:00Z", clock_out="2026-03-18T13:00:00Z",
            is_holiday=False, email_suffix="casc")
        assert ctx["session"]["gross_pay_cents"] == 10000, \
            f"expected gross 10000, got {ctx['session']['gross_pay_cents']}"
        caregiver = validate_success(api.get_caregiver(ctx["caregiver"]["id"], ADMIN), 200)
        assert caregiver["pending_earnings_cents"] == 8235, \
            f"expected pending_earnings 8235, got {caregiver['pending_earnings_cents']}"

    def test_clockout_wages_and_w2_flag(self, api):
        """PRD §3.9: "sets `is_w2_obligated` to true when, for any single
        caregiver, that grouped wage total is strictly greater than the federal
        annual wage threshold of 270000 cents."

        cash_wages 10000 (< 270000) → is_w2_obligated false.

        Design: Difficulty/transitive_cascade/clockout_cascade_pay_earnings_wages_w2_depth3
        """
        ctx = setup_completed_one_time_session(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000, family_pay_rate_cents=2000, caregiver_tier="BASIC",
            scheduled_start="2026-03-18T08:00:00Z", scheduled_end="2026-03-18T13:00:00Z",
            clock_in="2026-03-18T08:00:00Z", clock_out="2026-03-18T13:00:00Z",
            is_holiday=False, email_suffix="casc2")
        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family["cash_wages_ytd_cents"] == 10000
        assert family["is_w2_obligated"] is False


class TestFlaggedCascade:
    """transitive_cascade / flagged_check_cascade_suspend_then_cancel_bookings_release_escrow."""

    def _confirmed_with_pending_recheck(self, suffix):
        """STANDARD-cleared caregiver with a CONFIRMED booking (13200 reserved)
        and a fresh STANDARD re-check IN_PROGRESS. Returns (fam, cg, booking, bc2)."""
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=2,
                            required_tier="STANDARD", email=f"flag-{suffix}@x.com")
        cg = create_cleared_available_caregiver(tier="STANDARD", email=f"flagcg-{suffix}@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="STANDARD")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-25T08:00:00Z",
                                scheduled_end="2026-03-25T14:00:00Z")
        booking = confirm_booking(booking["id"], cg["id"])
        bc2 = get_success_data(api_client.create_background_check(
            {"caregiver_id": cg["id"], "requested_tier": "STANDARD"}, ADMIN))
        api_client.start_background_check(bc2["id"], ADMIN)
        return fam, cg, booking, bc2

    def test_flagged_suspends_and_cancels_booking(self, api):
        """PRD §3.2: "A decision of FLAGGED ... moves the check to the terminal
        `FLAGGED` state and triggers the platform's hardest cascade: the
        caregiver's `verification_status` becomes `FLAGGED`, the caregiver's
        `availability_status` is forced to `SUSPENDED`, and every booking of that
        caregiver currently in `OFFERED`, `COUNTERED`, or `CONFIRMED` is moved to
        `CANCELLED`, with each cancelled confirmed booking releasing the family
        escrow it had reserved."

        Design: Difficulty/transitive_cascade/flagged_check_cascade_suspend_then_cancel_bookings_release_escrow
        """
        fam, cg, booking, bc2 = self._confirmed_with_pending_recheck("a")
        get_success_data(api.adjudicate_background_check(
            bc2["id"], {"decision": "FLAGGED"}, ADMIN))
        caregiver = validate_success(api.get_caregiver(cg["id"], ADMIN), 200)
        assert caregiver["availability_status"] == "SUSPENDED"
        after = validate_success(api.get_booking(booking["id"], ADMIN), 200)
        assert after["status"] == "CANCELLED"

    def test_flagged_cascade_releases_family_escrow(self, api):
        """PRD §3.2: "with each cancelled confirmed booking releasing the family
        escrow it had reserved."

        Reserved 13200 returns to 0; available restored to the full 100000.

        Design: Difficulty/transitive_cascade/flagged_check_cascade_suspend_then_cancel_bookings_release_escrow
        """
        fam, cg, booking, bc2 = self._confirmed_with_pending_recheck("b")
        get_success_data(api.adjudicate_background_check(
            bc2["id"], {"decision": "FLAGGED"}, ADMIN))
        family = validate_success(api.get_family(fam["id"], ADMIN), 200)
        assert family["escrow_reserved_cents"] == 0
        assert family["escrow_available_cents"] == 100000


class TestRecurringConfirmGeneratesSessions:
    """Corner state_machines / recurring_confirm_generates_n_sessions."""

    def test_recurring_confirm_creates_three_sessions(self, api):
        """PRD §3.5: "It generates the booking's sessions: for a `ONE_TIME`
        booking exactly one `BookingSession`, and for a `RECURRING` booking one
        session per the `recurrence_count`, spaced at a weekly cadence starting
        from the first window."

        Design: Corner/state_machines/recurring_confirm_generates_n_sessions
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="rec@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="reccg@x.com")
        posting = create_open_posting(fam["id"], care_type="RECURRING",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-21T08:00:00Z",
                                scheduled_end="2026-03-21T12:00:00Z", recurrence_count=3)
        booking = confirm_booking(booking["id"], cg["id"])
        assert booking["status"] == "CONFIRMED"
        sessions = sessions_for(booking["id"])
        assert len(sessions) == 3, f"expected 3 sessions, got {len(sessions)}"


class TestRecurringCancelCascade:
    """Corner cross_cutting / cascade_recurring_cancel_cancels_all_scheduled_sessions."""

    def test_cancel_recurring_cancels_all_scheduled_sessions(self, api):
        """PRD §3.5: "Cancellation moves the booking to `CANCELLED`, releases the
        reservation ... cascades every still-`SCHEDULED` child session to
        `CANCELLED`, and reopens the posting to `OPEN`."

        Design: Corner/cross_cutting_complexity_layers/cascade_recurring_cancel_cancels_all_scheduled_sessions
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="cc@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="cccg@x.com")
        posting = create_open_posting(fam["id"], care_type="RECURRING",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-21T08:00:00Z",
                                scheduled_end="2026-03-21T12:00:00Z", recurrence_count=3)
        booking = confirm_booking(booking["id"], cg["id"])
        cancelled = validate_success(api.cancel_booking(
            booking["id"], make_family_headers(fam["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        family = validate_success(api.get_family(fam["id"], ADMIN), 200)
        assert family["escrow_reserved_cents"] == 0
        cancelled_sessions = sessions_for(booking["id"], status="CANCELLED")
        assert len(cancelled_sessions) == 3, \
            f"expected 3 cancelled sessions, got {len(cancelled_sessions)}"


class TestReviewPublishReputation:
    """Corner state_machines / review_publish_bubbles_caregiver_rating_aggregates."""

    def test_hide_published_review_recomputes_rating(self, api):
        """PRD §3.10: "A `PUBLISHED` review may later be hidden, moving it to
        `HIDDEN` and likewise recomputing the caregiver's `rating_avg` and
        `rating_count` over the remaining published reviews."

        Two published reviews (4 and 5 → avg 4.5, count 2); hiding the 4-star
        recomputes to avg 5.0, count 1.

        Design: Corner/state_machines/review_publish_bubbles_caregiver_rating_aggregates
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=200000, num_children=1,
                            required_tier="BASIC", email="rev@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="revcg@x.com")

        # First completed booking + review value 4.
        p1 = create_open_posting(fam["id"], care_type="ONE_TIME",
                                 family_pay_rate_cents=2000, required_tier="BASIC", title="Ra")
        b1 = offer_booking(fam["id"], cg["id"], p1["id"], agreed_rate_cents=2000,
                           scheduled_start="2026-04-01T08:00:00Z",
                           scheduled_end="2026-04-01T12:00:00Z")
        b1 = confirm_booking(b1["id"], cg["id"])
        s1 = first_session(b1["id"])
        complete_session(s1, cg["id"], clock_in="2026-04-01T08:00:00Z",
                         clock_out="2026-04-01T12:00:00Z")
        rv1 = submit_review(b1["id"], fam["id"], cg["id"], 4)

        # Second completed booking + review value 5.
        p2 = create_open_posting(fam["id"], care_type="ONE_TIME",
                                 family_pay_rate_cents=2000, required_tier="BASIC", title="Rb")
        b2 = offer_booking(fam["id"], cg["id"], p2["id"], agreed_rate_cents=2000,
                           scheduled_start="2026-04-03T08:00:00Z",
                           scheduled_end="2026-04-03T12:00:00Z")
        b2 = confirm_booking(b2["id"], cg["id"])
        s2 = first_session(b2["id"])
        complete_session(s2, cg["id"], clock_in="2026-04-03T08:00:00Z",
                         clock_out="2026-04-03T12:00:00Z")
        rv2 = submit_review(b2["id"], fam["id"], cg["id"], 5)

        publish_review(rv1["id"])
        publish_review(rv2["id"])
        # Hide the 4-star.
        get_success_data(api.moderate_review(rv1["id"], {"decision": "HIDE"}, ADMIN))

        caregiver = validate_success(api.get_caregiver(cg["id"], ADMIN), 200)
        assert caregiver["rating_count"] == 1, \
            f"expected rating_count 1, got {caregiver['rating_count']}"
        assert caregiver["rating_avg"] == pytest.approx(5.0, abs=0.001), \
            f"expected rating_avg 5.0, got {caregiver['rating_avg']}"
