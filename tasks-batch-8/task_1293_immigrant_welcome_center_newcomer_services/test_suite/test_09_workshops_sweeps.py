"""Workshop sessions: seat allocation boundaries, waitlist promotion, room
buffers, and sweep-driven epoch transitions (PRD §2.4, §3.8)."""

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    assert_workshop_seat_invariant,
    create_workshop_session_payload,
    register_client, create_staff_member, open_case, create_room,
    create_session, enroll_in_session, get_session, get_enrollment,
    setup_session_with_cases, set_clock, run_sweeps, create_appointment,
    confirm_appointment, staff_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]


class TestSeatBoundary:
    def test_enrollment_at_exact_capacity_boundary(self):
        """PRD §3.8: "When `enrolled_count` has reached `capacity`, the newcomer
        is `WAITLISTED` and receives the next per-session `waitlist_position` — a
        monotonic sequence 1, 2, 3, … in creation order; otherwise the enrollment
        is `ENROLLED` and `enrolled_count` increments."

        Design: Difficulty/boundary_precision_check/workshop_seat_boundary_at_exact_capacity
        """
        ctx = setup_session_with_cases(num_cases=3, capacity=2)
        mgr, session, cases = ctx["manager"], ctx["session"], ctx["cases"]
        ea = enroll_in_session(session, cases[0], mgr)   # count 0 -> ENROLLED
        eb = enroll_in_session(session, cases[1], mgr)   # count 1 == capacity-1 -> ENROLLED
        ec = enroll_in_session(session, cases[2], mgr)   # count 2 == capacity -> WAITLISTED
        assert ea["status"] == "ENROLLED"
        assert eb["status"] == "ENROLLED", "the boundary is >=, so capacity-1 still fits"
        assert ec["status"] == "WAITLISTED"
        assert ec["waitlist_position"] == 1
        sess = get_session(session["id"], mgr)
        assert sess["enrolled_count"] == 2
        assert sess["waitlist_count"] == 1
        assert sess["open_seats"] == 0
        assert_workshop_seat_invariant(sess)

    def test_capacity_one_session_boundary(self):
        """PRD §3.8: "When `enrolled_count` has reached `capacity`, the newcomer
        is `WAITLISTED` and receives the next per-session `waitlist_position` — a
        monotonic sequence 1, 2, 3, … in creation order; otherwise the enrollment
        is `ENROLLED` and `enrolled_count` increments."

        Design: Difficulty/boundary_precision_check/workshop_seat_boundary_at_exact_capacity
        """
        ctx = setup_session_with_cases(num_cases=2, capacity=1, room_name="Room C1")
        mgr, session, cases = ctx["manager"], ctx["session"], ctx["cases"]
        e1 = enroll_in_session(session, cases[0], mgr)
        e2 = enroll_in_session(session, cases[1], mgr)
        assert e1["status"] == "ENROLLED"
        assert e2["status"] == "WAITLISTED"
        assert e2["waitlist_position"] == 1
        sess = get_session(session["id"], mgr)
        assert sess["enrolled_count"] == 1 and sess["open_seats"] == 0
        assert_workshop_seat_invariant(sess)


class TestWaitlistPromotion:
    def test_workshop_waitlist_promotion_order(self):
        """PRD §3.8: "Cancelling an `ENROLLED` enrollment frees a seat:
        `enrolled_count` decrements, `open_seats` increments, and exactly one
        waitlisted enrollment is promoted — the one with the lowest
        `waitlist_position` — moving to `ENROLLED` with `waitlist_count`
        decrementing and `enrolled_count` and `open_seats` adjusting accordingly;
        an empty waitlist promotes nobody."

        Design: Corner/state_machines/workshop_waitlist_promotion_order
        """
        ctx = setup_session_with_cases(num_cases=3, capacity=1, room_name="Room P",
                                       starts_at="2026-08-21T10:00:00Z",
                                       ends_at="2026-08-21T11:00:00Z")
        mgr, session, cases = ctx["manager"], ctx["session"], ctx["cases"]
        e1 = enroll_in_session(session, cases[0], mgr)
        e2 = enroll_in_session(session, cases[1], mgr)
        e3 = enroll_in_session(session, cases[2], mgr)
        assert e2["waitlist_position"] == 1 and e3["waitlist_position"] == 2

        validate_success(api_client.cancel_workshop_enrollment(e1["id"], staff_headers(mgr)))
        e2_now = get_enrollment(e2["id"], mgr)
        e3_now = get_enrollment(e3["id"], mgr)
        assert e2_now["status"] == "ENROLLED", "the waitlist head promotes first"
        assert e3_now["status"] == "WAITLISTED"
        sess = get_session(session["id"], mgr)
        assert sess["enrolled_count"] == 1
        assert sess["waitlist_count"] == 1
        assert_workshop_seat_invariant(sess)

    def test_duplicate_workshop_enrollment_same_case_session(self):
        """PRD §3.8: "A case may not hold two live enrollments in one session —
        `ENROLLED` or `WAITLISTED` duplicates fail with
        `ERR_DUPLICATE_ENROLLMENT`."

        Design: Corner/validations/duplicate_workshop_enrollment_same_case_session
        """
        ctx = setup_session_with_cases(num_cases=1, capacity=5, room_name="Room D",
                                       starts_at="2026-08-22T10:00:00Z",
                                       ends_at="2026-08-22T11:00:00Z")
        mgr, session, case = ctx["manager"], ctx["session"], ctx["cases"][0]
        e1 = enroll_in_session(session, case, mgr)
        resp = api_client.create_workshop_enrollment(
            {"session_id": session["id"], "case_id": case["id"]}, staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)

        validate_success(api_client.cancel_workshop_enrollment(e1["id"], staff_headers(mgr)))
        again = enroll_in_session(session, case, mgr)
        assert again["status"] == "ENROLLED", "a cancelled row no longer blocks re-enrollment"


class TestSeatConservation:
    def test_seat_conservation_across_enroll_cancel(self):
        """PRD §2.10: "A workshop session's `open_seats` always equals its
        `capacity` minus its `enrolled_count`, with `waitlist_count` tracking the
        queue alongside."
        PRD §3.8: "Cancelling an `ENROLLED` enrollment frees a seat:
        `enrolled_count` decrements, `open_seats` increments".

        Design: Difficulty/compensating_invariant/workshop_seat_conservation_across_enroll_cancel
        """
        ctx = setup_session_with_cases(num_cases=2, capacity=2, room_name="Room S")
        mgr, session, cases = ctx["manager"], ctx["session"], ctx["cases"]
        enroll_in_session(session, cases[0], mgr)
        eb = enroll_in_session(session, cases[1], mgr)
        mid = get_session(session["id"], mgr)
        assert mid["enrolled_count"] == 2 and mid["open_seats"] == 0
        assert_workshop_seat_invariant(mid)

        validate_success(api_client.cancel_workshop_enrollment(eb["id"], staff_headers(mgr)))
        end = get_session(session["id"], mgr)
        assert end["enrolled_count"] == 1 and end["open_seats"] == 1, \
            "the compensating cancel restores the baseline exactly (no waitlist to mask drift)"
        assert end["enrolled_count"] + end["open_seats"] == end["capacity"]
        assert_workshop_seat_invariant(end)

    def test_seat_conservation_with_promotion_after_cancel(self):
        """PRD §2.10: "A workshop session's `open_seats` always equals its
        `capacity` minus its `enrolled_count`, with `waitlist_count` tracking the
        queue alongside."
        PRD §3.8: "exactly one waitlisted enrollment is promoted — the one with
        the lowest `waitlist_position` — moving to `ENROLLED` with
        `waitlist_count` decrementing and `enrolled_count` and `open_seats`
        adjusting accordingly".

        Design: Difficulty/compensating_invariant/workshop_seat_conservation_across_enroll_cancel
        """
        ctx = setup_session_with_cases(num_cases=3, capacity=2, room_name="Room S2")
        mgr, session, cases = ctx["manager"], ctx["session"], ctx["cases"]
        e1 = enroll_in_session(session, cases[0], mgr)
        enroll_in_session(session, cases[1], mgr)
        enroll_in_session(session, cases[2], mgr)  # WAITLISTED position 1

        validate_success(api_client.cancel_workshop_enrollment(e1["id"], staff_headers(mgr)))
        sess = get_session(session["id"], mgr)
        assert sess["enrolled_count"] == 2, "the promotion immediately refills the freed seat"
        assert sess["waitlist_count"] == 0
        assert sess["open_seats"] == 0
        assert_workshop_seat_invariant(sess)


class TestRoomBufferedConflicts:
    def _setup_room_with_session(self):
        mgr = create_staff_member()
        room = create_room(name="Room R", capacity=25)
        session = create_session(room, mgr, capacity=10,
                                 starts_at="2026-08-10T10:00:00Z",
                                 ends_at="2026-08-10T11:00:00Z", title="Session 1")
        return mgr, room, session

    def test_gap_of_exactly_two_buffers_conflicts_but_more_passes(self):
        """PRD §3.8: "Because the endpoints are inclusive, a back-to-back session
        always conflicts, and even a gap of exactly 30 minutes conflicts; a gap
        strictly greater than 30 minutes is required between sessions in one
        room."

        Design: Difficulty/resource_temporal_overlap/room_buffered_closed_interval_touch
        """
        mgr, room, _s1 = self._setup_room_with_session()
        # 30-minute gap: buffered intervals touch at 11:15 -> conflict.
        resp = api_client.create_workshop_session(
            create_workshop_session_payload(room["id"], title="Session 30-gap", capacity=10,
                                            starts_at="2026-08-10T11:30:00Z",
                                            ends_at="2026-08-10T12:30:00Z"),
            staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)
        # 31-minute gap: strictly greater than twice the buffer -> allowed.
        ok = validate_success(api_client.create_workshop_session(
            create_workshop_session_payload(room["id"], title="Session 31-gap", capacity=10,
                                            starts_at="2026-08-10T11:31:00Z",
                                            ends_at="2026-08-10T12:30:00Z"),
            staff_headers(mgr)), expected_status=201)
        assert ok["status"] == "SCHEDULED"

    def test_back_to_back_session_always_conflicts(self):
        """PRD §3.8: "A new session conflicts when another session in the same
        room, in `SCHEDULED` or `HELD`, has buffered intervals that touch or
        overlap — the new buffered start at or before the existing buffered end,
        and the existing buffered start at or before the new buffered end — and is
        rejected with `ERR_ROOM_TIME_CONFLICT`. Because the endpoints are
        inclusive, a back-to-back session always conflicts".

        Design: Difficulty/resource_temporal_overlap/room_buffered_closed_interval_touch
        """
        mgr, room, _s1 = self._setup_room_with_session()
        resp = api_client.create_workshop_session(
            create_workshop_session_payload(room["id"], title="Back to back", capacity=10,
                                            starts_at="2026-08-10T11:00:00Z",
                                            ends_at="2026-08-10T12:00:00Z"),
            staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)


class TestSweepEpochTransitions:
    def test_sweep_marks_no_show_and_held_then_reconciles(self):
        """PRD §2.4: "One sweep performs five jobs: it expires `SENT` referrals
        whose age has reached their time-to-live, expires `GRANTED` consents whose
        expiry instant has passed, marks `CONFIRMED` appointments whose end has
        passed as `NO_SHOW`, moves `SCHEDULED` workshop sessions whose end has
        passed to `HELD`, and reconciles any `HELD` session whose enrollments are
        fully marked into `RECONCILED`."
        PRD §3.8: "Once every `ENROLLED` enrollment of a `HELD` session has been
        marked one way or the other, the sweep reconciles the session to
        `RECONCILED`."

        Design: Corner/cross_cutting_layers/sweep_marks_no_show_and_held_then_reconciles
        """
        mgr = create_staff_member(full_name="Mgr One")
        mgr2 = create_staff_member(full_name="Mgr Two")
        client = register_client()
        case = open_case(client, mgr)
        appt1 = create_appointment(case, mgr, starts_at="2026-08-05T09:00:00Z",
                                   ends_at="2026-08-05T09:30:00Z")
        confirm_appointment(appt1["id"], mgr)
        appt2 = create_appointment(case, mgr2, kind="ORIENTATION",
                                   starts_at="2026-08-05T09:00:00Z",
                                   ends_at="2026-08-05T09:30:00Z")  # stays REQUESTED
        room = create_room(name="Room N")
        session = create_session(room, mgr, capacity=5,
                                 starts_at="2026-08-05T10:00:00Z",
                                 ends_at="2026-08-05T11:00:00Z")
        wke = enroll_in_session(session, case, mgr)

        set_clock("2026-08-06T00:00:00Z")
        sweep = run_sweeps()
        assert sweep["appointments_marked_no_show"] == 1, "only CONFIRMED appointments are marked"
        assert sweep["sessions_marked_held"] == 1

        a1 = validate_success(api_client.get_appointment(appt1["id"], staff_headers(mgr)))
        a2 = validate_success(api_client.get_appointment(appt2["id"], staff_headers(mgr)))
        assert a1["status"] == "NO_SHOW"
        assert a2["status"] == "REQUESTED", "REQUESTED appointments are untouched by the sweep"
        sess = get_session(session["id"], mgr)
        assert sess["status"] == "HELD"

        marked = validate_success(api_client.mark_attendance(
            wke["id"], {"attended": False}, staff_headers(mgr)))
        assert marked["status"] == "NO_SHOW"
        sweep2 = run_sweeps()
        assert sweep2["sessions_reconciled"] == 1
        sess2 = get_session(session["id"], mgr)
        assert sess2["status"] == "RECONCILED"
