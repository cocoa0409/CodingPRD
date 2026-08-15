"""Care episode lifecycle: exhaustion, exemption, closure, reopening."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    book_session,
    book_session_payload,
    complete_intake_short_term,
    complete_session,
    create_intake,
    create_student,
    get_episode_for_student,
    make_clinical_director_headers,
    make_counselor_headers,
    setup_exhausted_episode,
    setup_open_episode,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]


class TestExhaustionBoundary:

    def _setup_limit_two_episode(self):
        """LOW STUDENT_FEE under a base-4 policy: max(2, 4-2) = 2."""
        counselor, student, episode = setup_open_episode(
            student_number="S1200", full_name="Limit Edge",
            license_id="LIC-12", base_session_limit=4,
            no_show_strike_limit=5, phq9=3, gad7=2)  # 5 -> LOW
        assert episode["session_limit"] == 2
        s_a = book_session(episode["id"], counselor["id"],
                           "2026-08-02T09:00:00Z")
        s_b = book_session(episode["id"], counselor["id"],
                           "2026-08-02T11:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        return counselor, student, episode, s_a, s_b

    def test_episode_exhausts_exactly_at_limit_equality(self):
        """PRD section 3.4: "When the recount reaches the episode's limit and
        no exemption has been granted (`exemption_granted` starts false on
        every episode), the episode exhausts: its `status` moves from `OPEN`
        to `EXHAUSTED`, its `version` increments, the system creates a
        `PENDING` CommunityReferral linked to this episode (the exhaustion
        referral), and every remaining `SCHEDULED` session on the episode is
        cancelled as `CANCELLED_TIMELY` with `cancellation_reason` recorded
        as `EPISODE_EXHAUSTED`."

        The crossing happens AT equality: one completion leaves the episode
        OPEN at consumed 1; the second (consumed == limit) flips it.

        Design: Difficulty/boundary_precision_check/session_limit_exact_crossing_on_consumption
        """
        counselor, student, episode, s_a, s_b = self._setup_limit_two_episode()
        c_headers = make_counselor_headers(counselor["id"])
        complete_session(s_a["id"], counselor["id"])
        mid = validate_success(api_client.get_episode(episode["id"], c_headers))
        assert mid["sessions_consumed"] == 1
        assert mid["status"] == "OPEN", "below the limit the episode stays OPEN"
        complete_session(s_b["id"], counselor["id"])
        end = validate_success(api_client.get_episode(episode["id"], c_headers))
        assert end["sessions_consumed"] == 2
        assert end["status"] == "EXHAUSTED", \
            "reaching the limit exactly (>= semantics) exhausts the episode"

    def test_booking_after_exhaustion_rejected(self):
        """PRD section 3.5: "The episode must be `OPEN` with consumption still
        below its `session_limit` (or carrying an exemption), or the booking
        fails with `ERR_SESSION_LIMIT_REACHED`."

        Design: Difficulty/boundary_precision_check/session_limit_exact_crossing_on_consumption
        """
        counselor, student, episode, s_a, s_b = self._setup_limit_two_episode()
        complete_session(s_a["id"], counselor["id"])
        complete_session(s_b["id"], counselor["id"])
        ep = validate_success(api_client.get_episode(episode["id"], FD))
        resp = api_client.book_session(
            episode["id"],
            book_session_payload(counselor["id"], ep["version"],
                                 starts_at="2026-08-05T09:00:00Z"),
            FD)
        validate_error(resp, ApiErrorId.ERR_SESSION_LIMIT_REACHED)


class TestExemptionInvariant:

    def _setup_exhausted_limit_two(self):
        counselor, student, episode = setup_open_episode(
            student_number="S1800", full_name="Exempt Stud",
            license_id="LIC-18", base_session_limit=4,
            no_show_strike_limit=5, phq9=3, gad7=2)  # LOW -> limit 2
        s_a = book_session(episode["id"], counselor["id"],
                           "2026-08-02T09:00:00Z")
        s_b = book_session(episode["id"], counselor["id"],
                           "2026-08-02T11:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        complete_session(s_a["id"], counselor["id"])
        complete_session(s_b["id"], counselor["id"])
        return counselor, student, episode, s_a

    def test_exemption_preserves_completed_session_history(self):
        """PRD section 3.4: "A `ClinicalDirector` may grant a session-limit
        exemption on an `EXHAUSTED` episode: the episode returns to `OPEN`,
        `exemption_granted` becomes true, and the `session_limit` grows by
        four bonus sessions while `sessions_consumed` is left untouched."

        The conserved quantity is the historical record itself: the two
        COMPLETED sessions still stand and the ledger still reads 2.

        Design: Difficulty/compensating_invariant/episode_exemption_conserves_completed_session_records
        """
        counselor, student, episode, s_a = self._setup_exhausted_limit_two()
        c_headers = make_counselor_headers(counselor["id"])
        pre = validate_success(api_client.get_episode(episode["id"], c_headers))
        assert pre["status"] == "EXHAUSTED"
        assert pre["sessions_consumed"] == 2
        assert pre["session_limit"] == 2
        director = make_clinical_director_headers(counselor["id"])
        validate_success(api_client.grant_episode_exemption(
            episode["id"], director))
        post = validate_success(api_client.get_episode(episode["id"], c_headers))
        assert post["status"] == "OPEN"
        assert post["exemption_granted"] is True
        assert post["session_limit"] == 6, \
            f"2 + 4 bonus sessions must yield 6, got {post['session_limit']}"
        assert post["sessions_consumed"] == 2, \
            "the exemption extends the limit without rewriting history"
        ses = validate_success(api_client.get_session(s_a["id"], c_headers))
        assert ses["status"] == "COMPLETED", \
            "completed session records are conserved"

    def test_exempted_episode_admits_new_booking(self):
        """PRD section 3.4: "the episode returns to `OPEN`,
        `exemption_granted` becomes true, and the `session_limit` grows by
        four bonus sessions while `sessions_consumed` is left untouched."
        PRD section 3.5: "The episode must be `OPEN` with consumption still
        below its `session_limit` (or carrying an exemption), or the booking
        fails with `ERR_SESSION_LIMIT_REACHED`."

        With consumption 2 below the extended limit 6, booking resumes.

        Design: Difficulty/compensating_invariant/episode_exemption_conserves_completed_session_records
        """
        counselor, student, episode, s_a = self._setup_exhausted_limit_two()
        director = make_clinical_director_headers(counselor["id"])
        validate_success(api_client.grant_episode_exemption(
            episode["id"], director))
        booked = book_session(episode["id"], counselor["id"],
                              "2026-08-05T09:00:00Z")
        assert booked["status"] == "SCHEDULED"


class TestClosePrecondition:

    def _setup_episode_with_future_session(self):
        counselor, student, episode = setup_open_episode(
            student_number="S1300", full_name="Close Block",
            license_id="LIC-13", base_session_limit=8)
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-20T09:00:00Z")
        return counselor, student, episode, session

    def test_close_episode_with_scheduled_session_rejected(self):
        """PRD section 3.4: "It is permitted only when no linked session
        remains in `SCHEDULED` or `HELD` status".
        PRD section 2.8: "State eligibility — the target resource must be in a
        state from which the requested transition exists, including
        terminal-state lockdown and repeat triggers (`ERR_INVALID_STATE`)."

        The episode's closure is gated on the state of a different entity — a
        linked Session still in SCHEDULED blocks OPEN -> CLOSED.

        Design: Difficulty/cross_entity_state_dependency/episode_close_blocked_by_scheduled_session
        """
        counselor, student, episode, session = \
            self._setup_episode_with_future_session()
        resp = api_client.close_episode(
            episode["id"], make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_episode_succeeds_after_session_cancelled(self):
        """PRD section 3.4: "Closure is a deliberate act by the episode's
        primary counselor or the `ClinicalDirector`, moving `OPEN` to
        `CLOSED`. It is permitted only when no linked session remains in
        `SCHEDULED` or `HELD` status".

        Design: Difficulty/cross_entity_state_dependency/episode_close_blocked_by_scheduled_session
        """
        counselor, student, episode, session = \
            self._setup_episode_with_future_session()
        validate_success(api_client.cancel_session(
            session["id"], {"cancellation_reason": "client request"}, FD))
        closed = validate_success(api_client.close_episode(
            episode["id"], make_counselor_headers(counselor["id"])))
        assert closed["status"] == "CLOSED"


class TestEpisodeReopen:

    def test_reopen_creates_child_episode_with_prior_link(self):
        """PRD section 3.4: "Reopening completes that assessment in place with
        disposition `SHORT_TERM_CARE`, marks this episode `REOPENED` — a
        terminal marker from which no further transition exists — and creates
        a brand-new episode in `OPEN` status. The new episode's
        `prior_episode_id` points back at the reopened one, its
        `primary_counselor_id` is the referenced assessment's screener, its
        limit is recomputed fresh, and its consumption ledger restarts at
        zero: nothing carries over."
        PRD section 4: "Operations that create a new resource return `201
        Created`; this includes the episode-reopen action, whose response is
        the newly created continuation episode."

        Design: Corner/state_machines/episode_reopen_creates_child_episode_with_prior_link
        """
        counselor, student, episode = setup_open_episode(
            student_number="SS500", full_name="Reopen Stud",
            license_id="LIC-S5", base_session_limit=8,
            no_show_strike_limit=5, weekly_capacity=20)
        c_headers = make_counselor_headers(counselor["id"])
        validate_success(api_client.close_episode(episode["id"], c_headers))
        # The replacement intake must be created strictly after the closure;
        # advance the logical clock so the precondition is unambiguous.
        advance_clock("2026-08-02T00:00:00Z")
        # A fresher, still-PENDING intake for the same student (18 -> MODERATE).
        ia2 = create_intake(student["id"], counselor["id"], phq9=12, gad7=6)
        resp = api_client.reopen_episode(
            episode["id"],
            {"intake_assessment_id": ia2["id"], "academic_term": "2026-FALL"},
            c_headers)
        new_episode = validate_success(resp, expected_status=201)
        assert new_episode["status"] == "OPEN"
        assert new_episode["sessions_consumed"] == 0, \
            "the continuation's ledger restarts at zero"
        assert new_episode["prior_episode_id"] == episode["id"]
        assert new_episode["intake_assessment_id"] == ia2["id"]
        assert new_episode["session_limit"] == 8, \
            "MODERATE/STUDENT_FEE under base 8 recomputes to 8"
        old = validate_success(api_client.get_episode(episode["id"], c_headers))
        assert old["status"] == "REOPENED", \
            "the reopened episode keeps its terminal marker"
        consumed_intake = validate_success(api_client.get_intake_assessment(
            ia2["id"], c_headers))
        assert consumed_intake["disposition"] == "SHORT_TERM_CARE"
