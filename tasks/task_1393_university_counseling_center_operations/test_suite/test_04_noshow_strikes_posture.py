"""No-show determinations, the strike system, and booking posture."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    book_session,
    book_session_payload,
    complete_intake_short_term,
    create_intake,
    create_published_policy,
    create_student,
    excuse_no_show,
    get_episode_for_student,
    make_clinical_director_headers,
    make_counselor_headers,
    make_triage_screener_headers,
    mark_no_show,
    setup_open_episode,
    setup_student_with_strikes,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
CD = TEST_USERS["clinical_director_headers"]


def _student(student_id, counselor_id):
    return validate_success(api_client.get_student(
        student_id, make_clinical_director_headers(counselor_id)))


class TestSuspensionCascade:

    def test_second_strike_at_limit_suspends_student(self):
        """PRD section 3.6: "Under the published policy's
        `no_show_strike_limit`: a recount landing exactly one below the limit
        moves a `CLEAR` student to `RESTRICTED`; a recount at or above the
        limit moves a `CLEAR` or `RESTRICTED` student to `SUSPENDED`; and a
        recount that falls back below one-under-the-limit (after an excuse)
        moves a `RESTRICTED` student back to `CLEAR`."

        With strike limit 2, the second chargeable no-show recomputes the
        count to 2, which is at the limit: posture lands SUSPENDED (link 2 of
        the depth-3 cascade).

        Design: Difficulty/transitive_cascade/noshow_strike_posture_future_session_cascade
        """
        ctx = setup_student_with_strikes(
            strike_limit=2, num_strikes=2,
            future_session_starts=["2026-08-10T10:00:00Z",
                                   "2026-08-11T10:00:00Z"],
            student_number="S700", license_id="LIC-7")
        student = ctx["student"]
        assert student["no_show_strike_count"] == 2
        assert student["booking_posture"] == "SUSPENDED", \
            f"strikes at the limit must suspend, got {student['booking_posture']}"

    def test_suspension_cancels_future_sessions_as_policy_suspension(self):
        """PRD section 3.6: "Suspension carries a cancellation cascade: every
        session the student holds in `SCHEDULED` whose start lies strictly
        after the current logical clock is cancelled as `CANCELLED_TIMELY`
        with `cancellation_reason` recorded as `POLICY_SUSPENSION`; because
        scheduled sessions were never counted in consumption, the cascade
        decrements nothing."

        Link 3 of the cascade: the student's two future SCHEDULED sessions are
        force-cancelled by the posture flip, not by the original request.

        Design: Difficulty/transitive_cascade/noshow_strike_posture_future_session_cascade
        """
        ctx = setup_student_with_strikes(
            strike_limit=2, num_strikes=2,
            future_session_starts=["2026-08-10T10:00:00Z",
                                   "2026-08-11T10:00:00Z"],
            student_number="S700", license_id="LIC-7")
        c_headers = make_counselor_headers(ctx["counselor"]["id"])
        for future in ctx["future_sessions"]:
            current = validate_success(
                api_client.get_session(future["id"], c_headers))
            assert current["status"] == "CANCELLED_TIMELY", \
                f"future session must be cascade-cancelled, got {current['status']}"
            assert current["cancellation_reason"] == "POLICY_SUSPENSION"


class TestRestrictedThreshold:

    def test_restricted_at_limit_minus_one_and_override(self):
        """PRD section 3.6: "a recount landing exactly one below the limit
        moves a `CLEAR` student to `RESTRICTED`".
        PRD section 3.6: "At booking time, a `CLEAR` student books freely; a
        `RESTRICTED` student may book only when the payload carries the
        `director_override` flag; a `SUSPENDED` student never books —
        violations surface as `ERR_BOOKING_SUSPENDED`."

        With strike limit 3, two charged no-shows land exactly at limit-1:
        RESTRICTED. Booking without the flag fails; with it, succeeds.

        Design: Corner/complexity_layers/rate_threshold_restricted_at_limit_minus_one
        """
        ctx = setup_student_with_strikes(
            strike_limit=3, num_strikes=2,
            student_number="L400", license_id="LIC-L4")
        assert ctx["student"]["booking_posture"] == "RESTRICTED", \
            f"strikes == limit-1 must restrict, got {ctx['student']['booking_posture']}"
        assert ctx["student"]["no_show_strike_count"] == 2
        ep_version = ctx["episode"]["version"]
        resp = api_client.book_session(
            ctx["episode"]["id"],
            book_session_payload(ctx["counselor"]["id"], ep_version,
                                 starts_at="2026-08-10T09:00:00Z"),
            FD)
        validate_error(resp, ApiErrorId.ERR_BOOKING_SUSPENDED)
        booked = book_session(ctx["episode"]["id"], ctx["counselor"]["id"],
                              "2026-08-10T09:00:00Z", director_override=True)
        assert booked["status"] == "SCHEDULED"


class TestExcuseCompensation:

    def _charge_one(self):
        counselor, student, episode = setup_open_episode(
            student_number="S1700", funding_model="INSURANCE",
            license_id="LIC-17", no_show_strike_limit=3)
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-02T09:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        charged = mark_no_show(session["id"], counselor["id"],
                               chargeable=True)
        return counselor, student, episode, session, charged

    def test_charged_noshow_bills_consumes_and_strikes(self):
        """PRD section 3.6: "A `chargeable` determination moves the session
        to `NO_SHOW_CHARGED`: the no-show fee of §3.5 is billed, the episode's
        consumption recount runs (charged no-shows consume entitlement, so the
        exhaustion cascade may fire), and a strike lands on the student."
        PRD section 3.5: "a charged no-show bills a flat seventy-five hundred
        cents (seventy-five dollars)" and "Under `INSURANCE` the center bills
        eighty percent of the gross".

        Forward half of the conserved (consumption, strikes) pair: (+1, +1)
        and a 7500 * 0.80 = 6000-cent bill.

        Design: Difficulty/compensating_invariant/noshow_charge_excuse_restores_consumption_and_strikes
        """
        counselor, student, episode, session, charged = self._charge_one()
        assert charged["status"] == "NO_SHOW_CHARGED"
        assert charged["billed_amount_cents"] == 6000, \
            f"INSURANCE share of the 7500-cent no-show fee is 6000, got {charged['billed_amount_cents']}"
        ep = validate_success(api_client.get_episode(
            episode["id"], make_counselor_headers(counselor["id"])))
        assert ep["sessions_consumed"] == 1
        s = _student(student["id"], counselor["id"])
        assert s["no_show_strike_count"] == 1

    def test_excuse_zeroes_billing_and_restores_counters(self):
        """PRD section 3.6: "Excuse is a full compensation: billing zeroes
        out, the episode's consumption recount drops by one, and the strike
        comes off the student's record."

        After the compensating action the (consumption, strikes) pair equals
        its pre-action value (0, 0) exactly — no ledger drift.

        Design: Difficulty/compensating_invariant/noshow_charge_excuse_restores_consumption_and_strikes
        """
        counselor, student, episode, session, charged = self._charge_one()
        excused = excuse_no_show(session["id"], counselor["id"])
        assert excused["status"] == "NO_SHOW_EXCUSED"
        assert excused["billed_amount_cents"] == 0
        ep = validate_success(api_client.get_episode(
            episode["id"], make_counselor_headers(counselor["id"])))
        assert ep["sessions_consumed"] == 0, \
            "excuse must restore consumption to its pre-action value"
        s = _student(student["id"], counselor["id"])
        assert s["no_show_strike_count"] == 0, \
            "excuse must remove the strike from the student's record"


class TestSuspendedLockdownAndReset:

    def test_suspended_lockdown_reset_clears(self):
        """PRD section 3.6: "Only the `ClinicalDirector`'s strike-reset action
        performs the `SUSPENDED` to `CLEAR` transition: it sets the student's
        `strike_reset_anchor` to the current logical clock (so previously
        charged sessions predate the anchor and the recount returns zero),
        restores `booking_posture` to `CLEAR`, and increments the student's
        `version`."

        Three chargeable no-shows under a strike limit of 3 suspend the
        student; only the director's reset restores CLEAR.

        Design: Corner/state_machines/student_suspended_lockdown_no_terminal_escape_except_reset
        """
        ctx = setup_student_with_strikes(
            strike_limit=3, num_strikes=3,
            student_number="SSA00", license_id="LIC-SA")
        assert ctx["student"]["booking_posture"] == "SUSPENDED", \
            "the third strike reaches the limit and suspends (>= semantics)"
        director = make_clinical_director_headers(ctx["counselor"]["id"])
        reset = validate_success(api_client.reset_student_strikes(
            ctx["student"]["id"], director))
        assert reset["booking_posture"] == "CLEAR"
        assert reset["no_show_strike_count"] == 0
        after = _student(ctx["student"]["id"], ctx["counselor"]["id"])
        assert after["booking_posture"] == "CLEAR"
        assert after["no_show_strike_count"] == 0


class TestStrikeTermScoping:

    def test_strikes_scoped_to_current_term(self):
        """PRD section 3.6: "A student's `no_show_strike_count` counts
        charged-no-show sessions across the student's episodes in the current
        term — defined as the `academic_term` of the student's most recently
        created non-terminal episode — whose last mutation happened strictly
        after the student's `strike_reset_anchor`."

        A strike earned in the closed 2026-FALL episode is excluded once the
        student's active care context is the new 2026-SPRING episode.

        Design: Corner/calculations/no_show_strikes_scoped_to_current_term
        """
        from test_helpers import create_counselor
        counselor = create_counselor(license_id="LIC-C4", weekly_capacity=30)
        create_published_policy("2026-FALL", base_session_limit=8,
                                no_show_strike_limit=5)
        create_published_policy("2026-SPRING", base_session_limit=8,
                                no_show_strike_limit=5)
        student = create_student("C400", "Term Stud")
        ia1 = create_intake(student["id"], counselor["id"], phq9=10, gad7=8)
        complete_intake_short_term(ia1["id"], counselor["id"], "2026-FALL")
        ep1 = get_episode_for_student(student["id"], counselor["id"])
        ses = book_session(ep1["id"], counselor["id"], "2026-08-02T09:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        mark_no_show(ses["id"], counselor["id"], chargeable=True)
        mid = _student(student["id"], counselor["id"])
        assert mid["no_show_strike_count"] == 1
        # Close the FALL episode (the charged session is terminal, so the
        # close precondition is met), then open a SPRING episode.
        validate_success(api_client.close_episode(
            ep1["id"], make_counselor_headers(counselor["id"])))
        ia2 = create_intake(student["id"], counselor["id"], phq9=10, gad7=8)
        complete_intake_short_term(ia2["id"], counselor["id"], "2026-SPRING")
        final = _student(student["id"], counselor["id"])
        assert final["no_show_strike_count"] == 0, \
            "prior-term charged no-shows are excluded from the recount"
        assert final["booking_posture"] == "CLEAR"


class TestImmediateConsistency:

    def test_noshow_cascade_visible_in_same_read(self):
        """PRD section 3.6: "A `chargeable` determination moves the session
        to `NO_SHOW_CHARGED`: the no-show fee of §3.5 is billed, the episode's
        consumption recount runs (charged no-shows consume entitlement, so the
        exhaustion cascade may fire), and a strike lands on the student."
        PRD section 3.5: "a charged no-show bills a flat seventy-five hundred
        cents (seventy-five dollars)" and "Under `INSURANCE` the center bills
        eighty percent of the gross".

        Immediately after the 200 from mark-no-show, the very next GETs show
        the session's status and bill, the episode's consumption, and the
        student's strike with no staleness window.

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_read
        """
        counselor, student, episode = setup_open_episode(
            student_number="M100", funding_model="INSURANCE",
            license_id="LIC-M1", no_show_strike_limit=5)
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-02T09:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        validate_success(api_client.mark_session_no_show(
            session["id"], {"chargeable": True},
            make_counselor_headers(counselor["id"])))
        c_headers = make_counselor_headers(counselor["id"])
        ses = validate_success(api_client.get_session(session["id"], c_headers))
        assert ses["status"] == "NO_SHOW_CHARGED"
        assert ses["billed_amount_cents"] == 6000
        ep = validate_success(api_client.get_episode(episode["id"], c_headers))
        assert ep["sessions_consumed"] == 1
        s = _student(student["id"], counselor["id"])
        assert s["no_show_strike_count"] == 1
