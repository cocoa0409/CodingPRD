"""Consular processing: the six-per-day per-consulate quota, its point-in-time
(non-interval) semantics, terminal lockdown, and the guard battery."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_petition,
    create_grower,
    create_petition,
    create_petitioning_order,
    create_wage_determination,
    create_worker,
    file_petition,
    get_success_data,
    link_worker,
    schedule_appointment,
    set_clock,
    setup_active_order_pipeline,
    setup_approved_petition_with_linked_workers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
REVIEWER = TEST_USERS["program_reviewer_headers"]
VISA_OFFICER = TEST_USERS["visa_officer_headers"]


class TestDailyQuotaBoundary:
    def test_sixth_appointment_accepted_seventh_rejected(self, api):
        """PRD 3.4: "Each consulate processes at most six scheduled interviews per
        day: the server counts `SCHEDULED` appointments with the same
        `consulate_code` on the same `appointment_date` and accepts the booking
        only while that count is below six, so the sixth appointment of the day
        succeeds and the seventh is rejected with `ERR_CONSULATE_CAPACITY_FULL`;
        `CANCELLED` and `COMPLETED` appointments consume no slots."

        Design: Difficulty/boundary_precision_check/consular_daily_quota_sixth_ok_seventh_rejected
        """
        s = setup_approved_petition_with_linked_workers(7)
        pet_id, workers = s["petition"]["id"], s["workers"]

        for w in workers[:6]:
            resp = api.create_consular_appointment(
                {"worker_id": w["id"], "petition_id": pet_id,
                 "consulate_code": "MEX-MTY", "appointment_date": "2026-09-02"},
                ADMIN,
            )
            validate_success(resp, 201)

        resp = api.create_consular_appointment(
            {"worker_id": workers[6]["id"], "petition_id": pet_id,
             "consulate_code": "MEX-MTY", "appointment_date": "2026-09-02"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CONSULATE_CAPACITY_FULL)

    def test_quota_boundary_leaves_exactly_six_scheduled(self, api):
        """PRD 3.4: "the server counts `SCHEDULED` appointments with the same
        `consulate_code` on the same `appointment_date` and accepts the booking
        only while that count is below six, so the sixth appointment of the day
        succeeds and the seventh is rejected with `ERR_CONSULATE_CAPACITY_FULL`"

        Design: Difficulty/boundary_precision_check/consular_daily_quota_sixth_ok_seventh_rejected
        """
        s = setup_approved_petition_with_linked_workers(7)
        pet_id, workers = s["petition"]["id"], s["workers"]
        for w in workers[:6]:
            schedule_appointment(w["id"], pet_id, "2026-09-02")
        validate_error(
            api.create_consular_appointment(
                {"worker_id": workers[6]["id"], "petition_id": pet_id,
                 "consulate_code": "MEX-MTY", "appointment_date": "2026-09-02"},
                ADMIN,
            ),
            ApiErrorId.ERR_CONSULATE_CAPACITY_FULL,
        )

        rows, meta = validate_paginated(
            api.list_consular_appointments(
                ADMIN,
                params={"consulate_code": "MEX-MTY", "appointment_date": "2026-09-02", "status": "SCHEDULED"},
            )
        )
        assert meta["total_count"] == 6
        assert len(rows) == 6


class TestQuotaIsPerDatePointCount:
    def _six_booked(self, api):
        s = setup_approved_petition_with_linked_workers(7)
        pet_id, workers = s["petition"]["id"], s["workers"]
        first = schedule_appointment(workers[0]["id"], pet_id, "2026-09-02")
        for w in workers[1:6]:
            schedule_appointment(w["id"], pet_id, "2026-09-02")
        return pet_id, workers, first

    def test_full_day_does_not_block_adjacent_day(self, api):
        """PRD 3.4: "Each consulate processes at most six scheduled interviews per
        day: the server counts `SCHEDULED` appointments with the same
        `consulate_code` on the same `appointment_date` and accepts the booking
        only while that count is below six, so the sixth appointment of the day
        succeeds and the seventh is rejected with `ERR_CONSULATE_CAPACITY_FULL`"

        Design: Difficulty/resource_temporal_overlap/consular_point_quota_no_interval_carryover
        """
        pet_id, workers, _ = self._six_booked(api)

        # 2026-09-02 is full, but the quota counts a single (consulate, date)
        # point: the next day has zero bookings.
        created = validate_success(
            api.create_consular_appointment(
                {"worker_id": workers[6]["id"], "petition_id": pet_id,
                 "consulate_code": "MEX-MTY", "appointment_date": "2026-09-03"},
                ADMIN,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"

    def test_cancelled_appointment_frees_its_slot(self, api):
        """PRD 3.4: "`CANCELLED` and `COMPLETED` appointments consume no slots."
        PRD 3.4: "A `ContractorAdmin` may instead cancel a `SCHEDULED` appointment,
        moving it to `CANCELLED` and freeing its daily consular slot."

        Design: Difficulty/resource_temporal_overlap/consular_point_quota_no_interval_carryover
        """
        pet_id, workers, first = self._six_booked(api)

        cancelled = validate_success(api.cancel_consular_appointment(first["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"

        rebooked = validate_success(
            api.create_consular_appointment(
                {"worker_id": workers[0]["id"], "petition_id": pet_id,
                 "consulate_code": "MEX-MTY", "appointment_date": "2026-09-02"},
                ADMIN,
            ),
            201,
        )
        assert rebooked["status"] == "SCHEDULED"


class TestCompletionGuards:
    def test_appointment_complete_twice_terminal_lockdown(self, api):
        """PRD 3.4: "Recording the interview outcome is the exclusive duty of a
        `VisaOfficer`, and only for a `SCHEDULED` appointment (else
        `ERR_APPOINTMENT_INVALID_STATE`) whose `appointment_date` the clock date
        has reached (else `ERR_APPOINTMENT_NOT_YET_DUE`)."
        PRD 3.4: "The recorded `outcome` drives the worker: `ISSUED` moves the
        worker from `PETITIONED` to `VISA_ISSUED`; `REFUSED` sends the worker back
        to `REGISTERED` with `petition_id` cleared to null; `NO_SHOW` leaves the
        worker unchanged."

        Design: Corner/state_machines/appointment_complete_twice_terminal_lockdown
        """
        s = setup_active_order_pipeline(passports=("P0001",), start_assignments=False)
        appt = s["appointments"]["P0001"]
        wa = s["workers"]["P0001"]
        assert wa["status"] == "VISA_ISSUED"

        resp = api.complete_consular_appointment(appt["id"], {"outcome": "REFUSED"}, VISA_OFFICER)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE)

        current = get_success_data(api.get_consular_appointment(appt["id"], ADMIN))
        assert current["status"] == "COMPLETED"
        assert current["outcome"] == "ISSUED"
        worker = get_success_data(api.get_worker(wa["id"], ADMIN))
        assert worker["status"] == "VISA_ISSUED", "side effects of a terminal appointment must not re-fire"

    def test_appointment_guard_battery_rejected(self, api):
        """PRD 3.4: "The `appointment_date` must be strictly after the clock date
        at creation — same-day or past dates are rejected with
        `ERR_APPOINTMENT_DATE_NOT_FUTURE`."
        PRD 3.4: "Recording the interview outcome is the exclusive duty of a
        `VisaOfficer`, and only for a `SCHEDULED` appointment (else
        `ERR_APPOINTMENT_INVALID_STATE`) whose `appointment_date` the clock date
        has reached (else `ERR_APPOINTMENT_NOT_YET_DUE`)."
        PRD 3.4: "A worker may hold only one scheduled interview at a time —
        scheduling a second while one is still `SCHEDULED` is rejected with
        `ERR_WORKER_HAS_ACTIVE_APPOINTMENT`."
        PRD 3.4: "The petition must be `APPROVED`; the worker must be linked to
        that very petition (else `ERR_WORKER_NOT_ON_PETITION`) and in `PETITIONED`
        status (else `ERR_WORKER_INVALID_STATE`)."

        Design: Corner/errors/appointment_guard_battery_rejected
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_petitioning_order(grower["id"], wd["id"])
        pet1 = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=1)
        pet2 = create_petition(jo["id"], receipt_code="RCPT-2", requested_worker_count=1)
        wa = create_worker(passport_number="P0001", full_name="Worker A")
        wb = create_worker(passport_number="P0002", full_name="Worker B")
        link_worker(pet1["id"], wa["id"])
        link_worker(pet2["id"], wb["id"])
        file_petition(pet1["id"])
        file_petition(pet2["id"])
        adjudicate_petition(pet1["id"], "APPROVE", approved_worker_count=1)
        adjudicate_petition(pet2["id"], "APPROVE", approved_worker_count=1)

        set_clock("2026-09-01T00:00:00Z")
        appt_a = schedule_appointment(wa["id"], pet1["id"], "2026-09-05")

        # Same-day creation: appointment_date == clock date is not strictly after.
        resp = api.create_consular_appointment(
            {"worker_id": wa["id"], "petition_id": pet1["id"],
             "consulate_code": "MEX-MTY", "appointment_date": "2026-09-01"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_DATE_NOT_FUTURE)

        # Completing before the appointment date: clock 09-01 < 09-05.
        resp = api.complete_consular_appointment(appt_a["id"], {"outcome": "ISSUED"}, VISA_OFFICER)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_YET_DUE)
        assert get_success_data(api.get_consular_appointment(appt_a["id"], ADMIN))["status"] == "SCHEDULED"

        # A second SCHEDULED appointment for the same worker.
        resp = api.create_consular_appointment(
            {"worker_id": wa["id"], "petition_id": pet1["id"],
             "consulate_code": "MEX-MTY", "appointment_date": "2026-09-06"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_HAS_ACTIVE_APPOINTMENT)

        # W_B is linked to pet2, not pet1.
        resp = api.create_consular_appointment(
            {"worker_id": wb["id"], "petition_id": pet1["id"],
             "consulate_code": "MEX-MTY", "appointment_date": "2026-09-05"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_ON_PETITION)
