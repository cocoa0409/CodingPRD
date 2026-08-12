"""Counselor appointments: buffered intervals, nested-rounding utilization,
and the three-strike no-show freeze."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_counselor_headers,
    setup_counselor, setup_student, set_clock, make_appointment,
    make_no_show_appointment, assert_appointment,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCounselorUtilizationNestedRounding:
    def _setup(self, api):
        set_clock("2026-05-04T08:00:00Z")  # Monday
        counselor = setup_counselor(max_caseload=100, full_name="C Four")
        student = setup_student(counselor["id"], "U001", grade_level=10)
        make_appointment(counselor["id"], student["id"],
                         "2026-05-04T09:00:00Z", "2026-05-04T10:30:36Z")
        make_appointment(counselor["id"], student["id"],
                         "2026-05-04T13:00:00Z", "2026-05-04T13:20:24Z")
        return counselor

    def test_utilization_truncates_each_duration_before_summing(self, api):
        """PRD §3.6: "each appointment's duration is first truncated to whole
        minutes with seconds discarded rather than rounded, the whole minutes are
        then summed, and only then is the division performed."
        PRD §3.6: "summing fractional minutes before truncating is forbidden
        because it would produce a different result."

        Design: Difficulty/combinatorial_formula/counselor_utilization_nested_rounding
        """
        counselor = self._setup(api)
        data = validate_success(api.get_counselor_utilization(counselor["id"], ADMIN, params={
            "window_start": "2026-05-04T00:00:00Z", "window_end": "2026-05-05T00:00:00Z",
        }), 200)
        assert float(data["utilization"]) == pytest.approx(0.3056, abs=1e-9), (
            "truncate-then-sum yields 110/360 = 0.3056; the forbidden "
            f"sum-then-truncate yields 111/360 = 0.3083; got {data['utilization']}"
        )

    def test_utilization_booked_minutes_whole_truncation(self, api):
        """PRD §3.6: "Booked minutes sum the durations of the counselor's
        `BOOKED` appointments inside the half-open window" with "each
        appointment's duration ... first truncated to whole minutes with seconds
        discarded rather than rounded".

        Design: Difficulty/combinatorial_formula/counselor_utilization_nested_rounding
        """
        counselor = self._setup(api)
        data = validate_success(api.get_counselor_utilization(counselor["id"], ADMIN, params={
            "window_start": "2026-05-04T00:00:00Z", "window_end": "2026-05-05T00:00:00Z",
        }), 200)
        assert data["booked_minutes"] == 110, (
            f"90m36s truncates to 90 and 20m24s to 20, sum 110; got {data['booked_minutes']}"
        )
        assert data["available_minutes"] == 360


class TestAppointmentBufferedIntervalSemantics:
    def _setup(self, api):
        set_clock("2026-05-11T07:00:00Z")  # Monday
        counselor = setup_counselor(max_caseload=100, full_name="C Sixteen")
        s_b1 = setup_student(counselor["id"], "B001", grade_level=9)
        s_b2 = setup_student(counselor["id"], "B002", grade_level=9)
        s_b3 = setup_student(counselor["id"], "B003", grade_level=9)
        make_appointment(counselor["id"], s_b1["id"],
                         "2026-05-11T09:00:00Z", "2026-05-11T09:30:00Z")
        return counselor, s_b2, s_b3

    def test_back_to_back_and_nine_minute_gap_rejected(self, api):
        """PRD §3.6: "it must keep a buffer of at least 10 minutes on both sides
        of every existing `BOOKED` interval — back-to-back appointments are
        forbidden, since adjacency without the buffer is itself a conflict."
        Both surface as `ERR_APPOINTMENT_CONFLICT` (HTTP 409).

        Design: Difficulty/resource_temporal_overlap/appointment_buffered_interval_semantics
        """
        counselor, s_b2, _ = self._setup(api)
        resp_adjacent = api.create_appointment({
            "counselor_id": counselor["id"], "student_id": s_b2["id"],
            "start_at": "2026-05-11T09:30:00Z", "end_at": "2026-05-11T10:00:00Z",
        }, make_counselor_headers(counselor["id"]))
        validate_error(resp_adjacent, ApiErrorId.ERR_APPOINTMENT_CONFLICT, 409)
        resp_nine = api.create_appointment({
            "counselor_id": counselor["id"], "student_id": s_b2["id"],
            "start_at": "2026-05-11T09:39:00Z", "end_at": "2026-05-11T10:09:00Z",
        }, make_counselor_headers(counselor["id"]))
        validate_error(resp_nine, ApiErrorId.ERR_APPOINTMENT_CONFLICT, 409)

    def test_ten_minute_gap_accepted(self, api):
        """PRD §3.6: "it must keep a buffer of at least 10 minutes on both sides
        of every existing `BOOKED` interval" — a gap of exactly 10 minutes
        satisfies the boundary.

        Design: Difficulty/resource_temporal_overlap/appointment_buffered_interval_semantics
        """
        counselor, _, s_b3 = self._setup(api)
        data = validate_success(api.create_appointment({
            "counselor_id": counselor["id"], "student_id": s_b3["id"],
            "start_at": "2026-05-11T09:40:00Z", "end_at": "2026-05-11T10:10:00Z",
        }, make_counselor_headers(counselor["id"])), 201)
        assert_appointment(data)
        assert data["state"] == "BOOKED"


class TestNoShowFreezeAtExactlyThree:
    def _setup(self, api):
        set_clock("2026-03-01T08:00:00Z")
        counselor = setup_counselor(max_caseload=100, full_name="C Twelve")
        s_two = setup_student(counselor["id"], "TWO1", grade_level=9)
        s_three = setup_student(counselor["id"], "THR1", grade_level=9)
        for day in ("2026-03-02", "2026-03-03"):
            make_no_show_appointment(counselor["id"], s_two["id"],
                                     f"{day}T09:00:00Z", f"{day}T09:30:00Z")
        for day in ("2026-03-02", "2026-03-03", "2026-03-04"):
            make_no_show_appointment(counselor["id"], s_three["id"],
                                     f"{day}T10:00:00Z", f"{day}T10:30:00Z")
        set_clock("2026-05-06T12:00:00Z")
        return counselor, s_two, s_three

    def test_two_no_shows_do_not_freeze(self, api):
        """PRD §3.6: "When that count has reached three — exactly three engages
        the freeze; the rule is a threshold met, not exceeded — any new booking
        for the student is rejected with `ERR_NO_SHOW_FREEZE` (HTTP 422)."
        A count of two stays below the threshold.

        Design: Difficulty/boundary_precision_check/no_show_freeze_at_exactly_three
        """
        counselor, s_two, _ = self._setup(api)
        data = validate_success(api.create_appointment({
            "counselor_id": counselor["id"], "student_id": s_two["id"],
            "start_at": "2026-05-07T09:00:00Z", "end_at": "2026-05-07T09:30:00Z",
        }, make_counselor_headers(counselor["id"])), 201)
        assert data["state"] == "BOOKED"

    def test_exactly_three_no_shows_freezes(self, api):
        """PRD §3.6: "When that count has reached three — exactly three engages
        the freeze; the rule is a threshold met, not exceeded — any new booking
        for the student is rejected with `ERR_NO_SHOW_FREEZE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/no_show_freeze_at_exactly_three
        """
        counselor, _, s_three = self._setup(api)
        resp = api.create_appointment({
            "counselor_id": counselor["id"], "student_id": s_three["id"],
            "start_at": "2026-05-08T09:00:00Z", "end_at": "2026-05-08T09:30:00Z",
        }, make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_FREEZE, 422)


class TestNoShowCascadeToBookingFreeze:
    def _setup(self, api):
        set_clock("2026-03-01T08:00:00Z")
        counselor = setup_counselor(max_caseload=100, full_name="C Seven")
        s_ns = setup_student(counselor["id"], "NS01", grade_level=11)
        make_no_show_appointment(counselor["id"], s_ns["id"],
                                 "2026-03-02T09:00:00Z", "2026-03-02T09:30:00Z")
        make_no_show_appointment(counselor["id"], s_ns["id"],
                                 "2026-03-09T09:00:00Z", "2026-03-09T09:30:00Z")
        ap3 = make_appointment(counselor["id"], s_ns["id"],
                               "2026-05-06T09:00:00Z", "2026-05-06T09:30:00Z")
        set_clock("2026-05-06T12:00:00Z")
        return counselor, s_ns, ap3

    def test_third_no_show_marks_appointment_and_accumulates(self, api):
        """PRD §3.6: "marking a no-show moves `BOOKED` → `NO_SHOW`, which
        recomputes the student's trailing no-show count and may trip the freeze
        against future bookings."
        PRD §3.6: "A student's trailing no-show count is the number of their
        appointments in state `NO_SHOW` whose `start_at` falls within the 90 days
        before the server's logical now"

        Design: Difficulty/transitive_cascade/no_show_cascade_to_booking_freeze
        """
        counselor, s_ns, ap3 = self._setup(api)
        done = validate_success(api.mark_no_show_appointment(
            ap3["id"], make_counselor_headers(counselor["id"])), 200)
        assert done["state"] == "NO_SHOW"
        no_shows = get_success_data(api.list_appointments(ADMIN, params={
            "student_id": s_ns["id"], "state": "NO_SHOW",
        }))
        assert len(no_shows) == 3, "the recomputed trailing count must be 3"

    def test_recomputed_freeze_rejects_next_booking(self, api):
        """PRD §3.6: "When that count has reached three — exactly three engages
        the freeze; the rule is a threshold met, not exceeded — any new booking
        for the student is rejected with `ERR_NO_SHOW_FREEZE` (HTTP 422)." The
        rejection is caused by the recomputed count crossing the threshold, not
        by the mark-no-show call directly.

        Design: Difficulty/transitive_cascade/no_show_cascade_to_booking_freeze
        """
        counselor, s_ns, ap3 = self._setup(api)
        get_success_data(api.mark_no_show_appointment(
            ap3["id"], make_counselor_headers(counselor["id"])))
        resp = api.create_appointment({
            "counselor_id": counselor["id"], "student_id": s_ns["id"],
            "start_at": "2026-05-07T09:00:00Z", "end_at": "2026-05-07T09:30:00Z",
        }, make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_FREEZE, 422)


class TestAppointmentLifecycle:
    def test_appointment_complete_side_effect_version(self, api):
        """PRD §3.6: "completing it moves `BOOKED` → `COMPLETED`"
        PRD §3.6: "Each of these resolutions increments the appointment's
        `version` by one."

        Design: Corner/state_machines/appointment_complete_side_effect_version
        """
        set_clock("2026-05-12T07:00:00Z")  # Tuesday
        counselor = setup_counselor(max_caseload=50, full_name="C Cmp")
        student = setup_student(counselor["id"], "CMP1", grade_level=9)
        appt = make_appointment(counselor["id"], student["id"],
                                "2026-05-12T09:00:00Z", "2026-05-12T09:30:00Z")
        version_before = appt["version"]
        done = validate_success(api.complete_appointment(
            appt["id"], make_counselor_headers(counselor["id"])), 200)
        assert done["state"] == "COMPLETED"
        assert done["version"] == version_before + 1


class TestUtilizationWindowBoundary:
    def test_utilization_window_boundary_exclusion(self, api):
        """PRD §3.6: "Booked minutes sum the durations of the counselor's
        `BOOKED` appointments inside the half-open window — an appointment
        starting exactly at `window_end` is excluded, and one ending exactly at
        `window_start` is excluded"

        Design: Corner/calculations/utilization_window_boundary_exclusion
        """
        set_clock("2026-05-13T07:00:00Z")  # Wednesday
        counselor = setup_counselor(max_caseload=50, full_name="C Wb")
        s_wb1 = setup_student(counselor["id"], "WB01", grade_level=9)
        s_wb2 = setup_student(counselor["id"], "WB02", grade_level=9)
        make_appointment(counselor["id"], s_wb1["id"],
                         "2026-05-13T09:00:00Z", "2026-05-13T09:30:00Z")
        make_appointment(counselor["id"], s_wb2["id"],
                         "2026-05-14T00:00:00Z", "2026-05-14T00:30:00Z")
        data = validate_success(api.get_counselor_utilization(counselor["id"], ADMIN, params={
            "window_start": "2026-05-13T00:00:00Z", "window_end": "2026-05-14T00:00:00Z",
        }), 200)
        assert data["booked_minutes"] == 30, (
            "the appointment starting exactly at window_end must be excluded"
        )
        assert float(data["utilization"]) == pytest.approx(0.0833, abs=1e-9)
