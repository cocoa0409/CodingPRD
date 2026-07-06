"""Cascades, ratio-ceiling boundaries, refund edge, and conserved-quantity
invariants.

Queue A: rule_id=transitive_cascade, boundary_precision_check,
compensating_invariant.
"""
from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    setup_catalog, create_student_with_waiver, create_school, create_student,
    create_equipment, create_paid_enrollment, create_paid_withdrawn_enrollment,
    create_enrollment, create_session, book, attend_session, set_clock,
    create_rental, create_membership,
)

ADMIN = TEST_USERS["admin_headers"]


# ============================================================================
# rule_id=transitive_cascade
# ============================================================================
class TestWithdrawCascadeDepth3:
    """withdraw -> booking CANCELLED -> session enrolled_count down ->
    required_instructors recomputed."""

    def _three_booked_session(self):
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 2})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        students = [create_student_with_waiver(school["id"], full_name=n) for n in ("A", "B", "C")]
        enrs = [create_enrollment(school["id"], s["id"], level["id"],
                                  planned_sessions=1, party_size=1) for s in students]
        sess = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                            tide_window_start="2026-03-10T08:00:00Z",
                            tide_window_end="2026-03-10T12:00:00Z", capacity=6)
        v = sess["version"]
        for e in enrs:
            bk = book(sess["id"], e["id"], v)
            v = get_success_data(api_client.get_session(sess["id"], ADMIN))["version"]
        return sess["id"], enrs[2]["id"]

    def test_withdraw_cancels_booking_and_drops_enrolled_count(self, api):
        """PRD §3.5: "It moves `progress_status` to `WITHDRAWN` and cascades:
        every booking on this enrollment that is `BOOKED` or `CHECKED_IN` is
        cancelled."

        Design: Difficulty/transitive_cascade/enrollment_withdraw_cancels_booking_recomputes_session_ratio_depth3
        """
        sid, enr_c = self._three_booked_session()
        get_success_data(api.withdraw_enrollment(enr_c, ADMIN))
        sess = validate_success(api.get_session(sid, ADMIN), 200)
        assert sess["enrolled_count"] == 2, \
            f"cancelling one of three bookings drops enrolled_count to 2: got {sess['enrolled_count']}"

    def test_withdraw_recomputes_required_instructors(self, api):
        """PRD §3.5: "Each cancelled booking in turn decrements its session's
        `enrolled_count` and triggers a recompute of that session's
        `required_instructors`."

        Design: Difficulty/transitive_cascade/enrollment_withdraw_cancels_booking_recomputes_session_ratio_depth3
        """
        sid, enr_c = self._three_booked_session()
        get_success_data(api.withdraw_enrollment(enr_c, ADMIN))
        sess = validate_success(api.get_session(sid, ADMIN), 200)
        # ceil(3/2)=2 before -> ceil(2/2)=1 after.
        assert sess["required_instructors"] == 1, \
            f"required_instructors recomputed ceil(2/2)=1: got {sess['required_instructors']}"


class TestCompleteAttendanceCascadeDepth2:
    """complete(session) -> booking CHECKED_IN -> ATTENDED ->
    enrollment.attended_count bumped."""

    def _checked_in_session(self):
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student_with_waiver(school["id"])
        enr = create_enrollment(school["id"], student["id"], level["id"],
                                planned_sessions=1, party_size=1)
        sess = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                            tide_window_start="2026-03-05T08:00:00Z",
                            tide_window_end="2026-03-05T12:00:00Z", capacity=4)
        bk = book(sess["id"], enr["id"], sess["version"])
        set_clock("2026-03-05T08:30:00Z")
        get_success_data(api_client.start_session(sess["id"], ADMIN))
        get_success_data(api_client.check_in_booking(bk["id"], ADMIN))
        return sess["id"], bk["id"], enr["id"]

    def test_complete_marks_checked_in_attended(self, api):
        """PRD §3.6: "Each booking that was `CHECKED_IN` becomes `ATTENDED`, and
        the owning enrollment's `attended_count` rises by one for each."

        Design: Difficulty/transitive_cascade/session_complete_marks_attended_bumps_enrollment_count_depth2
        """
        sid, bk_id, _ = self._checked_in_session()
        get_success_data(api.complete_session(sid, ADMIN))
        bk = validate_success(api.get_booking(bk_id, ADMIN), 200)
        assert bk["status"] == "ATTENDED", \
            f"checked-in booking becomes ATTENDED on completion: got {bk['status']}"

    def test_complete_bumps_attended_count(self, api):
        """PRD §3.6: "Each booking that was `CHECKED_IN` becomes `ATTENDED`, and
        the owning enrollment's `attended_count` rises by one for each."

        Design: Difficulty/transitive_cascade/session_complete_marks_attended_bumps_enrollment_count_depth2
        """
        sid, _, enr_id = self._checked_in_session()
        get_success_data(api.complete_session(sid, ADMIN))
        enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
        assert enr["attended_count"] == 1, \
            f"attended_count rises from 0 to 1: got {enr['attended_count']}"


# ============================================================================
# rule_id=boundary_precision_check
# ============================================================================
class TestRatioCeilingBoundary:

    def test_third_booking_crosses_ratio_ceiling(self, api):
        """PRD §3.8: "The boundary lands on exact multiples: when the enrolled
        count equals the cap exactly, one instructor is required; one student
        beyond the cap requires two."

        Design: Difficulty/boundary_precision_check/ratio_ceiling_boundary_at_exact_multiple
        """
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 2})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        students = [create_student_with_waiver(school["id"], full_name=n) for n in ("A", "B", "C")]
        enrs = [create_enrollment(school["id"], s["id"], level["id"],
                                  planned_sessions=1, party_size=1) for s in students]
        sess = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                            tide_window_start="2026-03-10T08:00:00Z",
                            tide_window_end="2026-03-10T12:00:00Z", capacity=6)
        v = sess["version"]
        bk1 = book(sess["id"], enrs[0]["id"], v)
        v = get_success_data(api.get_session(sess["id"], ADMIN))["version"]
        bk2 = book(sess["id"], enrs[1]["id"], v)
        v = get_success_data(api.get_session(sess["id"], ADMIN))["version"]
        # At 2/2 the ratio ceiling is exactly 1 instructor.
        at_cap = validate_success(api.get_session(sess["id"], ADMIN), 200)
        assert at_cap["required_instructors"] == 1, \
            f"enrolled==max (2/2) -> 1 instructor: got {at_cap['required_instructors']}"
        # Adding a 3rd booking crosses to 2.
        book(sess["id"], enrs[2]["id"], v)
        over = validate_success(api.get_session(sess["id"], ADMIN), 200)
        assert over["enrolled_count"] == 3
        assert over["required_instructors"] == 2, \
            f"enrolled==max+1 (3/2) -> 2 instructors: got {over['required_instructors']}"

    def test_ratio_ceiling_at_exactly_cap(self, api):
        """PRD §3.8: "the session's `required_instructors` is recomputed as the
        `enrolled_count` divided by the level's `max_students_per_instructor`,
        rounded up to the next whole number (ceiling), with the special case
        that an `enrolled_count` of 0 yields 0."

        Design: Difficulty/boundary_precision_check/ratio_ceiling_boundary_at_exact_multiple
        """
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 2})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        s1 = create_student_with_waiver(school["id"], full_name="A")
        s2 = create_student_with_waiver(school["id"], full_name="B")
        e1 = create_enrollment(school["id"], s1["id"], level["id"], planned_sessions=1, party_size=1)
        e2 = create_enrollment(school["id"], s2["id"], level["id"], planned_sessions=1, party_size=1)
        sess = create_session(school["id"], level["id"], inst["id"],
                            starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                            tide_window_start="2026-03-10T08:00:00Z",
                            tide_window_end="2026-03-10T12:00:00Z", capacity=6)
        book(sess["id"], e1["id"], sess["version"])
        v = get_success_data(api.get_session(sess["id"], ADMIN))["version"]
        book(sess["id"], e2["id"], v)
        data = validate_success(api.get_session(sess["id"], ADMIN), 200)
        assert data["enrolled_count"] == 2
        assert data["required_instructors"] == 1


class TestRefundEmptyRemainingFullRefund:

    def test_no_remaining_sessions_yields_full_refund(self, api):
        """PRD §3.8: "If there are no such remaining bookings, the lead time is
        treated as effectively infinite (which lands in the top tier)."

        Design: Difficulty/boundary_precision_check/refund_lead_time_empty_remaining_sessions_full_refund
        """
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={
            "max_students_per_instructor": 4, "base_price_cents": 10000,
            "min_age": 0, "requires_swim_test": False, "required_equipment_type": "NONE"})
        school, level = cat["school"], cat["level"]
        student = create_student_with_waiver(school["id"])
        # planned 1, party 1, no member -> estimate 10000. No bookings at all.
        enr = create_paid_withdrawn_enrollment(school["id"], student["id"], level["id"],
                                               planned_sessions=1, party_size=1)
        data = validate_success(api.refund_enrollment(enr["id"], ADMIN), 200)
        assert data["refund_cents"] == 10000, \
            f"no remaining bookings -> full refund 10000: got {data['refund_cents']}"

    def test_refund_sets_payment_refunded(self, api):
        """PRD §3.5: "On success, `payment_status` becomes `REFUNDED` and
        `refund_cents` is computed by the lead-time waterfall (see §3.8)."

        Design: Difficulty/boundary_precision_check/refund_lead_time_empty_remaining_sessions_full_refund
        """
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={
            "max_students_per_instructor": 4, "base_price_cents": 10000,
            "min_age": 0, "requires_swim_test": False, "required_equipment_type": "NONE"})
        school, level = cat["school"], cat["level"]
        student = create_student_with_waiver(school["id"])
        enr = create_paid_withdrawn_enrollment(school["id"], student["id"], level["id"],
                                               planned_sessions=1, party_size=1)
        data = validate_success(api.refund_enrollment(enr["id"], ADMIN), 200)
        assert data["payment_status"] == "REFUNDED"


# ============================================================================
# rule_id=compensating_invariant
# ============================================================================
class TestMakeupCreditConservation:

    def test_cancel_grants_then_makeup_consumes_returns_to_zero(self, api):
        """PRD §3.6: "for each cancelled booking whose enrollment carries an
        active membership, that membership's `makeup_credit_balance` rises by
        one, because a school-caused cancellation grants the member a makeup."
        PRD §3.7: "on success the booking's `is_makeup` is set true and the
        membership's `makeup_credit_balance` falls by one."

        Design: Difficulty/compensating_invariant/makeup_credit_conserved_cancel_grants_then_makeup_consumes
        """
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student_with_waiver(school["id"])
        mem = create_membership(student["id"], tier="PREMIUM")
        enr = create_enrollment(school["id"], student["id"], level["id"],
                                membership_id=mem["id"], planned_sessions=2, party_size=1)
        sess_a = create_session(school["id"], level["id"], inst["id"],
                              starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                              tide_window_start="2026-03-05T08:00:00Z",
                              tide_window_end="2026-03-05T12:00:00Z", capacity=4)
        sess_b = create_session(school["id"], level["id"], inst["id"],
                              starts_at="2026-03-12T09:00:00Z", ends_at="2026-03-12T10:00:00Z",
                              tide_window_start="2026-03-12T08:00:00Z",
                              tide_window_end="2026-03-12T12:00:00Z", capacity=4)
        book(sess_a["id"], enr["id"], sess_a["version"])
        get_success_data(api.cancel_session(sess_a["id"], ADMIN))
        after_cancel = validate_success(api.get_membership(mem["id"], ADMIN), 200)
        assert after_cancel["makeup_credit_balance"] == 1, \
            f"school cancel grants +1 makeup credit: got {after_cancel['makeup_credit_balance']}"
        # Consume it via a makeup booking on session B.
        bkB = book(sess_b["id"], enr["id"], sess_b["version"], use_makeup_credit=True)
        final = validate_success(api.get_membership(mem["id"], ADMIN), 200)
        assert final["makeup_credit_balance"] == 0, \
            f"makeup booking consumes the credit back to 0: got {final['makeup_credit_balance']}"
        assert bkB["is_makeup"] is True

    def test_makeup_booking_flagged_is_makeup(self, api):
        """PRD §3.7: "When `use_makeup_credit` is true, the owning enrollment's
        membership must have a `makeup_credit_balance` of at least 1, or the
        booking is rejected with `ERR_NO_MAKEUP_CREDIT`; on success the
        booking's `is_makeup` is set true and the membership's
        `makeup_credit_balance` falls by one."

        Design: Difficulty/compensating_invariant/makeup_credit_conserved_cancel_grants_then_makeup_consumes
        """
        set_clock("2026-03-01T00:00:00Z")
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level, inst = cat["school"], cat["level"], cat["instructor"]
        student = create_student_with_waiver(school["id"])
        mem = create_membership(student["id"], tier="PREMIUM")
        enr = create_enrollment(school["id"], student["id"], level["id"],
                                membership_id=mem["id"], planned_sessions=2, party_size=1)
        sess_a = create_session(school["id"], level["id"], inst["id"],
                              starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                              tide_window_start="2026-03-05T08:00:00Z",
                              tide_window_end="2026-03-05T12:00:00Z", capacity=4)
        sess_b = create_session(school["id"], level["id"], inst["id"],
                              starts_at="2026-03-12T09:00:00Z", ends_at="2026-03-12T10:00:00Z",
                              tide_window_start="2026-03-12T08:00:00Z",
                              tide_window_end="2026-03-12T12:00:00Z", capacity=4)
        book(sess_a["id"], enr["id"], sess_a["version"])
        get_success_data(api.cancel_session(sess_a["id"], ADMIN))
        res = api.create_booking({"session_id": sess_b["id"], "enrollment_id": enr["id"],
                                  "expected_session_version": sess_b["version"],
                                  "use_makeup_credit": True}, ADMIN)
        data = validate_success(res, 201)
        assert data["is_makeup"] is True, "makeup booking flags is_makeup true"


class TestEquipmentAvailabilityConservation:

    def test_checkout_then_return_leaves_available(self, api):
        """PRD §3.9: "Returning the rental, again by administrator or owning
        student, moves it from `ACTIVE` to `RETURNED`, moves the equipment item
        back to `AVAILABLE` (incrementing its `version`), and releases the held
        deposit back to the student."

        Design: Difficulty/compensating_invariant/equipment_availability_conserved_checkout_then_return
        """
        set_clock("2026-03-03T00:00:00Z")
        school = create_school(name="Av School")
        student = create_student(school["id"], full_name="Leo")
        equipment = create_equipment(school["id"], equipment_type="BOARD",
                                     asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=5000)
        rental = create_rental(school["id"], student["id"], equipment["id"], equipment["version"],
                               starts_at="2026-03-02T09:00:00Z", ends_at="2026-03-02T12:00:00Z")
        get_success_data(api.checkout_rental(rental["id"], ADMIN))
        get_success_data(api.return_rental(rental["id"], ADMIN))
        item = validate_success(api.get_equipment(equipment["id"], ADMIN), 200)
        assert item["status"] == "AVAILABLE", \
            f"checkout+return leaves equipment AVAILABLE: got {item['status']}"

    def test_return_marks_rental_returned(self, api):
        """PRD §3.9: "Returning the rental, again by administrator or owning
        student, moves it from `ACTIVE` to `RETURNED`."

        Design: Difficulty/compensating_invariant/equipment_availability_conserved_checkout_then_return
        """
        set_clock("2026-03-03T00:00:00Z")
        school = create_school(name="Av School")
        student = create_student(school["id"], full_name="Leo")
        equipment = create_equipment(school["id"], equipment_type="BOARD",
                                     asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=5000)
        rental = create_rental(school["id"], student["id"], equipment["id"], equipment["version"],
                               starts_at="2026-03-02T09:00:00Z", ends_at="2026-03-02T12:00:00Z")
        get_success_data(api.checkout_rental(rental["id"], ADMIN))
        data = validate_success(api.return_rental(rental["id"], ADMIN), 200)
        assert data["status"] == "RETURNED"
