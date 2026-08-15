"""Bed and technologist registry, staffing assignments, and the night-capacity
arithmetic (pairwise bed-night exclusion and aggregate capacity)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_staffing_assignment,
    confirm_staffing,
    create_authorized_order,
    create_bed,
    create_order,
    create_patient,
    create_technologist,
    get_order,
    get_success_data,
    make_sleep_technologist_headers,
    plan_staffing,
    schedule_study,
    validate_error,
    validate_paginated,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]

WINDOW = {"window_start": "2026-08-01", "window_end": "2026-08-31"}


def _psg_order(patient_id, nights=1):
    return create_authorized_order(patient_id, "PSG_DIAGNOSTIC",
                                   approved_nights=nights, **WINDOW)["order"]


class TestRegistryDefaults:
    def test_defaults_applied_on_staffing_and_order_create(self, api):
        """PRD: "An optional `priority` defaults to `ROUTINE`" and "A new order
        begins in `RECEIVED` status with its `no_show_count` at zero".
        PRD: "Each **Bed** is registered with a unique `room_label`, a
        `titration_capable` flag (default false) marking beds wired for PAP
        titration equipment, and an `is_active` flag (default true) controlling
        schedulability."
        PRD: "Night coverage is planned through **StaffingAssignment** records,
        each pairing a `technologist_id` with a `shift_date` and a
        `patient_capacity` — the maximum number of in-lab patients that
        technologist covers that night, between one and four, defaulting to two
        under the AASM 2:1 ratio. An assignment begins `PLANNED`"

        Design: Corner/entities/defaults_applied_on_staffing_and_order_create
        """
        tech = create_technologist(credential="CPSGT")
        patient = create_patient()
        bed = create_bed()
        assert bed["titration_capable"] is False
        assert bed["is_active"] is True

        assignment = plan_staffing(tech["id"], "2026-08-03")
        assert_staffing_assignment(assignment)
        assert assignment["patient_capacity"] == 2, (
            "Omitted patient_capacity defaults to the AASM 2:1 ratio")
        assert assignment["status"] == "PLANNED"

        order = create_order(patient["id"], requested_study_type="HST")
        assert order["priority"] == "ROUTINE"
        assert order["no_show_count"] == 0
        assert order["status"] == "RECEIVED"


class TestStaffingAssignments:
    def test_technologist_double_booking_rejected(self, api):
        """PRD: "a technologist may hold only one non-`CANCELLED` assignment
        per `shift_date`; a second plan for the same technologist and night is
        rejected with `ERR_TECH_DOUBLE_BOOKED`."

        Design: Corner/errors/technologist_double_booking_rejected
        """
        tech = create_technologist()
        plan_staffing(tech["id"], "2026-08-03", patient_capacity=2)

        resp = api.create_staffing_assignment(
            {"technologist_id": tech["id"], "shift_date": "2026-08-03",
             "patient_capacity": 1},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED, 409)

        _, meta = validate_paginated(api.list_staffing_assignments(
            DIRECTOR, {"technologist_id": tech["id"],
                       "shift_date": "2026-08-03"}))
        assert meta["total_count"] == 1

    def test_staffing_confirm_by_other_technologist_forbidden(self, api):
        """PRD: "Confirmation is personal: only the assigned technologist may
        confirm the shift, meaning `X-User-ID` must equal the assignment's
        `technologist_id` (`ERR_STAFFING_NOT_OWN`)"

        Design: Corner/validations/staffing_confirm_by_other_technologist_forbidden
        """
        tech1 = create_technologist()
        tech2 = create_technologist(credential="CPSGT")
        assignment = plan_staffing(tech1["id"], "2026-08-03")

        resp = api.confirm_staffing_assignment(
            assignment["id"], make_sleep_technologist_headers(tech2["id"]))
        validate_error(resp, ApiErrorId.ERR_STAFFING_NOT_OWN, 403)

        reread = get_success_data(
            api.get_staffing_assignment(assignment["id"], DIRECTOR))
        assert reread["status"] == "PLANNED"

    def test_staffing_double_confirm_rejected(self, api):
        """PRD: "only a `PLANNED` assignment can be confirmed
        (`ERR_STAFFING_INVALID_STATE`)."

        Design: Corner/validations/staffing_double_confirm_rejected
        """
        tech = create_technologist()
        assignment = confirm_staffing(plan_staffing(tech["id"], "2026-08-03"))
        assert assignment["status"] == "CONFIRMED"

        resp = api.confirm_staffing_assignment(
            assignment["id"], make_sleep_technologist_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_STAFFING_INVALID_STATE, 409)


class TestBedNightPairwiseExclusion:
    def _night_with_held_bed(self, date="2026-08-05"):
        """Bed B held by one SCHEDULED PSG study on `date`; a second
        AUTHORIZED PSG order is ready to book."""
        tech = create_technologist()
        bed = create_bed()
        confirm_staffing(plan_staffing(tech["id"], date, patient_capacity=2))
        patient = create_patient()
        order_a = _psg_order(patient["id"])
        study_a = schedule_study(order_a["id"], patient["id"],
                                 "PSG_DIAGNOSTIC", scheduled_date=date,
                                 bed_id=bed["id"])
        order_b = _psg_order(patient["id"])
        return tech, bed, patient, order_a, study_a, order_b

    def test_bed_night_conflict_rejected(self, api):
        """PRD: "The bed-night itself must be free: the same `bed_id` and
        `scheduled_date` may not be held by another study in `SCHEDULED` or
        `IN_PROGRESS` (`ERR_BED_NIGHT_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/bed_night_pairwise_exclusion
        """
        _, bed, patient, _, study_a, order_b = self._night_with_held_bed()

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order_b["id"],
             "study_type": "PSG_DIAGNOSTIC", "scheduled_date": "2026-08-05",
             "bed_id": bed["id"]},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_BED_NIGHT_CONFLICT, 409)

        data, meta = validate_paginated(api.list_sleep_studies(
            SCHED, {"bed_id": bed["id"], "scheduled_date": "2026-08-05"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == study_a["id"]

    def test_bed_night_adjacent_night_free(self, api):
        """PRD: "The bed-night itself must be free: the same `bed_id` and
        `scheduled_date` may not be held by another study in `SCHEDULED` or
        `IN_PROGRESS` (`ERR_BED_NIGHT_CONFLICT`)." — the exclusion is keyed on
        the night, so the same bed on the adjacent night is schedulable.

        Design: Difficulty/resource_temporal_overlap/bed_night_pairwise_exclusion
        """
        tech, bed, patient, _, study_a, order_b = self._night_with_held_bed()
        confirm_staffing(plan_staffing(tech["id"], "2026-08-06",
                                       patient_capacity=2))

        study_b = schedule_study(order_b["id"], patient["id"],
                                 "PSG_DIAGNOSTIC", scheduled_date="2026-08-06",
                                 bed_id=bed["id"])
        assert study_b["status"] == "SCHEDULED"
        assert study_b["id"] != study_a["id"]


class TestAggregateCapacityCeiling:
    def test_third_study_exceeds_confirmed_capacity(self, api):
        """PRD: "Scheduling an in-lab study is only permitted when the occupied
        count plus one does not exceed the confirmed capacity — an occupied
        count exactly equal to capacity means the night is full, and the
        scheduling attempt is rejected with `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/staffing_aggregate_capacity_ceiling
        """
        date = "2026-08-04"
        tech = create_technologist()
        beds = [create_bed() for _ in range(3)]
        confirm_staffing(plan_staffing(tech["id"], date, patient_capacity=2))
        patient = create_patient()

        # Each order books exactly one study (booking moves the order out of
        # AUTHORIZED); three distinct beds keep the pairwise exclusion silent.
        studies = []
        for bed in beds[:2]:
            order = _psg_order(patient["id"])
            studies.append(schedule_study(order["id"], patient["id"],
                                          "PSG_DIAGNOSTIC", scheduled_date=date,
                                          bed_id=bed["id"]))
        assert all(s["status"] == "SCHEDULED" for s in studies), (
            "occupied == capacity (2 == 2) is still permitted — boundary "
            "inclusive")

        order_c = _psg_order(patient["id"])
        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order_c["id"],
             "study_type": "PSG_DIAGNOSTIC", "scheduled_date": date,
             "bed_id": beds[2]["id"]},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)

        _, meta = validate_paginated(
            api.list_sleep_studies(SCHED, {"scheduled_date": date}))
        assert meta["total_count"] == 2

    def test_no_confirmed_capacity_rejects_first_in_lab_booking(self, api):
        """PRD: "The **confirmed capacity** of a date is the sum of
        `patient_capacity` over that date's `CONFIRMED` staffing assignments."
        PRD: "Scheduling an in-lab study is only permitted when the occupied
        count plus one does not exceed the confirmed capacity — an occupied
        count exactly equal to capacity means the night is full, and the
        scheduling attempt is rejected with `ERR_CAPACITY_EXCEEDED`." With no
        confirmed assignments the night's capacity is zero and the first
        in-lab booking already exceeds it.

        Design: Difficulty/resource_temporal_overlap/staffing_aggregate_capacity_ceiling
        """
        bed = create_bed()
        patient = create_patient()
        order = _psg_order(patient["id"])

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "PSG_DIAGNOSTIC", "scheduled_date": "2026-08-04",
             "bed_id": bed["id"]},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)


class TestStaffingCancelCapacityGuard:
    def test_confirmed_cancel_that_breaks_capacity_rejected(self, api):
        """PRD: "cancelling a `CONFIRMED` assignment is capacity-guarded:
        letting `c` be that assignment's `patient_capacity`, the cancellation
        is rejected with `ERR_CAPACITY_WOULD_BE_VIOLATED` unless the night's
        occupied in-lab count remains no greater than the remaining confirmed
        capacity after subtracting `c`."

        Design: Corner/errors/staffing_cancel_capacity_guard
        """
        date = "2026-08-04"
        tech1 = create_technologist()
        tech2 = create_technologist(credential="CPSGT")
        bed1, bed2 = create_bed(), create_bed()
        sa1 = confirm_staffing(
            plan_staffing(tech1["id"], date, patient_capacity=1))
        sa2 = confirm_staffing(
            plan_staffing(tech2["id"], date, patient_capacity=1))
        patient = create_patient()
        # Two single-study orders occupy both confirmed slots.
        order1 = _psg_order(patient["id"])
        schedule_study(order1["id"], patient["id"], "PSG_DIAGNOSTIC",
                       scheduled_date=date, bed_id=bed1["id"])
        order2 = _psg_order(patient["id"])
        schedule_study(order2["id"], patient["id"], "PSG_DIAGNOSTIC",
                       scheduled_date=date, bed_id=bed2["id"])

        resp = api.cancel_staffing_assignment(sa2["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_WOULD_BE_VIOLATED, 422)

        reread = get_success_data(
            api.get_staffing_assignment(sa2["id"], DIRECTOR))
        assert reread["status"] == "CONFIRMED", (
            "The guarded cancellation leaves the assignment confirmed")
        assert sa1["status"] == "CONFIRMED"


class TestBedNightOccupancyConservedAcrossCancel:
    def test_cancel_frees_the_slot_for_another_order(self, api):
        """PRD: "A `Scheduler` may cancel a `SCHEDULED` study, moving it to
        `CANCELLED` and, when the order is `SCHEDULED`, returning it to
        `AUTHORIZED`."
        PRD: "studies in `NO_SHOW`, `CANCELLED`, or `TECHNICAL_FAILURE` do not
        consume a night."

        Design: Difficulty/compensating_invariant/bed_night_occupancy_conserved_across_cancel
        """
        date = "2026-08-06"
        tech = create_technologist()
        bed = create_bed()
        confirm_staffing(plan_staffing(tech["id"], date, patient_capacity=2))
        patient = create_patient()
        order_a = _psg_order(patient["id"])
        study1 = schedule_study(order_a["id"], patient["id"], "PSG_DIAGNOSTIC",
                                scheduled_date=date, bed_id=bed["id"])
        order_b = _psg_order(patient["id"])

        cancelled = get_success_data(api.cancel_sleep_study(study1["id"], SCHED))
        assert cancelled["status"] == "CANCELLED"
        assert get_order(order_a["id"])["status"] == "AUTHORIZED", (
            "Cancelling the study returns the order to AUTHORIZED")

        _, meta = validate_paginated(api.list_sleep_studies(
            SCHED, {"bed_id": bed["id"], "scheduled_date": date,
                    "status": "SCHEDULED"}))
        assert meta["total_count"] == 0, (
            "The cancelled study no longer occupies the bed-night")

        study2 = schedule_study(order_b["id"], patient["id"], "PSG_DIAGNOSTIC",
                                scheduled_date=date, bed_id=bed["id"])
        assert study2["status"] == "SCHEDULED", (
            "Occupancy is restored to exactly one, so the slot is free")

    def test_cancel_frees_the_order_for_its_own_rebooking(self, api):
        """PRD: "A `Scheduler` may cancel a `SCHEDULED` study, moving it to
        `CANCELLED` and, when the order is `SCHEDULED`, returning it to
        `AUTHORIZED`."
        PRD: "studies in `NO_SHOW`, `CANCELLED`, or `TECHNICAL_FAILURE` do not
        consume a night." — the same order can immediately rebook the freed
        bed-night.

        Design: Difficulty/compensating_invariant/bed_night_occupancy_conserved_across_cancel
        """
        date = "2026-08-06"
        tech = create_technologist()
        bed = create_bed()
        confirm_staffing(plan_staffing(tech["id"], date, patient_capacity=2))
        patient = create_patient()
        order = _psg_order(patient["id"])
        study1 = schedule_study(order["id"], patient["id"], "PSG_DIAGNOSTIC",
                                scheduled_date=date, bed_id=bed["id"])

        get_success_data(api.cancel_sleep_study(study1["id"], SCHED))
        assert get_order(order["id"])["status"] == "AUTHORIZED"

        study2 = schedule_study(order["id"], patient["id"], "PSG_DIAGNOSTIC",
                                scheduled_date=date, bed_id=bed["id"])
        assert study2["status"] == "SCHEDULED"
        assert study2["id"] != study1["id"]
