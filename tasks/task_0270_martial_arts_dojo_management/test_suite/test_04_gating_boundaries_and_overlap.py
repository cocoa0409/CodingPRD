"""Promotion-test gating precedence, boundary precision (capacity, age division),
instructor double-booking on half-open intervals, and the validation corner
instances.

Covers difficulty rules priority_pair_validation_conflict (the legitimate
waiver-vs-balance pair), boundary_precision_check, and resource_temporal_overlap,
plus the validations corner section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    set_clock, create_program, create_member, create_instructor,
    create_program_with_simple_chain, create_program_single_terminal_rank,
    setup_enrolled_member, create_enrollment, create_class_session,
    request_private_lesson, register_tournament, place_pro_shop_order,
    make_member_headers, make_instructor_headers, member_version, TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]


class TestPromotionGatingPrecedence:
    """When a promotion-test request trips both the waiver gate (evaluated first) and
    the balance ceiling, the waiver error is reported."""

    def test_waiver_beats_balance_ceiling(self, api):
        """PRD §3.5: "When several of these could fail at once, they are evaluated in
        the order just given: waiver, then member-active, then rank-terminal, then
        balance ceiling, then attendance-and-days eligibility."

        Design: Difficulty/priority_pair_validation_conflict/waiver_vs_balance_on_promotion_test
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        # Member without a signed waiver.
        member = create_member(waiver_signed=False)
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        # Drive balance to 12000 (> 10000 ceiling) via a fulfilled pro-shop order
        # (white belt -> 0% discount, net == gross).
        order = place_pro_shop_order(member["id"], [{"sku": "GI", "unit_price_cents": 12000, "qty": 1}])
        get_success_data(api.fulfill_pro_shop_order(order["id"], FD))
        m_check = validate_success(api.get_member(member["id"], FD), 200)
        assert m_check["outstanding_balance_cents"] == 12000, m_check
        res = api.create_promotion_test(
            {"enrollment_id": enrollment["id"], "examiner_instructor_id": instructor["id"],
             "scheduled_for": "2026-01-03T00:00:00Z"},
            make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_WAIVER_NOT_SIGNED", 422)

    def test_waiver_gate_fires_in_isolation(self, api):
        """PRD §3.5: "the member must have signed the waiver, else
        `ERR_WAIVER_NOT_SIGNED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/waiver_vs_balance_on_promotion_test
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        member = create_member(waiver_signed=False)
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        res = api.create_promotion_test(
            {"enrollment_id": enrollment["id"], "examiner_instructor_id": instructor["id"],
             "scheduled_for": "2026-01-03T00:00:00Z"},
            make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_WAIVER_NOT_SIGNED", 422)


class TestClassCapacityBoundary:
    """Capacity uses confirmed_count + 1 > capacity (strict)."""

    def _setup_capacity_class(self, capacity, num_members):
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z", capacity=capacity)
        members = []
        for _ in range(num_members):
            m, enr = setup_enrolled_member(prog["id"])
            members.append((m, enr))
        return prog, session, members

    def test_checkin_at_capacity_succeeds(self, api):
        """PRD §3.4: "a check-in that would push `confirmed_count` past `capacity` —
        that is, where the new confirmed count would exceed the session's capacity —
        is rejected with `ERR_CLASS_FULL` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/class_capacity_exact_boundary
        """
        prog, session, members = self._setup_capacity_class(capacity=2, num_members=2)
        for m, enr in members:
            get_success_data(api.create_attendance(
                {"enrollment_id": enr["id"], "class_session_id": session["id"]},
                make_member_headers(m["id"])))
        sess = validate_success(api.get_class_session(session["id"], FD), 200)
        assert sess["confirmed_count"] == 2, sess

    def test_checkin_over_capacity_rejected(self, api):
        """PRD §3.4: "a check-in that would push `confirmed_count` past `capacity` ...
        is rejected with `ERR_CLASS_FULL` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/class_capacity_exact_boundary
        """
        prog, session, members = self._setup_capacity_class(capacity=2, num_members=3)
        for m, enr in members[:2]:
            get_success_data(api.create_attendance(
                {"enrollment_id": enr["id"], "class_session_id": session["id"]},
                make_member_headers(m["id"])))
        m3, enr3 = members[2]
        res = api.create_attendance(
            {"enrollment_id": enr3["id"], "class_session_id": session["id"]},
            make_member_headers(m3["id"]))
        validate_error(res, "ERR_CLASS_FULL", 409)


class TestTournamentDivisionBoundary:
    """Division boundaries are inclusive at the lower edge (>=18 is ADULT)."""

    def test_exactly_18_is_adult(self, api):
        """PRD §3.7: "The boundaries are inclusive at the lower edge: a competitor who
        turns exactly 18 on the event date is `ADULT`, not `TEEN`, and one who turns
        exactly 13 is `TEEN`, not `YOUTH`."

        Design: Difficulty/boundary_precision_check/tournament_division_age_exact_18_boundary
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        member = create_member(date_of_birth="2008-09-01")
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        reg = register_tournament(member["id"], enrollment["id"], "2026-09-01T00:00:00Z",
                                  tournament_name="Adult Cup")
        assert reg["division"] == "ADULT", reg
        assert reg["division"] != "TEEN", reg

    def test_one_day_before_18_is_teen(self, api):
        """PRD §3.7: "a competitor who turns exactly 18 on the event date is `ADULT`,
        not `TEEN`, and one who turns exactly 13 is `TEEN`, not `YOUTH`."

        Design: Difficulty/boundary_precision_check/tournament_division_age_exact_18_boundary
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        # Born 2008-09-02 -> on 2026-09-01 is 17 completed years (one day short of 18).
        member = create_member(date_of_birth="2008-09-02")
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        reg = register_tournament(member["id"], enrollment["id"], "2026-09-01T00:00:00Z",
                                  tournament_name="Teen Cup")
        assert reg["division"] == "TEEN", reg
        assert reg["division"] != "ADULT", reg

    def test_under_13_is_youth(self, api):
        """PRD §3.7: "the age in whole completed years is taken, and a competitor
        under 13 is `YOUTH`, one who is 13 to 17 is `TEEN`, one who is 18 to 39 is
        `ADULT`, and one who is 40 or older is `MASTERS`."

        Design: Corner/calculations/tournament_division_youth_under_13
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        member = create_member(date_of_birth="2018-06-01")
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        reg = register_tournament(member["id"], enrollment["id"], "2026-09-01T00:00:00Z",
                                  tournament_name="Kids Cup")
        assert reg["division"] == "YOUTH", reg


class TestInstructorDoubleBooking:
    """Class/lesson overlap on an instructor uses the half-open [starts_at, ends_at)
    interval; adjacency is allowed, true overlap is rejected."""

    def test_adjacent_class_allowed_overlap_rejected(self, api):
        """PRD §3.4: "overlap is judged on the half-open interval from `starts_at`
        (inclusive) to `ends_at` (exclusive), so back-to-back bookings that merely
        touch — one's `ends_at` equal to the next's `starts_at` — are allowed; a true
        overlap is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/class_session_overlap_half_open_on_instructor
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        create_class_session(prog["id"], instructor["id"],
                             "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z", capacity=5)
        # Adjacent 11:00-12:00 is allowed.
        adjacent = validate_success(api.create_class_session(
            {"program_id": prog["id"], "instructor_id": instructor["id"],
             "starts_at": "2026-01-05T11:00:00Z", "ends_at": "2026-01-05T12:00:00Z", "capacity": 5}, FD), 201)
        assert adjacent["status"] == "SCHEDULED", adjacent
        # Overlapping 10:30-11:30 is rejected.
        res = api.create_class_session(
            {"program_id": prog["id"], "instructor_id": instructor["id"],
             "starts_at": "2026-01-05T10:30:00Z", "ends_at": "2026-01-05T11:30:00Z", "capacity": 5}, FD)
        validate_error(res, "ERR_INSTRUCTOR_DOUBLE_BOOKED", 409)

    def test_back_to_back_classes_both_scheduled(self, api):
        """PRD §3.4: "back-to-back bookings that merely touch — one's `ends_at` equal
        to the next's `starts_at` — are allowed."

        Design: Difficulty/resource_temporal_overlap/class_session_overlap_half_open_on_instructor
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        first = create_class_session(prog["id"], instructor["id"],
                                     "2026-01-07T10:00:00Z", "2026-01-07T11:00:00Z", capacity=5)
        # Touching at 11:00 on both sides is allowed (half-open adjacency).
        before = validate_success(api.create_class_session(
            {"program_id": prog["id"], "instructor_id": instructor["id"],
             "starts_at": "2026-01-07T09:00:00Z", "ends_at": "2026-01-07T10:00:00Z", "capacity": 5}, FD), 201)
        assert before["status"] == "SCHEDULED", before
        assert first["status"] == "SCHEDULED", first

    def test_private_lesson_overlap_with_class_rejected_at_confirm(self, api):
        """PRD §3.7: "the lesson's interval does not overlap any of that instructor's
        other `CONFIRMED` private lessons or `SCHEDULED` class sessions — the same
        half-open `[starts_at, ends_at)` overlap test used for class scheduling, so
        adjacency is allowed and a true overlap is rejected with
        `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/private_lesson_overlap_vs_class_cross_resource
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member = create_member()
        create_class_session(prog["id"], instructor["id"],
                             "2026-01-06T10:00:00Z", "2026-01-06T11:00:00Z", capacity=5)
        lesson = request_private_lesson(member["id"], instructor["id"],
                                        "2026-01-06T10:30:00Z", "2026-01-06T11:30:00Z")
        res = api.confirm_private_lesson(lesson["id"], make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_INSTRUCTOR_DOUBLE_BOOKED", 409)
        after = validate_success(api.get_private_lesson(lesson["id"], FD), 200)
        assert after["status"] == "REQUESTED", after

    def test_private_lesson_adjacent_to_class_confirms(self, api):
        """PRD §3.7: "the same half-open `[starts_at, ends_at)` overlap test used for
        class scheduling, so adjacency is allowed and a true overlap is rejected with
        `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409); confirmation moves the lesson to
        `CONFIRMED`."

        Design: Difficulty/resource_temporal_overlap/private_lesson_overlap_vs_class_cross_resource
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member = create_member()
        create_class_session(prog["id"], instructor["id"],
                             "2026-01-06T10:00:00Z", "2026-01-06T11:00:00Z", capacity=5)
        # Lesson 11:00-12:00 merely touches the class's 11:00 end -> adjacency allowed.
        lesson = request_private_lesson(member["id"], instructor["id"],
                                        "2026-01-06T11:00:00Z", "2026-01-06T12:00:00Z")
        confirmed = validate_success(api.confirm_private_lesson(
            lesson["id"], make_instructor_headers(instructor["id"])), 200)
        assert confirmed["status"] == "CONFIRMED", confirmed


class TestSchedulingValidations:
    """Field-level and gate validations on create endpoints (PRD §2 / §3)."""

    def test_class_ends_before_starts_rejected(self, api):
        """PRD §3.4: "`ends_at` must be strictly after `starts_at`, or the request
        fails with `ERR_VALIDATION`, 422."

        Design: Corner/validations/classsession_ends_before_starts_returns_validation
        """
        prog = create_program()
        instructor = create_instructor()
        res = api.create_class_session(
            {"program_id": prog["id"], "instructor_id": instructor["id"],
             "starts_at": "2026-02-01T11:00:00Z", "ends_at": "2026-02-01T10:00:00Z", "capacity": 5}, FD)
        validate_error(res, "ERR_VALIDATION", 422)

    def test_pro_shop_empty_line_items_rejected(self, api):
        """PRD §3.7: "an empty `line_items`, or a line with a `qty` below 1 or a
        negative `unit_price_cents`, fails with `ERR_VALIDATION` (422)."

        Design: Corner/validations/proshop_empty_line_items_returns_validation
        """
        member = create_member()
        res = api.create_pro_shop_order(
            {"member_id": member["id"], "line_items": []}, make_member_headers(member["id"]))
        validate_error(res, "ERR_VALIDATION", 422)

    def test_contract_bad_term_months_rejected(self, api):
        """PRD §3.6: "a `term_months` chosen from 3, 6, 12, or 24 ... A `term_months`
        outside the allowed set or a `billing_anchor_day` outside 1 to 28 fails with
        `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/validations/contract_bad_term_months_returns_validation
        """
        prog = create_program()
        member = create_member()
        res = api.create_contract(
            {"member_id": member["id"], "program_id": prog["id"], "term_months": 5,
             "billing_anchor_day": 1, "expected_member_version": member["version"]}, FD)
        validate_error(res, "ERR_VALIDATION", 422)

    def test_attendance_program_mismatch_rejected(self, api):
        """PRD §3.4: "a check-in whose enrollment's `program_id` does not equal the
        session's `program_id` is rejected with `ERR_PROGRAM_MISMATCH` (HTTP 422)."

        Design: Corner/validations/attendance_program_mismatch_returns_program_mismatch
        """
        set_clock("2026-01-01T00:00:00Z")
        prog_a = create_program(discipline="BJJ")
        prog_b = create_program(discipline="JUDO")
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog_a["id"])
        session_b = create_class_session(prog_b["id"], instructor["id"],
                                         "2026-02-01T10:00:00Z", "2026-02-01T11:00:00Z", capacity=5)
        res = api.create_attendance(
            {"enrollment_id": enrollment["id"], "class_session_id": session_b["id"]},
            make_member_headers(member["id"]))
        validate_error(res, "ERR_PROGRAM_MISMATCH", 422)

    def test_duplicate_checkin_rejected(self, api):
        """PRD §3.4: "a member who already holds a `CONFIRMED` attendance for that
        session cannot check in twice, which is rejected with `ERR_ALREADY_CHECKED_IN`
        (HTTP 409)."

        Design: Corner/validations/duplicate_checkin_returns_already_checked_in
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-02-01T10:00:00Z", "2026-02-01T11:00:00Z", capacity=10)
        get_success_data(api.create_attendance(
            {"enrollment_id": enrollment["id"], "class_session_id": session["id"]},
            make_member_headers(member["id"])))
        res = api.create_attendance(
            {"enrollment_id": enrollment["id"], "class_session_id": session["id"]},
            make_member_headers(member["id"]))
        validate_error(res, "ERR_ALREADY_CHECKED_IN", 409)

    def test_tournament_event_in_past_rejected(self, api):
        """PRD §3.7: "the `event_date` must be strictly in the future relative to the
        current clock (else `ERR_EVENT_IN_PAST`, 422)."

        Design: Corner/validations/tournament_event_in_past_returns_event_in_past
        """
        set_clock("2026-06-01T00:00:00Z")
        prog = create_program()
        member, enrollment = setup_enrolled_member(prog["id"])
        res = api.create_tournament_registration(
            {"member_id": member["id"], "enrollment_id": enrollment["id"],
             "tournament_name": "Old Cup", "event_date": "2026-01-01T00:00:00Z"},
            make_member_headers(member["id"]))
        validate_error(res, "ERR_EVENT_IN_PAST", 422)

    def test_promotion_test_at_terminal_rank_rejected(self, api):
        """PRD §3.5: "an enrollment already at a terminal rank, or one that is not
        `ACTIVE`, is rejected with `ERR_RANK_TERMINAL` (HTTP 422)."

        Design: Corner/validations/promotion_test_at_terminal_rank_returns_rank_terminal
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_single_terminal_rank(code="ONLY", min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        res = api.create_promotion_test(
            {"enrollment_id": enrollment["id"], "examiner_instructor_id": instructor["id"],
             "scheduled_for": "2026-01-05T00:00:00Z"},
            make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_RANK_TERMINAL", 422)

    def test_promotion_test_not_eligible_rejected(self, api):
        """PRD §3.5: "the attendance-and-time eligibility must hold — specifically,
        `rank_attendance_count` at least `min_attendance_for_test` and whole days in
        rank at least `min_days_in_rank` — else `ERR_NOT_ELIGIBLE_FOR_TEST` (HTTP 422)."

        Design: Corner/validations/promotion_test_not_eligible_returns_not_eligible
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", min_attendance_for_test=5, min_days_in_rank=0)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        res = api.create_promotion_test(
            {"enrollment_id": enrollment["id"], "examiner_instructor_id": instructor["id"],
             "scheduled_for": "2026-01-05T00:00:00Z"},
            make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_NOT_ELIGIBLE_FOR_TEST", 422)

    def test_attendance_waiver_not_signed_rejected(self, api):
        """PRD §3.4: "a member whose `waiver_signed` is false is blocked with
        `ERR_WAIVER_NOT_SIGNED` (HTTP 422)."

        Design: Corner/validations/attendance_waiver_not_signed_returns_waiver_error
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member = create_member(waiver_signed=False)
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-02-01T10:00:00Z", "2026-02-01T11:00:00Z", capacity=10)
        res = api.create_attendance(
            {"enrollment_id": enrollment["id"], "class_session_id": session["id"]},
            make_member_headers(member["id"]))
        validate_error(res, "ERR_WAIVER_NOT_SIGNED", 422)
