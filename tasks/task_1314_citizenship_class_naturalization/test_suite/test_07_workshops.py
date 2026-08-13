"""Legal-supervised workshops: seats, completion, reversal, cancellation (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_workshop,
    assert_workshop_seat,
    complete_workshop,
    create_general_volunteer,
    create_legal_volunteer,
    create_packet,
    create_program,
    create_screened_applicant,
    create_workshop,
    get_volunteer,
    get_workshop,
    get_workshop_seat,
    make_volunteer_headers,
    reserve_seat,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]


class TestWorkshopCompletion:
    def test_workshop_complete_before_start_rejected(self, api):
        """PRD §3.6: "Two guards apply: the supervising volunteer must hold `LEGAL`
        accreditation at completion time (`ERR_ACCREDITATION_LAPSED` when it has
        lapsed, `ERR_ACCREDITATION_INSUFFICIENT` otherwise), and the clock must be at
        or after `scheduled_start` (`ERR_WORKSHOP_NOT_YET_HELD`)."

        Design: Corner/endpoints/workshop_complete_before_start_rejected
        """
        create_program()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-20T10:00:00Z",
                                   duration_hours=2, capacity=3)
        # Clock is still the default 2026-08-01, strictly before the scheduled start.
        response = api.complete_workshop(
            workshop["id"], make_volunteer_headers(supervisor["id"])
        )
        validate_error(response, ApiErrorId.ERR_WORKSHOP_NOT_YET_HELD)
        assert get_workshop(workshop["id"])["status"] == "SCHEDULED"

    def test_workshop_complete_lapsed_supervisor_safety_beats_temporal(self, api):
        """PRD §2.9: "Validations on a request execute in a fixed priority order, and
        an earlier failure masks every later check."
        PRD §2.9: "8. **Accreditation lapse.** A required accreditation that exists
        but has lapsed at check time rejects as `ERR_ACCREDITATION_LAPSED` (HTTP 409)."
        PRD §2.9: "10. **Temporal guards.** Screening validity, workshop start, and
        ceremony date, rejecting as `ERR_SCREENING_EXPIRED`,
        `ERR_WORKSHOP_NOT_YET_HELD`, or `ERR_CEREMONY_NOT_YET_HELD` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/workshop_complete_lapsed_supervisor_safety_beats_temporal
        """
        create_program()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        # Scheduled in the future relative to the post-jump clock: both the lapse
        # guard (accredited 2026-08-01 + 24 months < 2028-08-15) and the temporal
        # guard (clock 2028-08-15 < start 2028-09-01) could fire.
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2028-09-01T10:00:00Z",
                                   duration_hours=2, capacity=4,
                                   title="Future Workshop")
        set_clock("2028-08-15T00:00:00Z")
        assert get_volunteer(supervisor["id"])["accreditation_level"] == "LAPSED"

        response = api.complete_workshop(workshop["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_ACCREDITATION_LAPSED)
        assert get_workshop(workshop["id"])["status"] == "SCHEDULED"

    def test_workshop_complete_lapsed_supervisor_after_start_still_rejected(self, api):
        """PRD §3.6: "Two guards apply: the supervising volunteer must hold `LEGAL`
        accreditation at completion time (`ERR_ACCREDITATION_LAPSED` when it has
        lapsed, `ERR_ACCREDITATION_INSUFFICIENT` otherwise), and the clock must be at
        or after `scheduled_start` (`ERR_WORKSHOP_NOT_YET_HELD`)."

        Design: Difficulty/priority_pair_validation_conflict/workshop_complete_lapsed_supervisor_safety_beats_temporal
        """
        create_program()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-05T10:00:00Z",
                                   duration_hours=2, capacity=4)
        # Clock well past the scheduled start, but also past the 24-month
        # accreditation anniversary: only the lapse guard can fail.
        set_clock("2028-08-15T00:00:00Z")
        assert get_volunteer(supervisor["id"])["accreditation_level"] == "LAPSED"

        response = api.complete_workshop(workshop["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_ACCREDITATION_LAPSED)
        assert get_workshop(workshop["id"])["status"] == "SCHEDULED"


class TestWorkshopSeats:
    def test_workshop_seat_reserve_when_full_rejected(self, api):
        """PRD §3.6: "The applicant must hold an unexpired `ACTIVE` screening with
        outcome `ELIGIBLE` or `ELIGIBLE_WITH_EXEMPTION` (`ERR_SCREENING_NOT_ELIGIBLE`,
        `ERR_SCREENING_EXPIRED`), and a workshop whose `reserved_count` already equals
        its `capacity` rejects further reservations with `ERR_WORKSHOP_FULL`."

        Design: Corner/endpoints/workshop_seat_reserve_when_full_rejected
        """
        create_program()
        applicant_a, _ = create_screened_applicant()
        applicant_b, _ = create_screened_applicant()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-20T10:00:00Z",
                                   duration_hours=2, capacity=1)
        seat = reserve_seat(workshop["id"], applicant_a["id"])
        assert_workshop_seat(seat)
        assert seat["status"] == "RESERVED"
        assert get_workshop(workshop["id"])["reserved_count"] == 1

        # Fresh version, so the concurrency guard passes and the capacity rule fires.
        current = get_workshop(workshop["id"])
        response = api.reserve_workshop_seat(
            workshop["id"],
            {"applicant_id": applicant_b["id"],
             "expected_workshop_version": current["version"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_WORKSHOP_FULL)
        assert get_workshop(workshop["id"])["reserved_count"] == 1


class TestWorkshopCancelAndReverse:
    def test_workshop_cancel_cascades_reserved_seats(self, api):
        """PRD §3.6: "Separately, a `ProgramAdmin` may cancel a `SCHEDULED` workshop
        (`ERR_INVALID_STATE` otherwise): every `RESERVED` seat moves to `CANCELLED`
        and the workshop itself becomes `CANCELLED`."

        Design: Corner/state_machines/workshop_cancel_cascades_reserved_seats
        """
        create_program()
        applicant, _ = create_screened_applicant()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-20T10:00:00Z",
                                   duration_hours=2, capacity=3)
        seat = reserve_seat(workshop["id"], applicant["id"])

        cancelled = validate_success(api.cancel_workshop(workshop["id"], ADMIN), 200)
        assert_workshop(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["reserved_count"] == 0
        assert get_workshop_seat(seat["id"])["status"] == "CANCELLED"

    def test_workshop_reverse_completion_locked_by_packet(self, api):
        """PRD §3.6: "Reversal is the compensating action, available to a
        `ProgramAdmin` only, and only while no application packet references any of
        the workshop's seats — once a packet cites a seat, completion is locked in and
        reversal rejects with `ERR_COMPLETION_LOCKED`."

        Design: Corner/endpoints/workshop_reverse_completion_locked_by_packet
        """
        create_program()
        applicant, _ = create_screened_applicant()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-05T10:00:00Z",
                                   duration_hours=3, capacity=5)
        seat = reserve_seat(workshop["id"], applicant["id"])
        complete_workshop(workshop["id"], supervisor["id"], at="2026-08-05T10:00:00Z")
        assert get_workshop_seat(seat["id"])["status"] == "ATTENDED"

        packet = create_packet(applicant["id"], seat["id"], supervisor["id"])
        assert packet["status"] == "DRAFT"

        response = api.reverse_workshop_completion(workshop["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_COMPLETION_LOCKED)
        assert get_workshop(workshop["id"])["status"] == "COMPLETED"
        assert get_workshop_seat(seat["id"])["status"] == "ATTENDED"


class TestSupervisedHoursConservation:
    def test_supervised_hours_complete_reverse_conservation(self, api):
        """PRD §3.6: "Reversal moves every `ATTENDED` seat to `REVERSED`, debits the
        assisting volunteer's `supervised_hours` by exactly `duration_hours` — the
        precise inverse of the earlier credit, so a completion followed by a reversal
        leaves the ledger with no drift — and moves the workshop terminally to
        `COMPLETION_REVERSED`."

        Design: Difficulty/compensating_invariant/supervised_hours_complete_reverse_conservation
        """
        create_program()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        assistant = create_general_volunteer(full_name="Asst Vol")
        workshop = create_workshop(supervisor["id"],
                                   assisting_volunteer_id=assistant["id"],
                                   scheduled_start="2026-08-05T10:00:00Z",
                                   duration_hours=3, capacity=3,
                                   title="Apprentice WS")
        assert get_volunteer(assistant["id"])["supervised_hours"] == 0

        completed = complete_workshop(workshop["id"], supervisor["id"],
                                      at="2026-08-05T10:00:00Z")
        assert completed["status"] == "COMPLETED"
        assert get_volunteer(assistant["id"])["supervised_hours"] == 3, (
            "completion credits duration_hours to the assistant"
        )

        reversed_workshop = validate_success(
            api.reverse_workshop_completion(workshop["id"], ADMIN), 200
        )
        assert reversed_workshop["status"] == "COMPLETION_REVERSED"
        assert get_volunteer(assistant["id"])["supervised_hours"] == 0, (
            "the complete/reverse pair conserves supervised_hours exactly"
        )

    def test_supervised_hours_partial_reversal_keeps_other_credit(self, api):
        """PRD §3.6: "Reversal moves every `ATTENDED` seat to `REVERSED`, debits the
        assisting volunteer's `supervised_hours` by exactly `duration_hours` — the
        precise inverse of the earlier credit, so a completion followed by a reversal
        leaves the ledger with no drift — and moves the workshop terminally to
        `COMPLETION_REVERSED`."

        Design: Difficulty/compensating_invariant/supervised_hours_complete_reverse_conservation
        """
        create_program()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        assistant = create_general_volunteer(full_name="Asst Vol")
        workshop_5 = create_workshop(supervisor["id"],
                                     assisting_volunteer_id=assistant["id"],
                                     scheduled_start="2026-08-05T10:00:00Z",
                                     duration_hours=5, capacity=3, title="WS5")
        workshop_3 = create_workshop(supervisor["id"],
                                     assisting_volunteer_id=assistant["id"],
                                     scheduled_start="2026-08-06T10:00:00Z",
                                     duration_hours=3, capacity=3, title="WS3")
        set_clock("2026-08-06T11:00:00Z")
        complete_workshop(workshop_5["id"], supervisor["id"])
        complete_workshop(workshop_3["id"], supervisor["id"])
        assert get_volunteer(assistant["id"])["supervised_hours"] == 8

        validate_success(api.reverse_workshop_completion(workshop_5["id"], ADMIN), 200)
        assistant_after = get_volunteer(assistant["id"])
        assert assistant_after["supervised_hours"] == 3, (
            "reversing the 5-hour workshop debits exactly 5, leaving the 3-hour credit"
        )
        assert get_workshop(workshop_5["id"])["status"] == "COMPLETION_REVERSED"
        assert get_workshop(workshop_3["id"])["status"] == "COMPLETED"
