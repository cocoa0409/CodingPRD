"""Leave request workflow: two-key approval, allowance accounting, windows, sweeps."""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_leave_request, assert_student, assert_standing_matches_points,
    create_leave_request_payload,
    make_student_headers, make_parent_headers, make_dorm_parent_headers,
    make_front_desk_headers, make_dean_headers,
    make_active_term, make_parent, make_student, make_dorm, make_room,
    make_dorm_parent, make_dean, make_front_desk,
    propose_assignment, confirm_assignment, setup_confirmed_residency,
    file_leave, parent_approve_leave, dorm_approve_leave,
    setup_leave_parent_approved, setup_leave_approved,
    report_case, sanction_minor_case, set_clock, get_student,
)

LEAVE_DEPARTS = "2026-09-04T17:00:00Z"
LEAVE_RETURNS = "2026-09-06T19:00:00Z"


class TestLeaveWindowOverlap:
    def _setup_student_with_requested_leave(self):
        dorm = make_dorm()
        make_room(dorm["id"], beds=2)
        term = make_active_term()
        parent = make_parent()
        student = make_student(parent["id"], grade=12, gender="MALE", legal_name="Stu R")
        leave1 = file_leave(student["id"], destination="Boston")
        return student, leave1

    def test_adjacent_leave_touching_endpoint_allowed(self, api):
        """PRD §3.4: "One student's non-terminal leaves may not overlap in time:
        the half-open interval from `departs_at` (inclusive) to `returns_at`
        (exclusive) must not intersect any other non-terminal leave of the same
        student, though intervals that merely touch at an endpoint are allowed".

        Design: Difficulty/resource_temporal_overlap/leave_window_half_open_adjacency_allowed_overlap_rejected
        """
        student, leave1 = self._setup_student_with_requested_leave()
        res = api.create_leave_request(
            create_leave_request_payload(destination="Home",
                                         departs_at="2026-09-06T19:00:00Z",
                                         returns_at="2026-09-08T21:00:00Z"),
            make_student_headers(student["id"]))
        leave2 = validate_success(res, 201)
        assert_leave_request(leave2)
        assert leave2["status"] == "REQUESTED"

    def test_overlapping_leave_one_minute_earlier_rejected(self, api):
        """PRD §3.4: "a collision is rejected with `ERR_LEAVE_WINDOW_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/leave_window_half_open_adjacency_allowed_overlap_rejected
        """
        student, leave1 = self._setup_student_with_requested_leave()
        res = api.create_leave_request(
            create_leave_request_payload(destination="Home",
                                         departs_at="2026-09-06T18:59:00Z",
                                         returns_at="2026-09-08T21:00:00Z"),
            make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_LEAVE_WINDOW_OVERLAP)


class TestAllowanceConservation:
    def test_approve_consumes_one_allowance_unit(self, api, admin_headers):
        """PRD §3.4: "A dorm approval moves the request to `APPROVED`, stamps
        `decided_by_staff_id`, and consumes one unit of the weekend allowance".

        Design: Difficulty/compensating_invariant/leave_approve_then_cancel_conserves_allowance_usage
        """
        ctx = setup_leave_parent_approved()
        before = get_student(ctx["student"]["id"])
        assert before["weekend_leaves_used"] == 0

        approved = dorm_approve_leave(ctx["leave"]["id"], ctx["dorm_parent"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_staff_id"] == ctx["dorm_parent"]["id"]

        after = get_student(ctx["student"]["id"])
        assert after["weekend_leaves_used"] == 1

    def test_cancel_of_approved_leave_releases_the_unit(self, api, admin_headers):
        """PRD §3.4: "The consumption counter `weekend_leaves_used` counts the
        student's `WEEKEND_OVERNIGHT` requests in the currently active term —
        measured by `departs_at` falling within the term's `starts_on` to
        `ends_on` range, both ends inclusive — whose status is `APPROVED`,
        `SIGNED_OUT`, `OVERDUE`, or `RETURNED`; denied, cancelled, and expired
        requests do not count." and "cancelling an `APPROVED` weekend overnight
        releases the allowance unit it consumed".

        Design: Difficulty/compensating_invariant/leave_approve_then_cancel_conserves_allowance_usage
        """
        ctx = setup_leave_approved()
        mid = get_student(ctx["student"]["id"])
        assert mid["weekend_leaves_used"] == 1

        cancelled = validate_success(api.cancel_leave(
            ctx["leave"]["id"], make_student_headers(ctx["student"]["id"])), 200)
        assert cancelled["status"] == "CANCELLED"

        after = get_student(ctx["student"]["id"])
        assert after["weekend_leaves_used"] == 0


class TestDormDecisionResidencyGate:
    def _setup_proposed_only_leave(self):
        """Student with a PROPOSED (never confirmed) assignment and a
        PARENT_APPROVED weekend leave."""
        dorm = make_dorm()
        room = make_room(dorm["id"], room_number="W-101", beds=2)
        term = make_active_term()
        parent = make_parent()
        student = make_student(parent["id"], grade=12, gender="MALE", legal_name="Stu P")
        dp = make_dorm_parent(dorm["id"])
        asg = propose_assignment(student["id"], room["id"], term["id"])
        leave = file_leave(student["id"], destination="Providence")
        parent_approve_leave(leave["id"], parent["id"])
        return {"dorm": dorm, "room": room, "term": term, "parent": parent,
                "student": student, "dorm_parent": dp, "assignment": asg,
                "leave": leave}

    def test_dorm_decision_without_confirmed_residency_rejected(self, api):
        """PRD §3.4: "the acting dorm parent's `dorm_id` must match the dorm of
        the student's `CONFIRMED` assignment in the active term — a student with
        no confirmed residency at all is rejected with `ERR_NO_CONFIRMED_RESIDENCY`".

        Design: Difficulty/cross_entity_state_dependency/leave_dorm_decision_requires_confirmed_assignment
        """
        ctx = self._setup_proposed_only_leave()
        res = api.dorm_decision(ctx["leave"]["id"], "APPROVE",
                                make_dorm_parent_headers(ctx["dorm_parent"]["id"]))
        validate_error(res, ApiErrorId.ERR_NO_CONFIRMED_RESIDENCY)

    def test_same_dorm_decision_succeeds_after_confirm(self, api):
        """PRD §3.4: "A dorm approval moves the request to `APPROVED`, stamps
        `decided_by_staff_id`, and consumes one unit of the weekend allowance".

        Design: Difficulty/cross_entity_state_dependency/leave_dorm_decision_requires_confirmed_assignment
        """
        ctx = self._setup_proposed_only_leave()
        validate_error(
            api.dorm_decision(ctx["leave"]["id"], "APPROVE",
                              make_dorm_parent_headers(ctx["dorm_parent"]["id"])),
            ApiErrorId.ERR_NO_CONFIRMED_RESIDENCY)

        confirm_assignment(ctx["assignment"]["id"])
        approved = validate_success(api.dorm_decision(
            ctx["leave"]["id"], "APPROVE",
            make_dorm_parent_headers(ctx["dorm_parent"]["id"])), 200)
        assert approved["status"] == "APPROVED"

        student = get_student(ctx["student"]["id"])
        assert student["weekend_leaves_used"] == 1


class TestStateBeatsFiscalPriority:
    def _setup_suspended_with_cancelled_leave(self):
        """Grade-12 student CONFIRMED, leave fully APPROVED, then a 20-point
        sanction flips standing to SUSPENDED and cascade-cancels the leave."""
        ctx = setup_leave_approved(grade=12)
        reporter = make_dean("Dean One")
        decider = make_dean("Dean Two")
        case = report_case(ctx["student"]["id"], reporter["id"],
                           category="MINOR", description="Contraband in room",
                           points_proposed=20)
        sanction_minor_case(case["id"], reporter["id"], decider["id"],
                            20, sanction_type="SUSPENSION")
        ctx["case"] = case
        return ctx

    def test_dorm_decision_on_cascade_cancelled_leave_returns_invalid_state(self, api):
        """PRD §2.6: "Only after all of that does the system check whether the
        target resource sits in a legitimate from-state for the requested
        transition (`ERR_INVALID_STATE`, HTTP 409), and only after state legality
        do the business, temporal, and fiscal rules of §3 run, each with the
        priority spelled out in its narrative."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_leave_dorm_decision
        """
        ctx = self._setup_suspended_with_cancelled_leave()
        leave = get_success_data(
            api.get_leave_request(ctx["leave"]["id"], TEST_USERS["admin_headers"]))
        assert leave["status"] == "CANCELLED"
        assert leave["denial_reason"] == "STANDING_SUSPENDED"

        res = api.dorm_decision(ctx["leave"]["id"], "APPROVE",
                                make_dorm_parent_headers(ctx["dorm_parent"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_suspended_student_has_zero_allowance_yet_state_error_wins(self, api, admin_headers):
        """PRD §3.4: "The allowance is computed from the student's grade — a base
        of 4 for grades 9 and 10, 6 for grade 11, and 8 for grade 12 — multiplied
        by a standing factor: full allowance for `GOOD`, half for `PROBATION`
        (rounding down to a whole number), and zero for `SUSPENDED`."
        PRD §2.6: "and only after state legality do the business, temporal, and
        fiscal rules of §3 run".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_leave_dorm_decision
        """
        ctx = self._setup_suspended_with_cancelled_leave()
        student = get_student(ctx["student"]["id"])
        assert student["discipline_standing"] == "SUSPENDED"
        assert student["weekend_leave_allowance"] == 0  # fiscal check would fail too

        res = api.dorm_decision(ctx["leave"]["id"], "APPROVE",
                                make_dorm_parent_headers(ctx["dorm_parent"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestWeekendLeaveAllowance:
    def _setup_grade11_international(self):
        from test_helpers import make_approved_guardian
        guardian = make_approved_guardian(max_wards=5)
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="FEMALE",
                               is_international=True, guardian_id=guardian["id"],
                               legal_name="Stu D")
        return student, guardian

    def test_grade11_international_good_standing_allowance_is_seven(self, api, admin_headers):
        """PRD §3.4: "The allowance is computed from the student's grade — a base
        of 4 for grades 9 and 10, 6 for grade 11, and 8 for grade 12 — multiplied
        by a standing factor: full allowance for `GOOD`, half for `PROBATION`
        (rounding down to a whole number), and zero for `SUSPENDED`. An
        international student whose guardian is currently `APPROVED` adds 1 on
        top of the floored product. The final `weekend_leave_allowance` is capped
        at 10."

        Design: Difficulty/combinatorial_formula/leave_allowance_tiered_standing_international
        """
        student, guardian = self._setup_grade11_international()
        fetched = get_student(student["id"])
        assert fetched["discipline_standing"] == "GOOD"
        # min(10, floor(6 * 1.0) + 1) = 7
        assert fetched["weekend_leave_allowance"] == 7

    def test_probation_halves_allowance_for_same_student(self, api, admin_headers):
        """PRD §3.4: "multiplied by a standing factor: full allowance for `GOOD`,
        half for `PROBATION` (rounding down to a whole number), and zero for
        `SUSPENDED`. An international student whose guardian is currently
        `APPROVED` adds 1 on top of the floored product."

        Design: Difficulty/combinatorial_formula/leave_allowance_tiered_standing_international
        """
        student, guardian = self._setup_grade11_international()
        before = get_student(student["id"])
        assert before["weekend_leave_allowance"] == 7

        reporter = make_dean("Dean One")
        decider = make_dean("Dean Two")
        case = report_case(student["id"], reporter["id"], category="MINOR",
                           description="Repeated dorm noise", points_proposed=10)
        sanction_minor_case(case["id"], reporter["id"], decider["id"],
                            10, sanction_type="PROBATION")

        after = get_student(student["id"])
        assert after["demerit_points"] == 10
        assert after["discipline_standing"] == "PROBATION"
        # min(10, floor(6 * 0.5) + 1) = 4
        assert after["weekend_leave_allowance"] == 4


class TestDayPassAllowance:
    def test_day_pass_does_not_consume_weekend_allowance(self, api, admin_headers):
        """PRD §3.4: "The consumption counter `weekend_leaves_used` counts the
        student's `WEEKEND_OVERNIGHT` requests in the currently active term" and
        "denied, cancelled, and expired requests do not count" — a DAY_PASS is
        not WEEKEND_OVERNIGHT and never enters the counter.

        Design: Corner/calculations/day_pass_does_not_consume_weekend_allowance
        """
        ctx = setup_leave_approved(
            grade=12, leave_type="DAY_PASS", destination="Town for dentist",
            departs_at="2026-09-09T13:00:00Z", returns_at="2026-09-09T17:00:00Z")
        assert ctx["leave"]["status"] == "APPROVED"

        student = get_student(ctx["student"]["id"])
        assert student["weekend_leaves_used"] == 0
        assert student["weekend_leave_allowance"] == 8  # grade 12, GOOD, domestic


class TestLeaveSweeps:
    def test_approved_leave_expires_after_grace_and_releases_allowance(self, api, admin_headers):
        """PRD §3.4: "If the student never signs out, the logical-clock sweep moves
        an `APPROVED` request to `EXPIRED` once the six-hour grace has lapsed,
        releasing the consumed allowance unit."
        PRD §3.4: "denied, cancelled, and expired requests do not count".

        Design: Corner/state_machines/expiry_sweep_marks_approved_leave_and_releases_allowance
        """
        ctx = setup_leave_approved(grade=12, gender="FEMALE")
        before = get_student(ctx["student"]["id"])
        assert before["weekend_leaves_used"] == 1

        set_clock("2026-09-04T23:00:01Z")  # past departs_at 17:00 + 6h grace

        leave = get_success_data(api.get_leave_request(ctx["leave"]["id"], admin_headers))
        assert leave["status"] == "EXPIRED"
        after = get_student(ctx["student"]["id"])
        assert after["weekend_leaves_used"] == 0

    def test_signed_out_leave_marked_overdue_by_sweep(self, api, admin_headers):
        """PRD §2.4: "A `SIGNED_OUT` leave whose planned return instant has passed
        moves to `OVERDUE`."

        Design: Corner/state_machines/overdue_sweep_marks_signed_out_leave
        """
        ctx = setup_leave_approved(grade=12)
        fd = make_front_desk()
        set_clock("2026-09-04T18:00:00Z")  # within [departs-2h, departs+6h]
        signed = validate_success(api.sign_out_leave(
            ctx["leave"]["id"], make_front_desk_headers(fd["id"])), 200)
        assert signed["status"] == "SIGNED_OUT"

        set_clock("2026-09-07T00:00:00Z")  # past returns_at 2026-09-06T19:00
        leave = get_success_data(api.get_leave_request(ctx["leave"]["id"], admin_headers))
        assert leave["status"] == "OVERDUE"


class TestSignOutWindowAndTerminalStates:
    def test_sign_out_outside_grace_window_rejected(self, api):
        """PRD §3.4: "Signing out is allowed only inside a grace window running
        from two hours before `departs_at` to six hours after it; outside that
        window the attempt is rejected with `ERR_SIGN_OUT_WINDOW`."

        Design: Corner/state_machines/leave_signout_outside_window_returns_error
        """
        ctx = setup_leave_approved(grade=12, gender="FEMALE")
        fd = make_front_desk()
        # Logical clock is still at the default 2026-08-01, more than 2h before
        # the 2026-09-04T17:00 departure.
        res = api.sign_out_leave(ctx["leave"]["id"], make_front_desk_headers(fd["id"]))
        validate_error(res, ApiErrorId.ERR_SIGN_OUT_WINDOW)

    def test_cancel_from_returned_returns_invalid_state(self, api):
        """PRD §3.4: "`DENIED`, `CANCELLED`, `EXPIRED`, and `RETURNED` are terminal."
        PRD §2.6: "the system check whether the target resource sits in a
        legitimate from-state for the requested transition (`ERR_INVALID_STATE`,
        HTTP 409)".
        PRD §3.4: "computes `late_return_minutes` as the whole minutes by which
        the actual return exceeded the planned `returns_at` (never below zero)".

        Design: Corner/state_machines/leave_cancel_from_returned_returns_invalid_state
        """
        ctx = setup_leave_approved(grade=12)
        fd = make_front_desk()
        set_clock("2026-09-04T18:00:00Z")
        validate_success(api.sign_out_leave(ctx["leave"]["id"],
                                            make_front_desk_headers(fd["id"])), 200)
        set_clock("2026-09-06T18:00:00Z")  # one hour before planned return
        returned = validate_success(api.return_leave(
            ctx["leave"]["id"], make_front_desk_headers(fd["id"])), 200)
        assert returned["status"] == "RETURNED"
        assert returned["late_return_minutes"] == 0

        res = api.cancel_leave(ctx["leave"]["id"],
                               make_student_headers(ctx["student"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestLeaveFilingGates:
    def test_leave_departing_in_the_past_rejected(self, api):
        """PRD §3.4: "a `departs_at` that must lie in the future
        (`ERR_LEAVE_IN_PAST`)".

        Design: Corner/validations/leave_in_past_rejected
        """
        make_active_term()
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="MALE", legal_name="Stu O")
        res = api.create_leave_request(
            create_leave_request_payload(leave_type="DAY_PASS", destination="Town",
                                         departs_at="2026-07-01T13:00:00Z",
                                         returns_at="2026-07-01T17:00:00Z"),
            make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_LEAVE_IN_PAST)

    def test_leave_filing_without_active_term_rejected(self, api):
        """PRD §3.1: "Term activation, assignment creation, assignment
        confirmation, leave creation, night checks, and sign events all require
        an `ACTIVE` term to exist; their absence surfaces as `ERR_TERM_NOT_ACTIVE`."

        Design: Corner/validations/leave_without_active_term_rejected
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=12, gender="FEMALE",
                               legal_name="Stu Z")
        res = api.create_leave_request(
            create_leave_request_payload(), make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_TERM_NOT_ACTIVE)

    def test_on_leave_student_cannot_file_leave(self, api, admin_headers):
        """PRD §3.4: "Filing requires an `ACTIVE` term and an `ENROLLED` student."
        PRD §5 pairs the enrollment failure with `ERR_STUDENT_NOT_ENROLLED`
        (HTTP 409).

        Design: Corner/validations/on_leave_student_cannot_request_leave
        """
        make_active_term()
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="MALE", legal_name="Stu AA")
        validate_success(api.set_student_enrollment(student["id"], "ON_LEAVE",
                                                    admin_headers), 200)
        res = api.create_leave_request(
            create_leave_request_payload(leave_type="DAY_PASS", destination="Town",
                                         departs_at="2026-09-09T13:00:00Z",
                                         returns_at="2026-09-09T17:00:00Z"),
            make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_STUDENT_NOT_ENROLLED)


class TestDormDecisionStandingGate:
    def test_suspended_student_day_pass_dorm_decision_rejected(self, api):
        """PRD §3.4: "Approval is refused when the student's standing is
        `SUSPENDED` (`ERR_STUDENT_SUSPENDED`)".

        Design: Corner/validations/suspended_student_day_pass_dorm_decision_rejected
        """
        ctx = setup_confirmed_residency(grade=12)
        reporter = make_dean("Dean One")
        decider = make_dean("Dean Two")
        case = report_case(ctx["student"]["id"], reporter["id"], category="MINOR",
                           description="Accumulated violations", points_proposed=20)
        sanction_minor_case(case["id"], reporter["id"], decider["id"],
                            20, sanction_type="SUSPENSION")
        student = get_student(ctx["student"]["id"])
        assert student["discipline_standing"] == "SUSPENDED"

        # DAY_PASS filed after the sanction; family approves; dorm must refuse.
        leave = file_leave(ctx["student"]["id"], leave_type="DAY_PASS",
                           destination="Dentist",
                           departs_at="2026-09-09T13:00:00Z",
                           returns_at="2026-09-09T17:00:00Z")
        parent_approve_leave(leave["id"], ctx["parent"]["id"])
        res = api.dorm_decision(leave["id"], "APPROVE",
                                make_dorm_parent_headers(ctx["dorm_parent"]["id"]))
        validate_error(res, ApiErrorId.ERR_STUDENT_SUSPENDED)


class TestFamilyDecisionOwnership:
    def test_parent_deciding_other_childs_leave_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of
        the acting `Parent`; family decisions on leave requests are authorized
        only for students whose `parent_id` equals `X-User-ID`."
        PRD §2.1: "A request whose role is not in the endpoint's authorized list,
        or that violates the ownership and scoping rules below, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/parent_decides_other_childs_leave_forbidden
        """
        make_active_term()
        par_a = make_parent()
        par_b = make_parent()
        stu_b = make_student(par_b["id"], grade=12, gender="FEMALE", legal_name="Stu B")
        leave_b = file_leave(stu_b["id"], destination="Home")

        res = api.parent_decision(leave_b["id"], "APPROVE",
                                  make_parent_headers(par_a["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
