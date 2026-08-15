"""Session booking gates, billing computation, holds, and consumption."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_session,
    book_session,
    book_session_payload,
    complete_intake_short_term,
    complete_session,
    create_counselor,
    create_intake,
    create_open_program,
    create_student,
    enroll_student,
    get_episode_for_student,
    make_counselor_headers,
    make_triage_screener_headers,
    mark_no_show,
    publish_program,
    setup_open_episode,
    validate_error,
    validate_paginated,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
RC = TEST_USERS["referral_coordinator_headers"]


class TestHoldReleaseCycle:

    def test_session_hold_release_cycle(self):
        """PRD section 3.5: "The front desk may place a brief hold pending
        payment confirmation, moving `SCHEDULED` to `HELD`, and may release
        that hold back to `SCHEDULED`; neither move affects consumption or
        billing."
        PRD section 2.4: "The `version` field is a system-managed integer that
        increments by one on every mutation of the resource and underpins
        optimistic concurrency control."

        Design: Corner/endpoints/session_hold_release_cycle
        """
        counselor, student, episode = setup_open_episode(
            student_number="P100", base_session_limit=8)
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-20T09:00:00Z")
        held = validate_success(
            api_client.hold_session(session["id"], FD))
        assert held["status"] == "HELD"
        assert held["version"] == session["version"] + 1
        back = validate_success(
            api_client.release_session_hold(session["id"], FD))
        assert back["status"] == "SCHEDULED"
        assert back["version"] == held["version"] + 1
        ep = validate_success(api_client.get_episode(episode["id"], FD))
        assert ep["sessions_consumed"] == 0, \
            "hold/release must not touch the consumption ledger"


class TestDoubleComplete:

    def test_session_double_complete_rejected(self):
        """PRD section 2.8: "State eligibility — the target resource must be
        in a state from which the requested transition exists, including
        terminal-state lockdown and repeat triggers (`ERR_INVALID_STATE`)."
        PRD section 3.4: "Consumption is tracked by `sessions_consumed`, which
        starts at zero on every newly created episode and is maintained as a
        full recount — not an incremental drift — of the episode's linked
        sessions sitting in `COMPLETED` or `NO_SHOW_CHARGED` status."

        Design: Corner/state_machines/session_double_complete_rejected
        """
        counselor, student, episode = setup_open_episode(
            student_number="SS100", base_session_limit=8,
            no_show_strike_limit=5, license_id="LIC-S1")
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-02T09:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        complete_session(session["id"], counselor["id"])
        resp = api_client.complete_session(
            session["id"], make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        ep = validate_success(api_client.get_episode(episode["id"], FD))
        assert ep["sessions_consumed"] == 1, \
            "a rejected repeat completion must not double-count consumption"


class TestTemporalGates:

    def test_booking_in_past_rejected(self):
        """PRD section 3.5: "The start must lie strictly in the future
        relative to the logical clock, or the booking is rejected with
        `ERR_TEMPORAL_INVALID`."

        Design: Corner/validations/booking_future_dated_enforced
        """
        counselor, student, episode = setup_open_episode(
            student_number="V100", license_id="LIC-V1")
        advance_clock("2026-08-10T00:00:00Z")
        ep = validate_success(api_client.get_episode(episode["id"], FD))
        resp = api_client.book_session(
            episode["id"],
            book_session_payload(counselor["id"], ep["version"],
                                 starts_at="2026-08-05T09:00:00Z"),
            FD)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID)

    def test_complete_before_start_rejected(self):
        """PRD section 3.5: "Delivery is recorded by the session's own
        counselor (or the director) marking it complete, which is permitted
        once the logical clock has reached the session's start — completing
        before the start is rejected with `ERR_TEMPORAL_INVALID`."

        Design: Corner/validations/complete_before_start_rejected
        """
        counselor, student, episode = setup_open_episode(
            student_number="V300", license_id="LIC-V3")
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-20T09:00:00Z")
        resp = api_client.complete_session(
            session["id"], make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID)


class TestEpisodeBookingOcc:

    def test_stale_episode_version_rejected(self):
        """PRD section 2.7: "Between a client's read of an episode and its
        booking request, another session completion may have advanced the
        episode's counter and version, leaving the client's view of remaining
        capacity stale; such a booking is rejected with `ERR_STALE_VERSION`."
        PRD section 3.5: "a successful booking itself increments the episode's
        `version` by one, so back-to-back bookings must re-read the episode
        between writes."

        Design: Corner/errors/error_stale_version_on_episode_booking
        """
        counselor, student, episode = setup_open_episode(
            student_number="R200", license_id="LIC-R2")
        stale_version = episode["version"]
        first = book_session(episode["id"], counselor["id"],
                             "2026-08-20T09:00:00Z")
        assert_session(first)
        # The successful booking bumped the episode version; the client's
        # captured version is now stale.
        resp = api_client.book_session(
            episode["id"],
            book_session_payload(counselor["id"], stale_version,
                                 starts_at="2026-08-21T09:00:00Z"),
            FD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        sessions, _m = validate_paginated(api_client.list_sessions(
            make_counselor_headers(counselor["id"]),
            params={"episode_id": episode["id"]}))
        assert len(sessions) == 1, "the stale booking must not create a session"


class TestCounselorSessionOverlap:

    def test_overlapping_session_booking_rejected(self):
        """PRD section 3.5: "The new session's interval, from `starts_at`
        through `starts_at` plus its duration, must not overlap any other
        pending session of the same counselor, or `ERR_SCHEDULE_CONFLICT`
        results".

        Existing 09:00-10:00; new 09:59-10:59 shares the minute 09:59-10:00.

        Design: Difficulty/resource_temporal_overlap/counselor_session_interval_overlap_half_open
        """
        counselor, student, episode = setup_open_episode(
            student_number="S1500", license_id="LIC-15",
            no_show_strike_limit=5)
        book_session(episode["id"], counselor["id"], "2026-08-20T09:00:00Z")
        ep = validate_success(api_client.get_episode(episode["id"], FD))
        resp = api_client.book_session(
            episode["id"],
            book_session_payload(counselor["id"], ep["version"],
                                 starts_at="2026-08-20T09:59:00Z"),
            FD)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)

    def test_adjacent_session_booking_succeeds(self):
        """PRD section 3.5: "The new session's interval, from `starts_at`
        through `starts_at` plus its duration, must not overlap any other
        pending session of the same counselor, or `ERR_SCHEDULE_CONFLICT`
        results".

        A session beginning exactly when the 09:00-10:00 session ends shares
        no span of time with it, so no overlap exists.

        Design: Difficulty/resource_temporal_overlap/counselor_session_interval_overlap_half_open
        """
        counselor, student, episode = setup_open_episode(
            student_number="S1500", license_id="LIC-15",
            no_show_strike_limit=5)
        book_session(episode["id"], counselor["id"], "2026-08-20T09:00:00Z")
        adjacent = book_session(episode["id"], counselor["id"],
                                "2026-08-20T10:00:00Z")
        assert_session(adjacent)
        assert adjacent["status"] == "SCHEDULED"


class TestBilling:

    def test_billing_student_fee_zero_insurance_share(self):
        """PRD section 3.5: "Sessions funded entirely by student fees
        (`STUDENT_FEE`) are never billed — `billed_amount_cents` stays zero."
        PRD section 3.5: "a completed session bills two hundred fifty cents
        per minute of its `duration_minutes` (two dollars and fifty cents per
        minute, so a sixty-minute session grosses fifteen thousand cents)" and
        "Under `INSURANCE` the center bills eighty percent of the gross".

        Design: Corner/calculations/billing_student_fee_zero_insurance_share
        """
        counselor, s_fee, ep_fee = setup_open_episode(
            student_number="C100", funding_model="STUDENT_FEE",
            license_id="LIC-C1", no_show_strike_limit=5)
        s_ins = create_student("C101", "Ins Stud", funding_model="INSURANCE")
        ia_ins = create_intake(s_ins["id"], counselor["id"], phq9=10, gad7=8)
        complete_intake_short_term(ia_ins["id"], counselor["id"], "2026-FALL")
        ep_ins = get_episode_for_student(s_ins["id"], counselor["id"])
        ses_fee = book_session(ep_fee["id"], counselor["id"],
                               "2026-08-02T09:00:00Z")
        ses_ins = book_session(ep_ins["id"], counselor["id"],
                               "2026-08-02T11:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        done_fee = complete_session(ses_fee["id"], counselor["id"])
        done_ins = complete_session(ses_ins["id"], counselor["id"])
        assert done_fee["billed_amount_cents"] == 0, \
            "STUDENT_FEE sessions are never billed"
        assert done_ins["billed_amount_cents"] == 12000, \
            f"250*60*0.80 must bill 12000 cents, got {done_ins['billed_amount_cents']}"

    def test_billing_late_cancel_vs_timely_classification(self):
        """PRD section 3.5: "When the hours remaining until the session start
        are at least `late_cancel_window_hours`, the cancellation is timely:
        the session becomes `CANCELLED_TIMELY`, the supplied
        `cancellation_reason` is recorded, and nothing is billed or consumed.
        When less time remains, the session becomes `CANCELLED_LATE` and a
        late-cancel fee is billed."
        PRD section 3.5: "a late cancellation bills a flat five thousand cents
        (fifty dollars)" and "Under `SPLIT` it bills fifty percent."

        Design: Corner/calculations/billing_late_cancel_vs_timely_classification
        """
        counselor, student, episode = setup_open_episode(
            student_number="C200", funding_model="SPLIT",
            license_id="LIC-C2", no_show_strike_limit=5,
            late_cancel_window_hours=24)
        # Clock is 2026-08-01T00:00:00Z: 30h out is timely, 10h out is late.
        timely = book_session(episode["id"], counselor["id"],
                              "2026-08-02T06:00:00Z")
        late = book_session(episode["id"], counselor["id"],
                            "2026-08-01T10:00:00Z")
        t = validate_success(api_client.cancel_session(
            timely["id"], {"cancellation_reason": "plans changed"}, FD))
        l = validate_success(api_client.cancel_session(
            late["id"], {"cancellation_reason": "slept in"}, FD))
        assert t["status"] == "CANCELLED_TIMELY"
        assert t["billed_amount_cents"] == 0
        assert t["cancellation_reason"] == "plans changed"
        assert l["status"] == "CANCELLED_LATE"
        assert l["billed_amount_cents"] == 2500, \
            f"5000 * 0.50 SPLIT share must bill 2500, got {l['billed_amount_cents']}"
        ep = validate_success(api_client.get_episode(episode["id"], FD))
        assert ep["sessions_consumed"] == 0, \
            "cancelled sessions never count toward consumption"


class TestDualFailurePrecedence:

    def _setup_suspended_with_overlap_armed(self):
        """Student S9 driven to SUSPENDED (2 strikes under limit 2) while a
        second student S9b holds a SCHEDULED session at 2026-08-05T09:00 with
        the same counselor (the per-student suspension cascade cannot touch
        the other student's session)."""
        counselor, s9, ep9 = setup_open_episode(
            student_number="S900", full_name="Dual Fail",
            license_id="LIC-9", weekly_capacity=30,
            base_session_limit=4, no_show_strike_limit=2)
        s9b = create_student("S901", "Other Stud")
        ia9b = create_intake(s9b["id"], counselor["id"], phq9=10, gad7=8)
        complete_intake_short_term(ia9b["id"], counselor["id"], "2026-FALL")
        ep9b = get_episode_for_student(s9b["id"], counselor["id"])
        s9_a = book_session(ep9["id"], counselor["id"], "2026-08-02T09:00:00Z")
        s9_b = book_session(ep9["id"], counselor["id"], "2026-08-02T11:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        mark_no_show(s9_a["id"], counselor["id"], chargeable=True)
        mark_no_show(s9_b["id"], counselor["id"], chargeable=True)
        # Arm the overlap: a future session belonging to the OTHER student.
        book_session(ep9b["id"], counselor["id"], "2026-08-05T09:00:00Z")
        ep9 = validate_success(api_client.get_episode(ep9["id"], FD))
        return counselor, s9, ep9

    def test_overlap_and_suspended_dual_failure_reports_schedule_conflict(self):
        """PRD section 2.8: "Domain gates, evaluated in this exact order: the
        clinical-safety gate (`ERR_RISK_BAND_VIOLATION`); the confidentiality
        wall (`ERR_CONFIDENTIALITY_VIOLATION`); uniqueness (`ERR_DUPLICATE`);
        schedule overlap (`ERR_SCHEDULE_CONFLICT`); single-room serialization
        (`ERR_ROOM_OCCUPIED`); the booking-posture gate
        (`ERR_BOOKING_SUSPENDED`); the session-limit gate
        (`ERR_SESSION_LIMIT_REACHED`); counselor capacity
        (`ERR_COUNSELOR_OVER_CAPACITY`); group-program openness
        (`ERR_PROGRAM_NOT_OPEN`); temporal validity (`ERR_TEMPORAL_INVALID`);
        optimistic concurrency (`ERR_STALE_VERSION`); and finally
        policy-lifecycle conflicts (`ERR_POLICY_CONFLICT`)."

        A booking that both overlaps another pending session of the counselor
        AND targets a SUSPENDED student must surface ERR_SCHEDULE_CONFLICT —
        schedule overlap is evaluated before the booking-posture gate.

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_session_booking
        """
        counselor, s9, ep9 = self._setup_suspended_with_overlap_armed()
        resp = api_client.book_session(
            ep9["id"],
            book_session_payload(counselor["id"], ep9["version"],
                                 starts_at="2026-08-05T09:30:00Z"),
            FD)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)
        after = validate_success(api_client.get_episode(ep9["id"], FD))
        assert after["version"] == ep9["version"], \
            "a rejected booking must not mutate the episode"
        sessions, _m = validate_paginated(api_client.list_sessions(
            make_counselor_headers(counselor["id"]),
            params={"episode_id": ep9["id"]}))
        assert all(s["starts_at"] != "2026-08-05T09:30:00Z"
                   for s in sessions), "no session may be created"

    def test_suspended_booking_without_overlap_reports_booking_suspended(self):
        """PRD section 3.6: "At booking time, a `CLEAR` student books freely;
        a `RESTRICTED` student may book only when the payload carries the
        `director_override` flag; a `SUSPENDED` student never books —
        violations surface as `ERR_BOOKING_SUSPENDED`."

        The companion probe at a non-overlapping hour isolates the fiscal
        gate, proving it was armed in the dual-failure scenario.

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_session_booking
        """
        counselor, s9, ep9 = self._setup_suspended_with_overlap_armed()
        resp = api_client.book_session(
            ep9["id"],
            book_session_payload(counselor["id"], ep9["version"],
                                 starts_at="2026-08-05T11:00:00Z"),
            FD)
        validate_error(resp, ApiErrorId.ERR_BOOKING_SUSPENDED)


class TestReverseFkListings:

    def test_fk_reverse_reachability_filtered_lists(self):
        """PRD section 3.4: "Episode listings can be filtered by
        `student_id`, `primary_counselor_id`, `status`, `academic_term`,
        `prior_episode_id`, and `intake_assessment_id`."
        PRD section 3.5: "Session listings can be filtered by `episode_id`,
        `counselor_id`, and `status`."
        PRD section 3.8: "Enrollment listings filter by `program_id`,
        `student_id`, and `status`."
        PRD section 3.9: "the referral list filters by `student_id`,
        `episode_id`, and `status`."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        counselor, student, episode = setup_open_episode(
            student_number="P200", license_id="LIC-P2",
            no_show_strike_limit=5)
        book_session(episode["id"], counselor["id"], "2026-08-20T09:00:00Z")
        # HIGH-band second student -> PENDING referral, no episode.
        high = create_student("P201", "FK High")
        ia_high = create_intake(high["id"], counselor["id"], phq9=20, gad7=20)
        validate_success(api_client.complete_intake_assessment(
            ia_high["id"], {},
            make_triage_screener_headers(counselor["id"])))
        program = create_open_program(counselor["id"], title="FK Group",
                                      starts_at="2026-09-01T17:00:00Z",
                                      weeks=4, risk_band_ceiling="MODERATE")
        enroll_student(program["id"], student["id"])

        c_headers = make_counselor_headers(counselor["id"])
        episodes, _m = validate_paginated(api_client.list_episodes(
            c_headers, params={"student_id": student["id"]}))
        assert len(episodes) == 1 and episodes[0]["id"] == episode["id"]
        sessions, _m = validate_paginated(api_client.list_sessions(
            c_headers, params={"episode_id": episode["id"]}))
        assert len(sessions) == 1
        enrollments, _m = validate_paginated(api_client.list_group_enrollments(
            FD, params={"program_id": program["id"]}))
        assert len(enrollments) == 1
        assert enrollments[0]["status"] == "ENROLLED"
        referrals, _m = validate_paginated(api_client.list_referrals(
            RC, params={"student_id": high["id"]}))
        assert len(referrals) == 1
        assert referrals[0]["status"] == "PENDING"
