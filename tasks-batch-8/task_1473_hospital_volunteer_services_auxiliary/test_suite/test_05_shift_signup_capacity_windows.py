"""Shift lifecycle gates: terminal lockdown, half-open double-booking, capacity
with waitlist branching, signup/self-cancel windows, the junior weekly cap, and the
18th-birthday age boundary."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    set_clock, approve_application, create_cleared_volunteer, create_active_volunteer,
    create_department, create_role, create_open_request, create_published_shift,
    signup, get_volunteer,
    make_volunteer_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _infra(dept_name="Emergency", role_name="ED Greeter", category="PATIENT_FACING",
           minimum_age=18, slots=1, **role_extra):
    dept = create_department(name=dept_name, head_user_id="dh-1")
    role = create_role(name=role_name, category=category, minimum_age=minimum_age,
                       **role_extra)
    request = create_open_request(dept["id"], role["id"], slots_needed=slots)
    return dept, role, request


class TestShiftTerminalLockdown:
    def test_cancelled_shift_rejects_publish_and_signup(self, api):
        """PRD §3.5: "Publication moves `SCHEDULED` → `PUBLISHED`, and from any other
        state the attempt is `ERR_SHIFT_INVALID_STATE`."
        PRD §3.5: "The shift must be `PUBLISHED` (`ERR_SHIFT_INVALID_STATE`)."

        Design: Corner/state_machines/shift_terminal_lockdown
        """
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _infra()
        ctx = create_active_volunteer(dept, role, request, full_name="V Lock",
                                      email="vl@x.org")
        shift = get_success_data(api.create_shift(
            {"department_id": dept["id"], "role_id": role["id"],
             "start_at": "2026-08-10T08:00:00Z", "end_at": "2026-08-10T12:00:00Z",
             "capacity": 3}, COORDINATOR))
        validate_success(api.cancel_shift(shift["id"], COORDINATOR))

        resp = api.publish_shift(shift["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SHIFT_INVALID_STATE)
        resp = api.create_shift_assignment(
            {"shift_id": shift["id"], "volunteer_id": ctx["volunteer_id"]},
            make_volunteer_headers(ctx["volunteer_id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_INVALID_STATE)


class TestDoubleBookingHalfOpen:
    def _setup(self, slots=1):
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _infra(slots=slots)
        ctx = create_active_volunteer(dept, role, request, full_name="V Overlap",
                                      email="vo@x.org")
        return dept, role, request, ctx

    def test_overlap_rejected_adjacency_allowed(self, api):
        """PRD §3.5: "the new shift's window may not half-open-overlap the volunteer's
        other `SIGNED_UP` or `CONFIRMED` shifts (`ERR_SHIFT_TIME_OVERLAP`) —
        adjacency, where one shift's end equals the other's start, is allowed."

        Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_half_open
        """
        dept, role, _, ctx = self._setup()
        vol_id = ctx["volunteer_id"]
        sA = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                    "2026-08-10T12:00:00Z", capacity=5)
        sB = create_published_shift(dept["id"], role["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T14:00:00Z", capacity=5)
        sC = create_published_shift(dept["id"], role["id"], "2026-08-10T12:00:00Z",
                                    "2026-08-10T16:00:00Z", capacity=5)
        signup(sA["id"], vol_id)

        resp = api.create_shift_assignment(
            {"shift_id": sB["id"], "volunteer_id": vol_id}, make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_OVERLAP)

        adjacent = validate_success(api.create_shift_assignment(
            {"shift_id": sC["id"], "volunteer_id": vol_id}, make_volunteer_headers(vol_id)),
            expected_status=201)
        assert adjacent["status"] == "SIGNED_UP", (
            "adjacency (C starts exactly at A's end) is allowed under half-open semantics")

        mine = get_success_data(api.list_shift_assignments(
            COORDINATOR, params={"volunteer_id": vol_id, "status": "SIGNED_UP"}))
        assert len(mine) == 2, f"exactly the A and C assignments remain live, got {len(mine)}"

    def test_waitlisted_overlap_is_not_counted(self, api):
        """PRD §3.5: "the new shift's window may not half-open-overlap the volunteer's
        other `SIGNED_UP` or `CONFIRMED` shifts (`ERR_SHIFT_TIME_OVERLAP`)" — a
        `WAITLISTED` row is neither, so it cannot block an overlapping signup.

        Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_half_open
        """
        dept, role, request, ctx = self._setup(slots=2)
        vol_id = ctx["volunteer_id"]
        w_ctx = create_active_volunteer(dept, role, request, full_name="W Seat",
                                        email="ws@x.org")

        sD = create_published_shift(dept["id"], role["id"], "2026-08-10T09:00:00Z",
                                    "2026-08-10T11:00:00Z", capacity=1,
                                    allow_waitlist=True)
        signup(sD["id"], w_ctx["volunteer_id"])          # occupies the single seat
        waitlisted = signup(sD["id"], vol_id)            # V lands WAITLISTED
        assert waitlisted["status"] == "WAITLISTED"

        sA = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                    "2026-08-10T12:00:00Z", capacity=5)
        signed = validate_success(api.create_shift_assignment(
            {"shift_id": sA["id"], "volunteer_id": vol_id}, make_volunteer_headers(vol_id)),
            expected_status=201)
        assert signed["status"] == "SIGNED_UP", (
            "the WAITLISTED row on overlapping shift D does not count as an occupation")

        sB = create_published_shift(dept["id"], role["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T14:00:00Z", capacity=5)
        resp = api.create_shift_assignment(
            {"shift_id": sB["id"], "volunteer_id": vol_id}, make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_OVERLAP)


class TestCapacityWaitlistBranch:
    def _setup_two_volunteers(self):
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _infra(slots=3)
        w1 = create_active_volunteer(dept, role, request, full_name="W One",
                                     email="w1@x.org")
        w2 = create_active_volunteer(dept, role, request, full_name="W Two",
                                     email="w2@x.org")
        return dept, role, request, w1, w2

    def test_full_shift_rejects_or_waitlists(self, api):
        """PRD §3.5: "When the shift is full, a shift with `allow_waitlist` true
        accepts the assignment as `WAITLISTED`; a shift without it rejects the signup
        with `ERR_SHIFT_AT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/shift_capacity_aggregate_with_waitlist_branch
        """
        dept, role, _, w1, w2 = self._setup_two_volunteers()
        s1 = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                    "2026-08-10T12:00:00Z", capacity=1,
                                    allow_waitlist=False)
        s2 = create_published_shift(dept["id"], role["id"], "2026-08-11T08:00:00Z",
                                    "2026-08-11T12:00:00Z", capacity=1,
                                    allow_waitlist=True)
        signup(s1["id"], w1["volunteer_id"])
        resp = api.create_shift_assignment(
            {"shift_id": s1["id"], "volunteer_id": w2["volunteer_id"]},
            make_volunteer_headers(w2["volunteer_id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_AT_CAPACITY)

        signup(s2["id"], w1["volunteer_id"])
        queued = validate_success(api.create_shift_assignment(
            {"shift_id": s2["id"], "volunteer_id": w2["volunteer_id"]},
            make_volunteer_headers(w2["volunteer_id"])), expected_status=201)
        assert queued["status"] == "WAITLISTED"
        s2_now = get_success_data(api.get_shift(s2["id"], COORDINATOR))
        assert s2_now["filled_count"] == 1, "waitlisted rows do not occupy aggregate capacity"

    def test_filled_count_tracks_signed_up_only(self, api):
        """PRD §3.5: "While `filled_count` is below `capacity`, the assignment lands
        `SIGNED_UP`, `signed_up_at` is stamped from the logical clock, and
        `filled_count` increments by one."

        Design: Difficulty/resource_temporal_overlap/shift_capacity_aggregate_with_waitlist_branch
        """
        dept, role, request, w1, w2 = self._setup_two_volunteers()
        w3 = create_active_volunteer(dept, role, request, full_name="W Three",
                                     email="w3@x.org")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-12T08:00:00Z",
                                       "2026-08-12T12:00:00Z", capacity=2,
                                       allow_waitlist=True)
        signup(shift["id"], w1["volunteer_id"])
        mid = get_success_data(api.get_shift(shift["id"], COORDINATOR))
        assert mid["filled_count"] == 1

        signup(shift["id"], w2["volunteer_id"])
        full = get_success_data(api.get_shift(shift["id"], COORDINATOR))
        assert full["filled_count"] == 2

        queued = validate_success(api.create_shift_assignment(
            {"shift_id": shift["id"], "volunteer_id": w3["volunteer_id"]},
            make_volunteer_headers(w3["volunteer_id"])), expected_status=201)
        assert queued["status"] == "WAITLISTED"
        after = get_success_data(api.get_shift(shift["id"], COORDINATOR))
        assert after["filled_count"] == 2, "filled_count increments only for SIGNED_UP landings"


class TestSignupAndCancelWindows:
    def _setup_active(self):
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _infra()
        ctx = create_active_volunteer(dept, role, request, full_name="Window Wes",
                                      email="ww@x.org")
        return dept, role, ctx

    def test_signup_window_boundary_closed_at_cutoff(self, api):
        """PRD §3.5: "Signup closes 24 hours before the shift starts: now must be
        strictly earlier than `start_at` minus 24 hours, and at or after that cutoff
        the signup is `ERR_SIGNUP_WINDOW_CLOSED`."

        Design: Corner/validations/signup_window_boundary_closed_at_cutoff
        """
        dept, role, ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=2)

        set_clock("2026-08-09T07:59:00Z")  # one minute before start-24h
        asg = validate_success(api.create_shift_assignment(
            {"shift_id": shift["id"], "volunteer_id": vol_id},
            make_volunteer_headers(vol_id)), expected_status=201)
        assert asg["status"] == "SIGNED_UP"
        validate_success(api.cancel_assignment(asg["id"], COORDINATOR))

        set_clock("2026-08-09T08:00:00Z")  # exactly start-24h: boundary is exclusive
        resp = api.create_shift_assignment(
            {"shift_id": shift["id"], "volunteer_id": vol_id},
            make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_SIGNUP_WINDOW_CLOSED)

    def test_self_cancel_window_staff_override(self, api):
        """PRD §3.5: "A volunteer cancelling their own assignment faces the same
        24-hour window as signup: now must be strictly earlier than `start_at` minus
        24 hours, or the attempt is `ERR_CANCEL_WINDOW_CLOSED`; staff roles bypass
        the window."

        Design: Corner/validations/self_cancel_window_staff_override
        """
        dept, role, ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        shift = create_published_shift(dept["id"], role["id"], "2026-08-02T08:00:00Z",
                                       "2026-08-02T12:00:00Z", capacity=2)
        asg = signup(shift["id"], vol_id)

        set_clock("2026-08-01T12:00:00Z")  # start-20h: inside the 24h window
        resp = api.cancel_assignment(asg["id"], make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_CANCEL_WINDOW_CLOSED)
        row = get_success_data(api.get_shift_assignment(asg["id"], COORDINATOR))
        assert row["status"] == "SIGNED_UP", "failed self-cancel causes no drift"

        cancelled = validate_success(api.cancel_assignment(asg["id"], COORDINATOR))
        assert cancelled["status"] == "CANCELLED", "staff bypass the window"


class TestJuniorWeeklyCap:
    def _setup_junior(self):
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _infra(dept_name="Library Cart",
                                     role_name="Book Cart Aide", category="COMMUNITY",
                                     minimum_age=14, slots=2)
        ctx = create_active_volunteer(dept, role, request, full_name="J Teen",
                                      date_of_birth="2011-06-15", email="j@x.org",
                                      phone="555-3001")
        return dept, role, ctx

    def test_exactly_16_hours_allowed_then_over(self, api):
        """PRD §3.5: "If the projection exceeds 16.0 hours, the signup is rejected
        with `ERR_JUNIOR_WEEKLY_HOUR_CAP_EXCEEDED`; a projection of exactly 16.0
        hours is allowed."

        Design: Difficulty/boundary_precision_check/junior_weekly_cap_exactly_16_allowed
        """
        dept, role, ctx = self._setup_junior()
        j_id = ctx["volunteer_id"]
        s1 = create_published_shift(dept["id"], role["id"], "2026-08-03T06:00:00Z",
                                    "2026-08-03T12:00:00Z", capacity=5)
        s2 = create_published_shift(dept["id"], role["id"], "2026-08-04T13:00:00Z",
                                    "2026-08-04T19:00:00Z", capacity=5)
        s3 = create_published_shift(dept["id"], role["id"], "2026-08-05T08:00:00Z",
                                    "2026-08-05T12:00:00Z", capacity=5)
        s4 = create_published_shift(dept["id"], role["id"], "2026-08-08T14:00:00Z",
                                    "2026-08-08T14:15:00Z", capacity=5)

        signup(s1["id"], j_id)   # 6.0h
        signup(s2["id"], j_id)   # 12.0h projected
        third = signup(s3["id"], j_id)   # 16.0h projected EXACTLY
        assert third["status"] == "SIGNED_UP", "16.0 is the inclusive boundary"

        resp = api.create_shift_assignment(
            {"shift_id": s4["id"], "volunteer_id": j_id}, make_volunteer_headers(j_id))
        validate_error(resp, ApiErrorId.ERR_JUNIOR_WEEKLY_HOUR_CAP_EXCEEDED)

    def test_waitlisted_hours_not_counted_in_projection(self, api):
        """PRD §3.5: "Sum the durations of the volunteer's shifts whose assignments
        stand `SIGNED_UP` or `CONFIRMED` with shift starts inside that week;
        `WAITLISTED` assignments are not counted, because a waitlist seat is not an
        occupation."

        Design: Difficulty/boundary_precision_check/junior_weekly_cap_exactly_16_allowed
        """
        dept, role, ctx = self._setup_junior()
        j_id = ctx["volunteer_id"]
        w_ctx = create_active_volunteer(dept, role, ctx["request"], full_name="W Seat",
                                        email="ws2@x.org")

        s1 = create_published_shift(dept["id"], role["id"], "2026-08-03T06:00:00Z",
                                    "2026-08-03T12:00:00Z", capacity=5)
        s2 = create_published_shift(dept["id"], role["id"], "2026-08-04T13:00:00Z",
                                    "2026-08-04T19:00:00Z", capacity=5)
        signup(s1["id"], j_id)   # 6.0h
        signup(s2["id"], j_id)   # 12.0h projected

        sC = create_published_shift(dept["id"], role["id"], "2026-08-05T08:00:00Z",
                                    "2026-08-05T12:00:00Z", capacity=1,
                                    allow_waitlist=True)
        signup(sC["id"], w_ctx["volunteer_id"])          # fills the single seat
        queued = signup(sC["id"], j_id)                  # J waitlisted on a 4h shift
        assert queued["status"] == "WAITLISTED"

        sD = create_published_shift(dept["id"], role["id"], "2026-08-06T08:00:00Z",
                                    "2026-08-06T12:00:00Z", capacity=5)
        fourth = signup(sD["id"], j_id)
        assert fourth["status"] == "SIGNED_UP", (
            "projected = 12.0 signed-up hours + 4.0 new = 16.0 exactly; the 4h "
            "WAITLISTED row is not counted")


class TestEighteenthBirthdayBoundary:
    def test_18th_birthday_counts_as_adult(self, api):
        """PRD §3.4: "Age at a date is the whole years between `date_of_birth` and
        that date, with a birthday falling on the date counting as reached — a
        volunteer whose 18th birthday is the shift's start date is an adult for that
        shift."
        PRD §3.5: "The volunteer's age at the shift's start date must meet the role's
        `minimum_age` (`ERR_ROLE_MIN_AGE_NOT_MET`)".

        Design: Corner/calculations/is_junior_18th_birthday_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Library Cart", head_user_id="dh-1")
        role14 = create_role(name="Book Cart Aide", category="COMMUNITY", minimum_age=14)
        role18 = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role14["id"], slots_needed=1)
        ctx = create_active_volunteer(dept, role14, request, full_name="Birthday Bea",
                                      date_of_birth="2008-08-10", email="bb@x.org",
                                      phone="555-9604")
        vol_id = ctx["volunteer_id"]

        s_before = create_published_shift(dept["id"], role18["id"],
                                          "2026-08-09T08:00:00Z", "2026-08-09T12:00:00Z",
                                          capacity=5)
        s_on = create_published_shift(dept["id"], role18["id"], "2026-08-10T08:00:00Z",
                                      "2026-08-10T12:00:00Z", capacity=5)

        resp = api.create_shift_assignment(
            {"shift_id": s_before["id"], "volunteer_id": vol_id},
            make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_ROLE_MIN_AGE_NOT_MET)

        on_day = validate_success(api.create_shift_assignment(
            {"shift_id": s_on["id"], "volunteer_id": vol_id},
            make_volunteer_headers(vol_id)), expected_status=201)
        assert on_day["status"] == "SIGNED_UP", (
            "the 18th birthday itself counts as reached — adult for that shift")


class TestSafetyBeatsCapacity:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Lab", head_user_id="dh-1", junior_allowed=True)
        role18 = create_role(name="Phlebotomy Aide", category="PATIENT_FACING",
                             minimum_age=18)
        role14 = create_role(name="Book Cart Aide", category="COMMUNITY", minimum_age=14)
        req_w = create_open_request(dept["id"], role18["id"], slots_needed=2)
        req_j = create_open_request(dept["id"], role14["id"], slots_needed=1)
        w_ctx = create_active_volunteer(dept, role18, req_w, full_name="W Grown",
                                        email="w@x.org")
        j_ctx = create_active_volunteer(dept, role14, req_j, full_name="J Teen",
                                        date_of_birth="2011-06-15", email="j@x.org",
                                        phone="555-3001")
        shift = create_published_shift(dept["id"], role18["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=1,
                                       allow_waitlist=False)
        return dept, role18, w_ctx, j_ctx, shift

    def test_min_age_error_beats_capacity_error(self, api):
        """PRD §2.8: "Checks are evaluated in a fixed thirteen-tier order, and the
        earliest failing tier wins — an earlier failure masks later ones, so the
        client always sees the same error for the same doubly-invalid request."
        Tier 9 is "Minor-protection and training gates" (including
        `ERR_ROLE_MIN_AGE_NOT_MET`); tier 10 is "Uniqueness, capacity, and graph
        constraints" (including `ERR_SHIFT_AT_CAPACITY`).

        Design: Difficulty/priority_pair_validation_conflict/signup_safety_beats_capacity
        """
        _, _, w_ctx, j_ctx, shift = self._setup()
        signup(shift["id"], w_ctx["volunteer_id"])  # fills the only seat

        resp = api.create_shift_assignment(
            {"shift_id": shift["id"], "volunteer_id": j_ctx["volunteer_id"]},
            make_volunteer_headers(j_ctx["volunteer_id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_MIN_AGE_NOT_MET)

    def test_capacity_error_in_isolation(self, api):
        """PRD §3.5: "a shift without it rejects the signup with
        `ERR_SHIFT_AT_CAPACITY`."
        (Isolation control: an adult who meets the role's minimum age hits only the
        capacity gate on the same full shift.)

        Design: Difficulty/priority_pair_validation_conflict/signup_safety_beats_capacity
        """
        dept, role18, w_ctx, j_ctx, shift = self._setup()
        w2_ctx = create_active_volunteer(dept, role18, w_ctx["request"],
                                         full_name="W Second", email="w2x@x.org")
        signup(shift["id"], w_ctx["volunteer_id"])
        resp = api.create_shift_assignment(
            {"shift_id": shift["id"], "volunteer_id": w2_ctx["volunteer_id"]},
            make_volunteer_headers(w2_ctx["volunteer_id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_AT_CAPACITY)
