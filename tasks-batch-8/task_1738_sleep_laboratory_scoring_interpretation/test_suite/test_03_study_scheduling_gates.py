"""Study-booking gates: order state, study-type coherence, bed rules,
authorization windows, and check-in timing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_staffing,
    create_authorized_order,
    create_bed,
    create_order,
    create_patient,
    create_technologist,
    decide_authorization,
    get_order,
    get_study,
    make_sleep_technologist_headers,
    plan_staffing,
    schedule_study,
    setup_study_scheduled,
    submit_authorization,
    validate_error,
    validate_paginated,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]

WIDE_WINDOW = {"window_start": "2026-08-01", "window_end": "2026-08-31"}


class TestBedRulesByStudyType:
    def test_hst_study_rejects_bed_id(self, api):
        """PRD: "`PSG_DIAGNOSTIC`, `SPLIT_NIGHT`, and `TITRATION_PAP` studies
        require a `bed_id` (`ERR_BED_REQUIRED_FOR_IN_LAB`), while an `HST`
        study must not carry one (`ERR_BED_NOT_ALLOWED_FOR_HST`)."

        Design: Corner/entities/hst_study_rejects_bed_id
        """
        bed = create_bed()
        patient = create_patient()
        order = create_authorized_order(patient["id"], "HST")["order"]

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "HST", "scheduled_date": "2026-08-01",
             "bed_id": bed["id"]},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_BED_NOT_ALLOWED_FOR_HST, 400)

        _, meta = validate_paginated(
            api.list_sleep_studies(SCHED, {"order_id": order["id"]}))
        assert meta["total_count"] == 0

    def test_psg_study_requires_bed_id(self, api):
        """PRD: "`PSG_DIAGNOSTIC`, `SPLIT_NIGHT`, and `TITRATION_PAP` studies
        require a `bed_id` (`ERR_BED_REQUIRED_FOR_IN_LAB`), while an `HST`
        study must not carry one (`ERR_BED_NOT_ALLOWED_FOR_HST`)."

        Design: Corner/entities/psg_study_requires_bed_id
        """
        patient = create_patient()
        order = create_authorized_order(patient["id"], "PSG_DIAGNOSTIC")["order"]

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "PSG_DIAGNOSTIC", "scheduled_date": "2026-08-01"},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_BED_REQUIRED_FOR_IN_LAB, 400)

    def test_inactive_bed_rejected(self, api):
        """PRD: "The referenced bed must be active (`ERR_BED_INACTIVE`), and
        `TITRATION_PAP` and `SPLIT_NIGHT` additionally require a
        `titration_capable` bed (`ERR_BED_NOT_TITRATION_CAPABLE`)."

        Design: Corner/validations/inactive_bed_rejected
        """
        bed = create_bed(is_active=False)
        patient = create_patient()
        order = create_authorized_order(patient["id"], "PSG_DIAGNOSTIC")["order"]

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "PSG_DIAGNOSTIC", "scheduled_date": "2026-08-01",
             "bed_id": bed["id"]},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_BED_INACTIVE, 422)

    def test_titration_study_requires_capable_bed(self, api):
        """PRD: "`TITRATION_PAP` and `SPLIT_NIGHT` additionally require a
        `titration_capable` bed (`ERR_BED_NOT_TITRATION_CAPABLE`)."

        Design: Corner/validations/titration_study_requires_capable_bed
        """
        bed = create_bed(titration_capable=False)
        patient = create_patient()
        order = create_authorized_order(patient["id"], "TITRATION_PAP")["order"]

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "TITRATION_PAP", "scheduled_date": "2026-08-01",
             "bed_id": bed["id"]},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_BED_NOT_TITRATION_CAPABLE, 422)


class TestStudyTypeCoherence:
    def test_study_type_mismatch_rejected(self, api):
        """PRD: "The payload's `patient_id` must be the patient the order
        belongs to, and the `study_type` must equal the order's
        `requested_study_type` (`ERR_STUDY_TYPE_MISMATCH`)."

        Design: Corner/validations/study_type_mismatch_rejected
        """
        patient = create_patient()
        order = create_authorized_order(patient["id"], "PSG_DIAGNOSTIC")["order"]

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "HST", "scheduled_date": "2026-08-01"},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_TYPE_MISMATCH, 422)


class TestOrderStateGate:
    def test_scheduling_auth_denied_order_rejected(self, api):
        """PRD: "A `Scheduler` books a **SleepStudy** against an `AUTHORIZED`
        order — any other order state is rejected with
        `ERR_ORDER_NOT_AUTHORIZED`."

        Design: Difficulty/cross_entity_state_dependency/study_scheduling_requires_authorized_order
        """
        patient = create_patient()
        order = create_order(patient["id"], requested_study_type="HST")
        auth = submit_authorization(order)
        decide_authorization(auth["id"], "DENIED")
        assert get_order(order["id"])["status"] == "AUTH_DENIED"

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "HST", "scheduled_date": "2026-08-01"},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_AUTHORIZED, 409)

        assert get_order(order["id"])["status"] == "AUTH_DENIED", (
            "The rejected booking leaves the order state untouched")
        _, meta = validate_paginated(
            api.list_sleep_studies(SCHED, {"order_id": order["id"]}))
        assert meta["total_count"] == 0

    def test_scheduling_received_order_rejected(self, api):
        """PRD: "A `Scheduler` books a **SleepStudy** against an `AUTHORIZED`
        order — any other order state is rejected with
        `ERR_ORDER_NOT_AUTHORIZED`." A fresh order still in `RECEIVED` has
        never been authorized, so the same gate fires.

        Design: Difficulty/cross_entity_state_dependency/study_scheduling_requires_authorized_order
        """
        patient = create_patient()
        order = create_order(patient["id"], requested_study_type="HST")
        assert order["status"] == "RECEIVED"

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order["id"],
             "study_type": "HST", "scheduled_date": "2026-08-01"},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_AUTHORIZED, 409)


class TestTemporalWindowAndBedConflictOrdering:
    def _occupied_bed_setup(self):
        """Bed occupied 2026-08-20 by one PSG study; order A authorized with a
        window that does NOT cover 2026-08-20."""
        tech = create_technologist()
        bed = create_bed()
        confirm_staffing(
            plan_staffing(tech["id"], "2026-08-20", patient_capacity=2))
        patient = create_patient()
        order_a = create_authorized_order(
            patient["id"], "PSG_DIAGNOSTIC",
            window_start="2026-08-01", window_end="2026-08-10")["order"]
        order_b = create_authorized_order(
            patient["id"], "PSG_DIAGNOSTIC", **WIDE_WINDOW)["order"]
        occupant = schedule_study(order_b["id"], patient["id"],
                                  "PSG_DIAGNOSTIC", scheduled_date="2026-08-20",
                                  bed_id=bed["id"])
        return bed, patient, order_a, occupant

    def test_temporal_violation_beats_bed_conflict(self, api):
        """PRD: "Temporally, the `scheduled_date` must fall within the approved
        authorization's `window_start`-to-`window_end` window, inclusive on
        both ends; a date outside the window is rejected with
        `ERR_AUTH_WINDOW_VIOLATION`, and this temporal check runs before the
        bed-night conflict check."

        Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_bed_conflict
        """
        bed, patient, order_a, _ = self._occupied_bed_setup()

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order_a["id"],
             "study_type": "PSG_DIAGNOSTIC", "scheduled_date": "2026-08-20",
             "bed_id": bed["id"]},
            SCHED,
        )
        # Both violations are present (outside the window AND the bed is
        # occupied that night); the temporal check runs first.
        validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_VIOLATION, 422)

        _, meta = validate_paginated(api.list_sleep_studies(
            SCHED, {"bed_id": bed["id"], "scheduled_date": "2026-08-20"}))
        assert meta["total_count"] == 1

    def test_bed_conflict_fires_when_window_satisfied(self, api):
        """PRD: "Temporally, the `scheduled_date` must fall within the approved
        authorization's `window_start`-to-`window_end` window, inclusive on
        both ends; a date outside the window is rejected with
        `ERR_AUTH_WINDOW_VIOLATION`, and this temporal check runs before the
        bed-night conflict check."
        PRD: "The bed-night itself must be free: the same `bed_id` and
        `scheduled_date` may not be held by another study in `SCHEDULED` or
        `IN_PROGRESS` (`ERR_BED_NIGHT_CONFLICT`)." With the window satisfied,
        the bed-night check is the one that fires.

        Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_bed_conflict
        """
        bed, patient, _, _ = self._occupied_bed_setup()
        order_c = create_authorized_order(
            patient["id"], "PSG_DIAGNOSTIC", **WIDE_WINDOW)["order"]

        resp = api.create_sleep_study(
            {"patient_id": patient["id"], "order_id": order_c["id"],
             "study_type": "PSG_DIAGNOSTIC", "scheduled_date": "2026-08-20",
             "bed_id": bed["id"]},
            SCHED,
        )
        validate_error(resp, ApiErrorId.ERR_BED_NIGHT_CONFLICT, 409)


class TestCheckInTiming:
    def test_checkin_wrong_date_rejected(self, api):
        """PRD: "Check-in requires the study to be `SCHEDULED` and the logical
        clock's UTC calendar date to equal the `scheduled_date`; a date
        mismatch is rejected with `ERR_STUDY_NOT_TONIGHT`"

        Design: Corner/validations/checkin_wrong_date_rejected
        """
        # Logical clock untouched at its 2026-08-01 startup default; the study
        # is booked for the following night.
        ws = setup_study_scheduled(study_type="HST",
                                   scheduled_date="2026-08-02")

        resp = api.check_in_study(
            ws["study"]["id"],
            make_sleep_technologist_headers(ws["technologist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_TONIGHT, 422)

        assert get_study(ws["study"]["id"])["status"] == "SCHEDULED"
