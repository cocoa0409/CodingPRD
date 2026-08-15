"""Sessions, attendance weights, and the milestone threshold state machine."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_teacher_headers,
    setup_open_year_with_section, setup_section_with_attendance,
    setup_family_with_enrollment, create_family, create_student,
    enroll_student_fresh, create_hired_teacher, create_sessions,
    hold_sessions, post_marks, get_milestone_for_student, get_section,
    fulfill_commitment, get_commitment_for_family,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSessionGuards:
    def test_unstaffed_section_session_rejected(self):
        """PRD §3.4: "Scheduling is refused when the section is `UNSTAFFED`
        (`ERR_SECTION_UNSTAFFED`)". PRD §3.2: "`STAFFED` exactly when `teacher_id`
        is set and that teacher's status is `HIRED`, otherwise `UNSTAFFED`."

        Design: Corner/validations/unstaffed_section_session_rejected
        """
        ctx = setup_open_year_with_section()
        year = ctx["year"]
        # Section with no teacher_id -> UNSTAFFED by derivation.
        from test_helpers import create_section_payload
        payload = create_section_payload(room="RU")
        unstaffed = get_success_data(
            api_client.create_section(year["id"], payload, ADMIN), 201
        )
        assert unstaffed["staffing_status"] == "UNSTAFFED"
        resp = api_client.create_session(
            unstaffed["id"], {"session_date": "2026-09-13"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_SECTION_UNSTAFFED)

    def test_session_on_closure_date_rejected(self):
        """PRD §3.4: "or when the date falls inside any of the year's closures
        (`ERR_SESSION_DATE_CLOSED`)".

        Design: Corner/validations/session_on_closure_date_rejected
        """
        ctx = setup_open_year_with_section()
        year, section = ctx["year"], ctx["section"]
        get_success_data(
            api_client.create_closure(
                year["id"],
                {"start_date": "2026-09-13", "end_date": "2026-09-13", "reason": "Holiday"},
                ADMIN,
            ),
            201,
        )
        resp = api_client.create_session(
            section["id"], {"session_date": "2026-09-13"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_DATE_CLOSED)

    def test_session_out_of_year_rejected(self):
        """PRD §3.4: "when the date falls outside the year's inclusive
        `start_date`-to-`end_date` window (`ERR_SESSION_DATE_OUT_OF_YEAR`)".

        Design: Corner/validations/session_out_of_year_rejected
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        resp = api_client.create_session(
            section["id"], {"session_date": "2027-07-04"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_DATE_OUT_OF_YEAR)

    def test_future_session_hold_rejected(self):
        """PRD §3.4: "the `session_date` is on or before the logical clock's
        current date — holding a future-dated session fails with
        `ERR_SESSION_DATE_IN_FUTURE`."

        Design: Corner/validations/future_session_hold_rejected
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        session = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-13"}, ADMIN),
            201,
        )
        # Clock untouched at the 2026-08-01 startup default; 2026-09-13 is future.
        resp = api_client.hold_session(session["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SESSION_DATE_IN_FUTURE)


class TestHoldSideEffects:
    def test_first_hold_activates_registered_enrollments(self):
        """PRD §3.4: "When the first session of a section is held, every
        `REGISTERED` enrollment of that section advances to `ACTIVE`".
        PRD §3.4: "The transition `SCHEDULED` → `HELD`".

        Design: Corner/state_machines/session_hold_activates_registered_enrollments
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        bundle = setup_family_with_enrollment(section, 1)
        enr = bundle["enrollments"][0]
        assert enr["status"] == "REGISTERED"
        session = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-13"}, ADMIN),
            201,
        )
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-09-13T12:00:00Z"}, ADMIN)
        )
        held = get_success_data(api_client.hold_session(session["id"], ADMIN))
        assert held["status"] == "HELD"
        enr_now = get_success_data(api_client.get_enrollment(enr["id"], ADMIN))
        assert enr_now["status"] == "ACTIVE"


class TestAttendanceWeights:
    def test_excused_counts_half(self):
        """PRD §3.4: "Each student's mark in an eligible session contributes a
        weight: `PRESENT` counts as 1.0, `EXCUSED` as 0.5, `ABSENT` as 0.0" and "The
        **current** percentage is the sum of weights divided by the number of
        eligible sessions, multiplied by 100 and rounded half up to two decimal
        places".

        Design: Corner/calculations/attendance_excused_half_weight
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "EXCUSED"], clock_to="2026-09-27T12:00:00Z"
        )
        milestone = ctx["milestone"]
        evaluated = get_success_data(api_client.evaluate_milestone(milestone["id"], ADMIN))
        # (1.0 + 1.0 + 0.5) / 3 = 0.8333... -> 83.33
        assert evaluated["current_attendance_pct"] == pytest.approx(83.33, abs=0.001)
        assert evaluated["status"] == "ELIGIBLE"  # 83.33 >= 80

    def test_attendance_unenrolled_student_rejected(self):
        """PRD §3.4: "Every entry must reference a student holding a `REGISTERED`
        or `ACTIVE` enrollment in the session's section, or the whole post fails
        with `ERR_STUDENT_NOT_ENROLLED`."

        Design: Corner/validations/attendance_unenrolled_student_rejected
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        session = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-13"}, ADMIN),
            201,
        )
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-09-13T12:00:00Z"}, ADMIN)
        )
        get_success_data(api_client.hold_session(session["id"], ADMIN))
        outsider_family = create_family()
        outsider = create_student(outsider_family["id"])
        resp = api_client.post_attendance(
            session["id"],
            {"entries": [{"student_id": outsider["id"], "status": "PRESENT"}]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ENROLLED)


class TestMilestoneThreshold:
    def test_exactly_80pct_boundary(self):
        """PRD §3.4: "the milestone moves `TRACKING` → `ELIGIBLE` when
        `current_attendance_pct` reaches or exceeds the year's
        `attendance_threshold_pct`, and slips back `ELIGIBLE` → `TRACKING` when
        recomputation drops it below". PRD §3.1: "(a typical value is 80, and the
        comparison is inclusive)".

        Design: Difficulty/boundary_precision_check/milestone_attendance_exactly_80pct_boundary
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "PRESENT", "ABSENT"],
            clock_to="2026-10-11T12:00:00Z",
        )
        milestone = ctx["milestone"]
        # Exactly 4.0/5 = 80.0 -> inclusive >= meets the threshold.
        assert milestone["current_attendance_pct"] == pytest.approx(80.0, abs=0.001)
        assert milestone["status"] == "ELIGIBLE"
        # Upsert one PRESENT -> ABSENT: 3.0/5 = 60.0 -> reverts below threshold.
        post_marks(ctx["held_sessions"][0]["id"], ctx["student"]["id"], "ABSENT")
        m_now = get_success_data(api_client.get_milestone(milestone["id"], ADMIN))
        assert m_now["current_attendance_pct"] == pytest.approx(60.0, abs=0.001)
        assert m_now["status"] == "TRACKING"

    def test_threshold_cycle_eligible_then_back_to_tracking(self):
        """PRD §3.4: "a cycle that may repeat arbitrarily over the year" for
        "TRACKING" → "ELIGIBLE" and back.

        Design: Difficulty/non_linear_state_machine/milestone_eligible_tracking_threshold_cycle
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "PRESENT", "ABSENT"],
            num_scheduled_extra=1,
            clock_to="2026-10-18T12:00:00Z",
        )
        milestone = ctx["milestone"]
        # After 5 sessions: 4.0/5 = 80.0 -> ELIGIBLE.
        assert milestone["status"] == "ELIGIBLE"
        assert milestone["current_attendance_pct"] == pytest.approx(80.0, abs=0.001)
        # Hold the 6th session and post ABSENT: 4.0/6 = 66.67 -> back to TRACKING.
        sixth = ctx["scheduled_sessions"][0]
        get_success_data(api_client.hold_session(sixth["id"], ADMIN))
        post_marks(sixth["id"], ctx["student"]["id"], "ABSENT")
        m_now = get_success_data(api_client.get_milestone(milestone["id"], ADMIN))
        assert m_now["status"] == "TRACKING"
        assert m_now["current_attendance_pct"] == pytest.approx(66.67, abs=0.001)


    def test_evaluate_reapplies_threshold(self):
        """PRD §3.4: "Whenever attendance is posted, a session is cancelled or
        held, or an administrator invokes the evaluate capability, the two
        percentages are recomputed and the threshold rule is applied: the milestone
        moves `TRACKING` → `ELIGIBLE` when `current_attendance_pct` reaches or
        exceeds the year's `attendance_threshold_pct`".

        Design: Difficulty/non_linear_state_machine/milestone_eligible_tracking_threshold_cycle
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "PRESENT", "ABSENT"],
            clock_to="2026-10-11T12:00:00Z",
        )
        milestone = ctx["milestone"]
        # 80.0 already reached ELIGIBLE; an explicit evaluate keeps it there.
        evaluated = get_success_data(
            api_client.evaluate_milestone(milestone["id"], ADMIN)
        )
        assert evaluated["status"] == "ELIGIBLE"
        assert evaluated["current_attendance_pct"] == pytest.approx(80.0, abs=0.001)


class TestMilestoneBoundaryBelow:
    def test_79_99_equivalent_stays_tracking(self):
        """PRD §3.4: "the milestone moves `TRACKING` → `ELIGIBLE` when
        `current_attendance_pct` reaches or exceeds the year's
        `attendance_threshold_pct`, and slips back `ELIGIBLE` → `TRACKING` when
        recomputation drops it below" — with 3 PRESENT + 1 EXCUSED + 1 ABSENT the
        current percentage is (1+1+1+0.5+0)/5 = 70.0, strictly below 80, so the
        milestone remains TRACKING.

        Design: Difficulty/boundary_precision_check/milestone_attendance_exactly_80pct_boundary
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "EXCUSED", "ABSENT"],
            clock_to="2026-10-11T12:00:00Z",
        )
        milestone = ctx["milestone"]
        # (3.0 + 0.5) / 5 = 70.0 < 80 -> never crosses the inclusive threshold.
        assert milestone["current_attendance_pct"] == pytest.approx(70.0, abs=0.001)
        assert milestone["status"] == "TRACKING"


class TestCurrentVsProjected:
    def test_current_75_projected_80_same_data(self):
        """PRD §3.4: "This current figure is the only variant consulted for
        milestone eligibility, and it is stored on the Milestone as
        `current_attendance_pct`. A second **projected** figure, stored as
        `projected_attendance_pct`, gives planners the best case: it adds the count
        of the section's `SCHEDULED` sessions to both the numerator and the
        denominator of the same formula".

        Design: Difficulty/dual_variant_calc/attendance_current_vs_projected_percentage
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "ABSENT"],
            num_scheduled_extra=1,
            clock_to="2026-10-04T12:00:00Z",
        )
        milestone = get_success_data(
            api_client.evaluate_milestone(ctx["milestone"]["id"], ADMIN)
        )
        # current: 3.0 / 4 HELD-with-attendance = 75.0
        assert milestone["current_attendance_pct"] == pytest.approx(75.0, abs=0.001)
        # projected: (3 + 1 SCHEDULED) / (4 + 1) = 80.0
        assert milestone["projected_attendance_pct"] == pytest.approx(80.0, abs=0.001)
        # Only the current variant gates eligibility: 75 < 80 -> TRACKING.
        assert milestone["status"] == "TRACKING"

    def test_projected_variant_adds_scheduled_to_both_sides(self):
        """PRD §3.4: "it adds the count of the section's `SCHEDULED` sessions to
        both the numerator and the denominator of the same formula, as if the
        student attended every remaining scheduled meeting".

        Design: Difficulty/dual_variant_calc/attendance_current_vs_projected_percentage
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "ABSENT"], num_scheduled_extra=2,
            clock_to="2026-09-20T12:00:00Z",
        )
        milestone = get_success_data(
            api_client.evaluate_milestone(ctx["milestone"]["id"], ADMIN)
        )
        # current: 1.0 / 2 = 50.0
        assert milestone["current_attendance_pct"] == pytest.approx(50.0, abs=0.001)
        # projected: (1 + 2) / (2 + 2) = 75.0
        assert milestone["projected_attendance_pct"] == pytest.approx(75.0, abs=0.001)


class TestTeacherAttendanceOwnership:
    def test_teacher_attendance_ownership(self):
        """PRD §2.1: "the only write a teacher may perform is posting attendance,
        and only for sessions of sections whose `teacher_id` equals `X-User-ID` —
        otherwise the request fails with `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/teacher_attendance_ownership
        """
        ctx = setup_open_year_with_section()
        section, t1 = ctx["section"], ctx["teacher"]
        t2 = create_hired_teacher()
        bundle = setup_family_with_enrollment(section, 1)
        student = bundle["students"][0]
        session = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-13"}, ADMIN),
            201,
        )
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-09-13T12:00:00Z"}, ADMIN)
        )
        get_success_data(api_client.hold_session(session["id"], ADMIN))
        payload = {"entries": [{"student_id": student["id"], "status": "PRESENT"}]}
        # T2 (hired, but not assigned to this section) -> ownership mismatch.
        resp = api_client.post_attendance(session["id"], payload, make_teacher_headers(t2["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        # T1 (the section's teacher) -> succeeds.
        ok = api_client.post_attendance(session["id"], payload, make_teacher_headers(t1["id"]))
        ok_data = validate_success(ok, 200)
        assert len(ok_data["attendance"]) == 1
