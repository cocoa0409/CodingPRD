"""Class sections, enrollments, and the pinned seat ledger (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_class_section,
    assert_enrollment,
    assert_same_instant,
    assert_seat_ledger_invariants,
    create_general_volunteer,
    create_program,
    create_screened_applicant,
    create_section,
    enroll,
    get_enrollment,
    get_section,
    register_applicant,
    set_clock,
    setup_section_with_enrollees,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]


def _waitlist_scenario():
    """Section with capacity 1: applicant A ENROLLED, then B and C WAITLISTED
    (B created before C)."""
    return setup_section_with_enrollees(
        capacity=1, num_applicants=3, total_sessions=10,
        weekday="WED", start_minute=700, end_minute=760, room_id="R6",
    )


class TestRoomOverlap:
    def test_class_section_room_halfopen_adjacency(self, api):
        """PRD §3.4: "A section occupies its room on its weekday over the half-open
        window from `start_minute` up to but not including `end_minute`; another
        section on the same weekday whose window intersects it in the same `room_id`
        is rejected with `ERR_SCHEDULE_CONFLICT`, while back-to-back meetings — one
        starting at exactly the minute another ends — are permitted."

        Design: Difficulty/resource_temporal_overlap/class_section_room_halfopen_adjacency
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        first = create_section(instructor["id"], title="S1", weekday="MON",
                               start_minute=600, end_minute=660, room_id="R1",
                               capacity=10)
        assert_class_section(first)

        # Back-to-back: [660, 720) starts exactly when [600, 660) ends — not an
        # overlap under half-open semantics.
        adjacent = validate_success(
            api.create_class_section(
                {"title": "S2", "weekday": "MON", "start_minute": 660,
                 "end_minute": 720, "room_id": "R1",
                 "instructor_volunteer_id": instructor["id"], "capacity": 10,
                 "total_sessions": 10},
                ADMIN,
            ),
            201,
        )
        assert_class_section(adjacent)

        # [630, 690) truly intersects [600, 660) in the same room on the same weekday.
        overlapping = api.create_class_section(
            {"title": "S3", "weekday": "MON", "start_minute": 630, "end_minute": 690,
             "room_id": "R1", "instructor_volunteer_id": instructor["id"],
             "capacity": 10, "total_sessions": 10},
            ADMIN,
        )
        validate_error(overlapping, ApiErrorId.ERR_SCHEDULE_CONFLICT)

    def test_class_section_overlap_scoped_per_room_and_weekday(self, api):
        """PRD §3.4: "A section occupies its room on its weekday over the half-open
        window from `start_minute` up to but not including `end_minute`; another
        section on the same weekday whose window intersects it in the same `room_id`
        is rejected with `ERR_SCHEDULE_CONFLICT`, while back-to-back meetings — one
        starting at exactly the minute another ends — are permitted."

        Design: Difficulty/resource_temporal_overlap/class_section_room_halfopen_adjacency
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        create_section(instructor["id"], title="S1", weekday="MON",
                       start_minute=600, end_minute=660, room_id="R1", capacity=10)

        # Same intersecting window, different room: outside the rule's scope.
        other_room = validate_success(
            api.create_class_section(
                {"title": "S4", "weekday": "MON", "start_minute": 630,
                 "end_minute": 690, "room_id": "R2",
                 "instructor_volunteer_id": instructor["id"], "capacity": 10,
                 "total_sessions": 10},
                ADMIN,
            ),
            201,
        )
        assert other_room["room_id"] == "R2"

        # Same room and window, different weekday: also outside the rule's scope.
        other_day = validate_success(
            api.create_class_section(
                {"title": "S5", "weekday": "TUE", "start_minute": 630,
                 "end_minute": 690, "room_id": "R1",
                 "instructor_volunteer_id": instructor["id"], "capacity": 10,
                 "total_sessions": 10},
                ADMIN,
            ),
            201,
        )
        assert other_day["weekday"] == "TUE"


class TestEnrollmentScreeningGate:
    def test_enrollment_rejected_when_screening_missing_or_not_eligible(self, api):
        """PRD §3.4: "The applicant must hold an `ACTIVE` screening whose outcome is
        `ELIGIBLE` or `ELIGIBLE_WITH_EXEMPTION` — a missing, `NOT_ELIGIBLE`, or
        `NEEDS_REVIEW` screening rejects with `ERR_SCREENING_NOT_ELIGIBLE` — and that
        screening must not have expired (`ERR_SCREENING_EXPIRED`)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_gated_by_screening_outcome_and_expiry
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], title="Open", weekday="THU",
                                 start_minute=600, end_minute=660, room_id="R5",
                                 capacity=4, total_sessions=8)
        # Three failure flavours, each isolated so only the outcome gate can fail.
        no_screening = register_applicant(full_name="No Screening")
        not_eligible, _ = create_screened_applicant(continuous_residence_months=40)
        needs_review, _ = create_screened_applicant(has_legal_flag=True)

        for applicant in (no_screening, not_eligible, needs_review):
            response = api.create_enrollment(
                {"applicant_id": applicant["id"], "class_section_id": section["id"],
                 "expected_section_version": get_section(section["id"])["version"]},
                COORD,
            )
            validate_error(response, ApiErrorId.ERR_SCREENING_NOT_ELIGIBLE)

        assert get_section(section["id"])["enrolled_count"] == 0

    def test_enrollment_rejected_when_screening_expired(self, api):
        """PRD §3.2: "A screening remains valid only while `expires_at` is strictly
        later than the current clock reading; once the clock reaches or passes
        `expires_at`, operations that require a live screening reject with
        `ERR_SCREENING_EXPIRED`."
        PRD §3.4: "The applicant must hold an `ACTIVE` screening whose outcome is
        `ELIGIBLE` or `ELIGIBLE_WITH_EXEMPTION` — a missing, `NOT_ELIGIBLE`, or
        `NEEDS_REVIEW` screening rejects with `ERR_SCREENING_NOT_ELIGIBLE` — and that
        screening must not have expired (`ERR_SCREENING_EXPIRED`)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_gated_by_screening_outcome_and_expiry
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], title="Open", weekday="THU",
                                 start_minute=600, end_minute=660, room_id="R5",
                                 capacity=4, total_sessions=8)
        applicant, screening = create_screened_applicant()
        assert screening["outcome"] == "ELIGIBLE"
        # Born at the default clock 2026-08-01, so expires_at is 2027-01-28; advancing
        # to 2027-01-29 puts the clock past expiry.
        assert_same_instant(screening["expires_at"], "2027-01-28T00:00:00Z")
        set_clock("2027-01-29T00:00:00Z")

        response = api.create_enrollment(
            {"applicant_id": applicant["id"], "class_section_id": section["id"],
             "expected_section_version": get_section(section["id"])["version"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_SCREENING_EXPIRED)
        assert get_section(section["id"])["enrolled_count"] == 0


class TestEnrollmentDuplicateActive:
    def test_enrollment_duplicate_active_rejected(self, api):
        """PRD §3.4: "An applicant may hold at most one live enrollment in a given
        section: an existing `ENROLLED`, `WAITLISTED`, or `PENDING_PROMOTION`
        enrollment for the same pairing rejects with
        `ERR_ENROLLMENT_DUPLICATE_ACTIVE`."

        Design: Corner/endpoints/enrollment_duplicate_active_rejected
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=3, total_sessions=10)
        applicant, _ = create_screened_applicant()
        enrollment = enroll(applicant["id"], section["id"])
        assert enrollment["status"] == "ENROLLED"

        response = api.create_enrollment(
            {"applicant_id": applicant["id"], "class_section_id": section["id"],
             "expected_section_version": get_section(section["id"])["version"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_ENROLLMENT_DUPLICATE_ACTIVE)


class TestPromotionEvaluationOrder:
    def test_seat_ledger_promotion_evaluation_order(self, api):
        """PRD §3.4: "`enrolled_count` is the number of `ENROLLED` enrollments in the
        section; `pending_promotion_count` is the number of `PENDING_PROMOTION`
        enrollments, because an outstanding promotion offer holds its seat;
        `seats_open` is `capacity` minus `enrolled_count` minus
        `pending_promotion_count`, evaluated in that order."
        PRD §3.4: "Whenever a seat opens in a section with a waitlist — through
        withdrawal, midterm revocation, or an expiring offer — the system promotes
        that section's `WAITLISTED` enrollment with the earliest `created_at` to
        `PENDING_PROMOTION`, decrementing `waitlisted_count`, incrementing
        `pending_promotion_count`, and stamping `offer_expires_at` at the clock plus
        `promotion_offer_hours`."

        Design: Difficulty/combinatorial_formula/seat_ledger_promotion_evaluation_order
        """
        scenario = _waitlist_scenario()
        section = scenario["section"]
        enrollment_a, enrollment_b, enrollment_c = scenario["enrollments"]
        assert enrollment_a["status"] == "ENROLLED"
        assert enrollment_b["status"] == "WAITLISTED"
        assert enrollment_c["status"] == "WAITLISTED"

        validate_success(api.withdraw_enrollment(enrollment_a["id"], COORD), 200)

        promoted = get_enrollment(enrollment_b["id"])
        assert promoted["status"] == "PENDING_PROMOTION", (
            "the earliest-created WAITLISTED enrollment wins the freed seat"
        )
        assert_same_instant(
            promoted["offer_expires_at"], "2026-08-04T00:00:00Z",
            "offer_expires_at must be the clock (2026-08-01) plus 72 hours",
        )
        still_waiting = get_enrollment(enrollment_c["id"])
        assert still_waiting["status"] == "WAITLISTED", (
            "the pending promotion holds the seat, so no second promotion is issued"
        )

        section_after = get_section(section["id"])
        assert section_after["enrolled_count"] == 0
        assert section_after["pending_promotion_count"] == 1
        assert section_after["waitlisted_count"] == 1
        assert section_after["seats_open"] == 0
        assert_seat_ledger_invariants(section_after)

    def test_seat_ledger_confirm_promotion_settles_ledger(self, api):
        """PRD §3.4: "The offeree — or a coordinator on their behalf — confirms while
        the enrollment is `PENDING_PROMOTION` (`ERR_INVALID_STATE` otherwise):
        `pending_promotion_count` decrements, `enrolled_count` increments,
        `offer_expires_at` clears to null, and the enrollment becomes `ENROLLED`."
        PRD §3.4: "When an applicant whose stage is `SCREENED` first reaches
        `ENROLLED` — whether directly or by confirming a promotion — the stage
        advances automatically to `IN_PIPELINE`."

        Design: Difficulty/combinatorial_formula/seat_ledger_promotion_evaluation_order
        """
        scenario = _waitlist_scenario()
        section = scenario["section"]
        enrollment_a, enrollment_b, enrollment_c = scenario["enrollments"]
        applicant_b = scenario["applicants"][1]
        validate_success(api.withdraw_enrollment(enrollment_a["id"], COORD), 200)

        confirmed = validate_success(
            api.confirm_promotion(enrollment_b["id"], COORD), 200
        )
        assert_enrollment(confirmed)
        assert confirmed["status"] == "ENROLLED"
        assert confirmed["offer_expires_at"] is None

        section_after = get_section(section["id"])
        assert section_after["enrolled_count"] == 1
        assert section_after["pending_promotion_count"] == 0
        assert section_after["waitlisted_count"] == 1
        assert section_after["seats_open"] == 0
        assert get_enrollment(enrollment_c["id"])["status"] == "WAITLISTED"

        applicant_b_after = api.get_applicant(applicant_b["id"], COORD).json()["data"]
        assert applicant_b_after["stage"] == "IN_PIPELINE", (
            "confirming a promotion is the applicant's first ENROLLED moment"
        )


class TestSeatLedgerConservation:
    def test_seat_ledger_enroll_withdraw_conservation(self, api):
        """PRD §3.4: "The invariant is compensating and exact: `enrolled_count` equals
        the true count of `ENROLLED` rows at all times, with enrollment, withdrawal,
        revocation, and promotion confirmation each adjusting it by one in the
        appropriate direction."
        PRD §3.4: "Withdrawal is the voluntary exit: an `ENROLLED` enrollment may be
        withdrawn by the applicant or an `IntakeCoordinator` (`ERR_INVALID_STATE` in
        any other status), decrementing `enrolled_count` and freeing the seat for
        promotion selection."

        Design: Difficulty/compensating_invariant/seat_ledger_enroll_withdraw_conservation
        """
        scenario = setup_section_with_enrollees(
            capacity=2, num_applicants=2, total_sessions=10,
            weekday="FRI", start_minute=600, end_minute=660, room_id="R7",
        )
        section = scenario["section"]
        enrollment_a, _ = scenario["enrollments"]
        applicant_a = scenario["applicants"][0]
        assert get_section(section["id"])["enrolled_count"] == 2

        withdrawn = validate_success(
            api.withdraw_enrollment(enrollment_a["id"], COORD), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_section(section["id"])["enrolled_count"] == 1, (
            "withdrawal applies the -1 compensation exactly once"
        )

        re_enrolled = enroll(applicant_a["id"], section["id"])
        assert re_enrolled["status"] == "ENROLLED"
        assert re_enrolled["id"] != enrollment_a["id"], (
            "re-enrollment creates a new row; the withdrawn row is not resurrected"
        )
        assert get_enrollment(enrollment_a["id"])["status"] == "WITHDRAWN"

        section_after = get_section(section["id"])
        assert section_after["enrolled_count"] == 2
        assert section_after["seats_open"] == 0

        rows, meta = validate_paginated(
            api.list_enrollments(
                COORD,
                params={"class_section_id": section["id"], "status": "ENROLLED"},
            )
        )
        assert meta["total_count"] == 2 == section_after["enrolled_count"], (
            "the derived counter must reconcile with the authoritative filtered list"
        )
        assert len(rows) == 2

    def test_seat_ledger_withdraw_promote_confirm_chain_conserves(self, api):
        """PRD §3.4: "The invariant is compensating and exact: `enrolled_count` equals
        the true count of `ENROLLED` rows at all times, with enrollment, withdrawal,
        revocation, and promotion confirmation each adjusting it by one in the
        appropriate direction."
        PRD §3.4: "Whenever a seat opens in a section with a waitlist — through
        withdrawal, midterm revocation, or an expiring offer — the system promotes
        that section's `WAITLISTED` enrollment with the earliest `created_at` to
        `PENDING_PROMOTION`, decrementing `waitlisted_count`, incrementing
        `pending_promotion_count`, and stamping `offer_expires_at` at the clock plus
        `promotion_offer_hours`."

        Design: Difficulty/compensating_invariant/seat_ledger_enroll_withdraw_conservation
        """
        scenario = setup_section_with_enrollees(
            capacity=1, num_applicants=2, total_sessions=10,
            weekday="FRI", start_minute=700, end_minute=760, room_id="R8",
        )
        section = scenario["section"]
        enrollment_a, enrollment_b = scenario["enrollments"]
        assert enrollment_b["status"] == "WAITLISTED"

        validate_success(api.withdraw_enrollment(enrollment_a["id"], COORD), 200)
        section_after_withdraw = get_section(section["id"])
        assert section_after_withdraw["enrolled_count"] == 0
        assert section_after_withdraw["waitlisted_count"] == 0
        assert section_after_withdraw["pending_promotion_count"] == 1
        assert section_after_withdraw["seats_open"] == 0
        pending_rows, pending_meta = validate_paginated(
            api.list_enrollments(
                COORD,
                params={"class_section_id": section["id"], "status": "PENDING_PROMOTION"},
            )
        )
        assert pending_meta["total_count"] == 1
        assert pending_rows[0]["id"] == enrollment_b["id"]

        validate_success(api.confirm_promotion(enrollment_b["id"], COORD), 200)
        section_final = get_section(section["id"])
        assert section_final["enrolled_count"] == 1
        assert section_final["pending_promotion_count"] == 0
        assert section_final["seats_open"] == 0
        enrolled_rows, enrolled_meta = validate_paginated(
            api.list_enrollments(
                COORD,
                params={"class_section_id": section["id"], "status": "ENROLLED"},
            )
        )
        assert enrolled_meta["total_count"] == section_final["enrolled_count"] == 1
        assert enrolled_rows[0]["id"] == enrollment_b["id"]


class TestPromotionExpirySweep:
    def test_promotion_expiry_sweep_auto_withdraws_and_promotes_next(self, api):
        """PRD §2.5: "A waitlist promotion offer whose `offer_expires_at` falls
        strictly earlier than the new clock reading is auto-declined, and each freed
        seat immediately re-runs waitlist promotion selection as described in §3.4. An
        offer expiring exactly at the clock reading survives."
        PRD §3.4: "An offer the clock sweep passes is auto-declined: the enrollment
        moves terminally to `WITHDRAWN`, `pending_promotion_count` decrements,
        `offer_expires_at` clears, and the freed seat immediately re-runs promotion
        selection for the next waiting enrollment."

        Design: Corner/state_machines/promotion_expiry_sweep_auto_withdraws_and_promotes_next
        """
        scenario = _waitlist_scenario()
        section = scenario["section"]
        enrollment_a, enrollment_b, enrollment_c = scenario["enrollments"]
        validate_success(api.withdraw_enrollment(enrollment_a["id"], COORD), 200)
        assert_same_instant(
            get_enrollment(enrollment_b["id"])["offer_expires_at"],
            "2026-08-04T00:00:00Z",
        )

        # At exactly offer_expires_at the offer survives (the sweep is strictly <).
        set_clock("2026-08-04T00:00:00Z")
        assert get_enrollment(enrollment_b["id"])["status"] == "PENDING_PROMOTION"

        # One second past expiry: B auto-withdraws terminally, C is promoted with a
        # fresh 72-hour offer stamped from the sweep time.
        set_clock("2026-08-04T00:00:01Z")
        declined = get_enrollment(enrollment_b["id"])
        assert declined["status"] == "WITHDRAWN"
        assert declined["offer_expires_at"] is None

        promoted = get_enrollment(enrollment_c["id"])
        assert promoted["status"] == "PENDING_PROMOTION"
        assert_same_instant(promoted["offer_expires_at"], "2026-08-07T00:00:01Z")

        section_after = get_section(section["id"])
        assert section_after["enrolled_count"] == 0
        assert section_after["pending_promotion_count"] == 1
        assert section_after["waitlisted_count"] == 0
        assert_seat_ledger_invariants(section_after)
