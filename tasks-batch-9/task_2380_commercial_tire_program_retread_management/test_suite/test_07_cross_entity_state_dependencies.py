"""Writes whose admissibility is decided by the state of a different row."""

from test_helpers import (
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestSchedulingDependsOnLineState:
    """The line's status gates both booking and starting."""

    def test_a_down_line_refuses_new_bookings_and_takes_them_once_back_up(self, api):
        """PRD §3.1: "A `DealerAdmin` may set a line's `status` to `DOWN` for
        maintenance and back to `AVAILABLE`; a `DOWN` line rejects new scheduling,
        rescheduling and job starts with `ERR_LINE_DOWN`, but already-booked jobs
        keep their slots and the line's `booked_minutes` does not change when the
        line goes down or comes back up."
        PRD §3.5: "The target line must be `AVAILABLE`, or `ERR_LINE_DOWN` applies."

        Design: Difficulty/cross_entity_state_dependency/retread_job_creation_depends_on_retread_line_state
        """
        program = fixtures.setup_plant_program()
        casing = fixtures.create_inspected_casing(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )
        down = fixtures.take_line_down(program["line"]["id"])
        assert down["status"] == "DOWN"
        assert down["booked_minutes"] == 0

        payload = factories.retread_job_payload(
            casing["id"],
            program["line"]["id"],
            "2026-08-20T08:00:00Z",
            "2026-08-20T12:00:00Z",
        )
        validate_error(
            api.create_retread_job(payload, fixtures.SCHEDULER),
            "ERR_LINE_DOWN",
            expected_status=409,
        )
        assert fixtures.read_casing(casing["id"])["status"] == "INSPECTED"
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 0

        fixtures.return_line_to_service(program["line"]["id"])
        job = validate_success(
            api.create_retread_job(payload, fixtures.SCHEDULER), expected_status=201
        )

        assert job["status"] == "SCHEDULED"
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 270
        assert fixtures.read_casing(casing["id"])["status"] == "RETREAD_QUEUED"

    def test_a_line_going_down_after_booking_blocks_the_start_but_keeps_the_slot(
        self, api
    ):
        """PRD §3.5: "The job must be `SCHEDULED`, the line must still be `AVAILABLE`
        — a line that went down between booking and start rejects the start with
        `ERR_LINE_DOWN` — and `started_at` must fall on or after the job's
        `scheduled_start_at`; an earlier instant is rejected with
        `ERR_JOB_START_TOO_EARLY`."
        PRD §3.5: "The line's `booked_minutes` is unchanged, because a job in
        production is still in the booked set."

        Design: Difficulty/cross_entity_state_dependency/retread_job_creation_depends_on_retread_line_state
        """
        program = fixtures.setup_scheduled_job()
        line_id = program["line"]["id"]
        assert fixtures.read_line(line_id)["booked_minutes"] == 270

        fixtures.take_line_down(line_id)
        validate_error(
            api.start_retread_job(
                program["job"]["id"],
                factories.start_job_payload("2026-08-20T08:00:00Z"),
                fixtures.SCHEDULER,
            ),
            "ERR_LINE_DOWN",
            expected_status=409,
        )
        assert fixtures.read_job(program["job"]["id"])["status"] == "SCHEDULED"
        assert fixtures.read_line(line_id)["booked_minutes"] == 270, (
            "an already-booked job keeps its slot while the line is down"
        )

        fixtures.return_line_to_service(line_id)
        started = fixtures.start_job(program["job"]["id"])
        assert started["status"] == "IN_PRODUCTION"
        assert fixtures.read_line(line_id)["booked_minutes"] == 270


class TestTerminationDependsOnInvoiceState:
    """An agreement cannot be pulled out from under an unfinished bill."""

    def test_termination_is_blocked_while_a_bill_is_open_or_submitted(self, api):
        """PRD §3.2: "Termination is blocked while any cross-location invoice priced
        by that agreement is still `OPEN` or `SUBMITTED`, and the attempt is rejected
        with `ERR_AGREEMENT_HAS_OPEN_INVOICE`; the intent is that a fleet's billing
        cannot be orphaned mid-cycle."
        PRD §3.8: "The invoice advances `SUBMITTED → PAID` and records the amount,
        and every claimed call cascades `BILLED_TO_NATIONAL → SETTLED`."

        Design: Difficulty/cross_entity_state_dependency/agreement_termination_depends_on_invoice_state
        """
        program = fixtures.setup_open_invoice(credit_grade="B")
        agreement_id = program["agreement"]["id"]
        payload = {"terminated_reason": "Fleet moved to a competitor"}

        validate_error(
            api.terminate_national_agreement(agreement_id, payload, fixtures.ADMIN),
            "ERR_AGREEMENT_HAS_OPEN_INVOICE",
            expected_status=409,
        )
        assert fixtures.read_agreement(agreement_id)["status"] == "ACTIVE"

        submitted = fixtures.submit_invoice(program["invoice"]["id"])
        assert submitted["status"] == "SUBMITTED"
        validate_error(
            api.terminate_national_agreement(agreement_id, payload, fixtures.ADMIN),
            "ERR_AGREEMENT_HAS_OPEN_INVOICE",
            expected_status=409,
        )

        paid = fixtures.settle_invoice(
            program["invoice"]["id"], submitted["total_cents"]
        )
        assert paid["status"] == "PAID"

        terminated = validate_success(
            api.terminate_national_agreement(agreement_id, payload, fixtures.ADMIN)
        )
        assert terminated["status"] == "TERMINATED"

    def test_termination_after_a_dispute_reverts_the_fleet_to_direct_billing(self, api):
        """PRD §3.2: "When termination succeeds and the fleet is left holding no
        other `ACTIVE` agreement, the fleet's `billing_mode` reverts to `DIRECT` and
        the fleet's `version` increments — a national account that has no agreement
        is, by definition, no longer cross-location billed."
        PRD §3.8: "Both `PAID` and `DISPUTED` are terminal for an invoice; submitting
        an invoice that is not `OPEN`, or settling or disputing one that is not
        `SUBMITTED`, is rejected with `ERR_INVOICE_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/agreement_termination_depends_on_invoice_state
        """
        program = fixtures.setup_submitted_invoice(credit_grade="B")
        fleet_id = program["fleet"]["id"]
        assert fixtures.read_fleet(fleet_id)["billing_mode"] == "CROSS_LOCATION"

        disputed = fixtures.dispute_invoice(program["invoice"]["id"])
        assert disputed["status"] == "DISPUTED"

        version_before = fixtures.read_fleet(fleet_id)["version"]
        terminated = validate_success(
            api.terminate_national_agreement(
                program["agreement"]["id"],
                {"terminated_reason": "Cycle closed out"},
                fixtures.ADMIN,
            )
        )

        assert terminated["status"] == "TERMINATED"
        fleet = fixtures.read_fleet(fleet_id)
        assert fleet["billing_mode"] == "DIRECT"
        assert fleet["account_type"] == "NATIONAL_ACCOUNT", (
            "only the billing mode reverts, not the commercial classification"
        )
        assert fleet["version"] == version_before + 1


class TestCallCreationDependsOnFleetState:
    """Suspension is forward-looking only."""

    def test_a_suspended_fleet_cannot_open_a_new_call(self, api):
        """PRD §3.6: "The fleet must be `ACTIVE`, otherwise `ERR_FLEET_SUSPENDED`;
        and the unit must belong to that fleet, otherwise `ERR_FLEET_MISMATCH`."
        PRD §3.1: "A `DealerAdmin` may later toggle standing between `ACTIVE` and
        `SUSPENDED`, supplying both the target `status` and a free-text
        `status_reason` that is retained on the account; each toggle increments the
        fleet's `version`."

        Design: Difficulty/cross_entity_state_dependency/road_service_call_creation_depends_on_fleet_account_state
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        suspended = fixtures.suspend_fleet(program["fleet"]["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["status_reason"] == "Past due balance"

        payload = factories.road_service_call_payload(
            program["fleet"]["id"],
            vehicle["id"],
            program["location"]["id"],
            "2026-08-05T13:00:00Z",
        )
        validate_error(
            api.create_road_service_call(payload, fixtures.DISPATCHER),
            "ERR_FLEET_SUSPENDED",
            expected_status=409,
        )

        reinstated = fixtures.reinstate_fleet(program["fleet"]["id"])
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["status_reason"] == "Payment received"

        call = validate_success(
            api.create_road_service_call(payload, fixtures.DISPATCHER),
            expected_status=201,
        )
        assert call["dispatch_status"] == "OPEN"
        assert call["billing_status"] == "UNBILLED"

    def test_work_already_in_flight_completes_despite_a_later_suspension(self, api):
        """PRD §3.1: "Suspension is forward-looking only: work already in flight is
        untouched, but a suspended fleet may not have a new road service call opened
        for it and may not have a new retread scheduled — both are rejected with
        `ERR_FLEET_SUSPENDED`."
        PRD §3.5: "The owning fleet must not be suspended, or `ERR_FLEET_SUSPENDED`
        applies."

        Design: Difficulty/cross_entity_state_dependency/road_service_call_creation_depends_on_fleet_account_state
        """
        program = fixtures.setup_plant_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        technician = fixtures.create_technician(program["location"]["id"])
        casing = fixtures.create_inspected_casing(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )
        call = fixtures.open_call(
            program["fleet"]["id"],
            vehicle["id"],
            program["location"]["id"],
            "2026-08-05T13:00:00Z",
        )
        fixtures.dispatch_call(
            call["id"], "2026-08-05T13:05:00Z", 10, technician["id"]
        )
        fixtures.arrive_call(call["id"], "2026-08-05T14:00:00Z", technician["id"])

        fixtures.suspend_fleet(program["fleet"]["id"])

        completed = fixtures.complete_call(
            call["id"], "2026-08-05T15:00:00Z", 1.0, technician["id"]
        )
        assert completed["dispatch_status"] == "COMPLETED"
        assert completed["gross_cents"] == 23350, (
            "9500 base plus 11000 labour plus 2850 mileage, priced as usual"
        )
        assert completed["sla_met"] is True

        # But nothing new may be started for the suspended fleet.
        validate_error(
            api.create_retread_job(
                factories.retread_job_payload(
                    casing["id"],
                    program["line"]["id"],
                    "2026-08-20T08:00:00Z",
                    "2026-08-20T12:00:00Z",
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_FLEET_SUSPENDED",
            expected_status=409,
        )
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 0
        assert (
            fixtures.reinstate_fleet(program["fleet"]["id"])["status_reason"]
            == "Payment received"
        )


class TestRescheduleDependsOnCasingState:
    """A failed cure is re-bookable only if the carcass survived it."""

    def test_a_condemned_carcass_can_never_be_rescheduled(self, api):
        """PRD §3.5: "The job must be `FAILED_CURE`; the casing must be sitting in
        `INSPECTED`, which is exactly why a job that failed with `CASING_FAILURE` can
        never be rescheduled — its carcass is `REJECTED`, and the attempt is rejected
        with `ERR_CASING_INVALID_STATE`."
        PRD §2.11: "This applies to every action endpoint that drives a state
        transition."

        Design: Difficulty/cross_entity_state_dependency/retread_reschedule_depends_on_casing_state
        """
        program = fixtures.setup_failed_cure_job(failure_reason="CASING_FAILURE")
        assert fixtures.read_casing(program["casing"]["id"])["status"] == "REJECTED"

        validate_error(
            api.reschedule_retread_job(
                program["job"]["id"],
                factories.reschedule_job_payload(
                    "2026-08-21T08:00:00Z", "2026-08-21T12:00:00Z"
                ),
                fixtures.SCHEDULER,
            ),
            "ERR_CASING_INVALID_STATE",
            expected_status=409,
        )

        job = fixtures.read_job(program["job"]["id"])
        assert job["status"] == "FAILED_CURE"
        assert job["reschedule_count"] == 0
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 0

    def test_a_carcass_that_survived_the_cure_defect_is_re_bookable(self, api):
        """PRD §3.5: "On success the job returns `FAILED_CURE → SCHEDULED` with the
        new slot fields, adopts the supplied `retread_line_id` when one was given,
        increments `reschedule_count` by 1, cascades the casing `INSPECTED →
        RETREAD_QUEUED`, and adds the new slot's minutes plus the target line's
        cooldown to that line's `booked_minutes`."
        PRD §3.5: "`FAILED_CURE` is not terminal."

        Design: Difficulty/cross_entity_state_dependency/retread_reschedule_depends_on_casing_state
        """
        program = fixtures.setup_failed_cure_job(failure_reason="CURE_DEFECT")
        assert fixtures.read_casing(program["casing"]["id"])["status"] == "INSPECTED"
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 0

        rebooked = validate_success(
            api.reschedule_retread_job(
                program["job"]["id"],
                factories.reschedule_job_payload(
                    "2026-08-21T08:00:00Z", "2026-08-21T12:00:00Z"
                ),
                fixtures.SCHEDULER,
            )
        )

        assert rebooked["status"] == "SCHEDULED"
        assert rebooked["reschedule_count"] == 1
        assert rebooked["scheduled_start_at"] == "2026-08-21T08:00:00Z"
        assert rebooked["slot_minutes"] == 240
        assert fixtures.read_casing(program["casing"]["id"])["status"] == "RETREAD_QUEUED"
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 270
