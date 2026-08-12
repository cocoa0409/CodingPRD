"""Corner coverage: machine/maintenance/plan battery, DRAFT supersede, and the
full order lifecycle battery."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, ApiErrorId,
    get_success_data,
    create_program, create_patient, create_machine, assign_machine,
    create_active_home_patient, create_draft_order, submit_order,
    create_approved_order, schedule_appointment, complete_appointment,
    review_order,
    set_clock, get_patient, report_waste_return, verify_waste_return,
    api_client, make_admin_headers, make_nurse_headers,
    make_biomed_headers, make_patient_headers, make_coordinator_headers,
    create_maintenance_event_payload, create_backup_plan_payload,
)


class TestMachineAssignmentMaintenanceAndPlanBattery:
    """Machine lifecycle probes, one-IN_PROGRESS-per-machine, OCC on
    reassignment, and backup-plan machine reference gating decommission."""

    def test_machine_state_and_event_battery(self, api):
        """PRD §3.4: "Unassignment moves an `ASSIGNED` machine back to
        `IN_STOCK` (`ERR_MACHINE_INVALID_STATE` from any other state), clears
        `assigned_patient_id`, increments `version`, and recomputes the former
        patient's posture."
        PRD §3.4: "Starting an event requires it to be `SCHEDULED` and the
        machine to be `IN_STOCK` or `ASSIGNED` (an `UNDER_MAINTENANCE` or
        `DECOMMISSIONED` machine yields `ERR_EVENT_INVALID_STATE`), requires
        that no other event is already `IN_PROGRESS` on the same machine
        (`ERR_MACHINE_BUSY_MAINTENANCE`), and requires the current clock to be
        no later than `window_end` (`ERR_EVENT_WINDOW_PASSED`)."

        Design: Corner/state_machines/machine_assignment_maintenance_and_plan_battery
        """
        program = create_program()
        p1 = create_patient(program["id"], full_name="Pat A")
        m1 = create_machine(program["id"], serial_number="SN-M1")
        # Unassign from IN_STOCK: invalid state.
        resp = api.unassign_machine(m1["id"], make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_MACHINE_INVALID_STATE)
        assign_machine(m1["id"], p1["id"])
        # Decommission while ASSIGNED: invalid state.
        resp = api.decommission_machine(m1["id"], make_admin_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_MACHINE_INVALID_STATE)
        ev1 = validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(
                m1["id"], window_start="2026-05-10T09:00:00Z",
                window_end="2026-05-10T12:00:00Z"),
            make_biomed_headers("biomed-1")), 201)
        ev2 = validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(
                m1["id"], event_type="REPAIR",
                window_start="2026-05-11T09:00:00Z",
                window_end="2026-05-11T12:00:00Z"),
            make_biomed_headers("biomed-1")), 201)
        validate_success(api.start_maintenance_event(
            ev1["id"], make_biomed_headers("biomed-1")))
        # One IN_PROGRESS per machine. PRD lists both
        # ERR_MACHINE_BUSY_MAINTENANCE ("no other event is already IN_PROGRESS")
        # and ERR_EVENT_INVALID_STATE ("an UNDER_MAINTENANCE machine yields
        # ERR_EVENT_INVALID_STATE") as possible here; the priority pipeline
        # (§2.6) places state validity (stage 5) above uniqueness/overlap
        # (stage 8), but the PRD does not pin which wording applies to the
        # compound state, so accept either.
        resp = api.start_maintenance_event(ev2["id"],
                                           make_biomed_headers("biomed-1"))
        validate_error_is_one_of(resp, [ApiErrorId.ERR_MACHINE_BUSY_MAINTENANCE,
                                        ApiErrorId.ERR_EVENT_INVALID_STATE])
        # Cancel from IN_PROGRESS is invalid.
        resp = api.cancel_maintenance_event(ev1["id"],
                                            make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_INVALID_STATE)
        validate_success(api.complete_maintenance_event(
            ev1["id"], make_biomed_headers("biomed-1")))
        # Start after window_end.
        ev3 = validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(
                m1["id"], event_type="DECONTAMINATION",
                window_start="2026-04-01T09:00:00Z",
                window_end="2026-04-01T12:00:00Z"),
            make_biomed_headers("biomed-1")), 201)
        resp = api.start_maintenance_event(ev3["id"],
                                           make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_PASSED)

    def test_reassign_occ_and_backup_machine_and_decommission_gates(self, api):
        """PRD §2.8: "Assigning a dialysis machine (`POST
        /api/dialysis-machines/{id}/assign`) requires the non-optional field
        `expected_machine_version`, carrying the client's last observed
        `version` of the DialysisMachine. A mismatch with the machine's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because
        assignment supersedes the machine's current assignment when it moves
        from one patient to another (§3.4)."
        PRD §3.4: "Unless the mode is `IN_CENTER_CHAIR`, a `backup_machine_id`
        is required (`ERR_BACKUP_MACHINE_REQUIRED`) and must reference a
        machine currently `IN_STOCK` (`ERR_BACKUP_MACHINE_NOT_IN_STOCK`)."
        PRD §3.4: "A `ProgramAdmin` may decommission an `IN_STOCK` machine
        (`ERR_MACHINE_INVALID_STATE` otherwise), but only while no
        EmergencyBackupPlan in `ACTIVE` or `EXPIRED` references it as its
        `backup_machine_id` (`ERR_MACHINE_REFERENCED_BY_PLAN`); decommissioning
        cancels the machine's `SCHEDULED` maintenance events and lands the
        machine in the terminal `DECOMMISSIONED` state."

        Design: Corner/state_machines/machine_assignment_maintenance_and_plan_battery
        """
        program = create_program()
        p1 = create_patient(program["id"], full_name="Pat A")
        p2 = create_patient(program["id"], full_name="Pat B")
        m1 = create_machine(program["id"], serial_number="SN-M1")
        m2 = create_machine(program["id"], serial_number="SN-M2")
        assign_machine(m1["id"], p1["id"])
        # Same-patient reassign is a no-op rejection.
        cur = get_success_data(api.get_machine(m1["id"],
                                               make_admin_headers("admin-1")))
        resp = api.assign_machine(
            m1["id"], {"patient_id": p1["id"],
                       "expected_machine_version": cur["version"]},
            make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Reassign to p2 supersedes; a stale version is rejected 412.
        stale_v = cur["version"]
        assign_machine(m1["id"], p2["id"])
        after = get_success_data(api.get_machine(m1["id"],
                                                 make_admin_headers("admin-1")))
        assert after["assigned_patient_id"] == p2["id"]
        resp = api.assign_machine(
            m1["id"], {"patient_id": p1["id"],
                       "expected_machine_version": stale_v},
            make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Plan validation battery on p2.
        p2_doc = get_patient(p2["id"])
        resp = api.create_backup_plan(
            {"patient_id": p2["id"], "plan_mode": "BACKUP_MACHINE",
             "expected_patient_version": p2_doc["version"]},
            make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_BACKUP_MACHINE_REQUIRED)
        resp = api.create_backup_plan(
            {"patient_id": p2["id"], "plan_mode": "BACKUP_MACHINE",
             "backup_machine_id": m1["id"],
             "expected_patient_version": p2_doc["version"]},
            make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_BACKUP_MACHINE_NOT_IN_STOCK)
        p2_doc = get_patient(p2["id"])
        plan1 = validate_success(api.create_backup_plan(
            {"patient_id": p2["id"], "plan_mode": "BACKUP_MACHINE",
             "backup_machine_id": m2["id"],
             "expected_patient_version": p2_doc["version"]},
            make_nurse_headers("nurse-1")), 201)
        assert plan1["status"] == "ACTIVE"
        # Decommission blocked while referenced by the ACTIVE plan.
        resp = api.decommission_machine(m2["id"], make_admin_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_MACHINE_REFERENCED_BY_PLAN)
        ev4 = validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(
                m2["id"], window_start="2026-05-20T09:00:00Z",
                window_end="2026-05-20T12:00:00Z"),
            make_biomed_headers("biomed-1")), 201)
        # Supersede the plan; the SUPERSEDED plan no longer blocks or drills.
        p2_doc = get_patient(p2["id"])
        validate_success(api.create_backup_plan(
            {"patient_id": p2["id"], "plan_mode": "IN_CENTER_CHAIR",
             "expected_patient_version": p2_doc["version"]},
            make_nurse_headers("nurse-1")), 201)
        resp = api.drill_backup_plan(plan1["id"], make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        decomm = validate_success(api.decommission_machine(
            m2["id"], make_admin_headers("admin-1")))
        assert decomm["status"] == "DECOMMISSIONED"
        events = get_success_data(api.list_machine_events(
            m2["id"], make_admin_headers("admin-1")))
        assert events[0]["status"] == "CANCELLED"


class TestOrderDraftSupersededByNewCreate:
    """A second DRAFT create supersedes the first; the superseded order can no
    longer be submitted."""

    def test_second_draft_supersedes_first(self, api):
        """PRD §3.5: "Creation is a create-with-supersede: if a `DRAFT` order
        already exists for the same patient and month, it becomes `SUPERSEDED`;
        but if an order for that patient and month exists in `SUBMITTED`,
        `APPROVED`, or `CLOSED`, creation is rejected outright with
        `ERR_MONTH_ORDER_EXISTS`."

        Design: Corner/state_machines/order_draft_superseded_by_new_create
        """
        program = create_program()
        patient = create_patient(program["id"])
        pat = patient["id"]
        ord1 = create_draft_order(pat, "2026-05",
                                  [{"sku": "DIALYSATE_2L", "quantity": 5}])
        ord2 = create_draft_order(pat, "2026-05",
                                  [{"sku": "DIALYSATE_2L", "quantity": 8}])
        first = get_success_data(api.get_supply_order(ord1["id"],
                                                      make_admin_headers("admin-1")))
        assert first["order_status"] == "SUPERSEDED"
        resp = api.submit_supply_order(ord1["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        assert ord2["order_status"] == "DRAFT"
        assert ord2["provisional_total_units"] == 8


class TestOrderLifecycleAndWasteBattery:
    """Full order lifecycle probe across both axes plus waste verify replay
    and on-hand sufficiency."""

    def _setup(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        ord_may = create_draft_order(pat, "2026-05",
                                     [{"sku": "DIALYSATE_2L", "quantity": 10}])
        ord_jun = create_draft_order(pat, "2026-06",
                                     [{"sku": "DIALYSATE_2L", "quantity": 4}])
        return ctx, pat, ord_may, ord_jun

    def test_appointment_and_close_guards(self, api):
        """PRD §3.5: "A `SupplyCoordinator` schedules a DeliveryAppointment
        with `supply_order_id`, `window_start`, and `window_end`; the order
        must be `APPROVED` (`ERR_ORDER_INVALID_STATE`), at most one appointment
        per order may be `SCHEDULED` at a time (`ERR_ACTIVE_APPOINTMENT_EXISTS`),
        the `window_start` must not be in the past and its calendar date must
        fall inside the order month (`ERR_APPOINTMENT_OUTSIDE_ORDER_MONTH`),
        and the window must run at least 120 and at most 720 minutes with the
        end after the start (`ERR_INVALID_REQUEST`)."
        PRD §3.5: "The order must be `APPROVED` (`ERR_ORDER_INVALID_STATE`),
        the first day of the month after `order_month` must have been reached
        on the logical clock (`ERR_MONTH_NOT_ENDED`), and no `SCHEDULED`
        delivery appointment may remain on the order
        (`ERR_OPEN_APPOINTMENTS_EXIST`)."

        Design: Corner/state_machines/order_lifecycle_and_waste_battery
        """
        ctx, pat, ord_may, ord_jun = self._setup(api)
        # Appointment on a DRAFT order.
        resp = api.create_delivery_appointment(
            {"supply_order_id": ord_jun["id"],
             "window_start": "2026-06-04T08:00:00Z",
             "window_end": "2026-06-04T12:00:00Z"},
            make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        submit_order(ord_may["id"], pat)
        review_order(ord_may["id"], "APPROVE")
        # June window on a May order.
        resp = api.create_delivery_appointment(
            {"supply_order_id": ord_may["id"],
             "window_start": "2026-06-04T08:00:00Z",
             "window_end": "2026-06-04T12:00:00Z"},
            make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OUTSIDE_ORDER_MONTH)
        ap1 = schedule_appointment(ord_may["id"], "2026-05-04T08:00:00Z",
                                   "2026-05-04T12:00:00Z")
        # Second concurrent appointment.
        resp = api.create_delivery_appointment(
            {"supply_order_id": ord_may["id"],
             "window_start": "2026-05-05T08:00:00Z",
             "window_end": "2026-05-05T12:00:00Z"},
            make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_ACTIVE_APPOINTMENT_EXISTS)
        # Close while month still current.
        resp = api.close_supply_order(ord_may["id"],
                                      make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_MONTH_NOT_ENDED)
        # Close in June with the appointment still SCHEDULED.
        set_clock("2026-06-01T00:00:00Z")
        resp = api.close_supply_order(ord_may["id"],
                                      make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_OPEN_APPOINTMENTS_EXIST)
        validate_success(api.cancel_delivery_appointment(
            ap1["id"], make_coordinator_headers("coord-1")))
        closed = validate_success(api.close_supply_order(
            ord_may["id"], make_coordinator_headers("coord-1")))
        assert closed["order_status"] == "CLOSED"
        assert closed["actualized_units"] == 0, "no logs in the month"
        assert closed["adjustment_units"] == -72, "0 - (3*4*6)"
        # Terminal lockdown: submit on CLOSED.
        resp = api.submit_supply_order(ord_may["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    def test_delivery_and_waste_verification_battery(self, api):
        """PRD §3.5: "Completing a `SCHEDULED` appointment records
        `delivered_units`, which must be at least 1 and at most the order's
        remaining undelivered units — `provisional_total_units` minus
        `delivered_units_total` — with any other value rejected as
        `ERR_DELIVERED_UNITS_INVALID`."
        PRD §3.5: "Complete, fail, or cancel from a non-`SCHEDULED` appointment
        is `ERR_APPOINTMENT_INVALID_STATE`."
        PRD §3.8: "Verification belongs to the `SupplyCoordinator`, who passes
        an `approved` flag on a `REPORTED` record
        (`ERR_WASTE_RECORD_NOT_REPORTED` from any other state)."
        PRD §3.8: "The server sums the lines into `total_units` and requires
        it to fit within the patient's `on_hand_units`
        (`ERR_QUANTITY_EXCEEDS_ON_HAND`), but nothing leaves on-hand at report
        time."

        Design: Corner/state_machines/order_lifecycle_and_waste_battery
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        order = create_approved_order(pat, "2026-05",
                                      [{"sku": "DIALYSATE_2L", "quantity": 10}])
        ap1 = schedule_appointment(order["id"], "2026-05-04T08:00:00Z",
                                   "2026-05-04T12:00:00Z")
        set_clock("2026-05-04T09:00:00Z")
        complete_appointment(ap1["id"], 7)
        ap2 = schedule_appointment(order["id"], "2026-05-18T08:00:00Z",
                                   "2026-05-18T12:00:00Z")
        # 4 exceeds the remaining 3.
        resp = api.complete_delivery_appointment(
            ap2["id"], {"delivered_units": 4}, make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_DELIVERED_UNITS_INVALID)
        complete_appointment(ap2["id"], 3)
        # Double complete on a non-SCHEDULED appointment.
        resp = api.complete_delivery_appointment(
            ap2["id"], {"delivered_units": 1}, make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE)
        # Waste verify then replay.
        wr = report_waste_return(pat, "WASTE", "2026-05",
                                 [{"sku": "DIALYSATE_2L", "units": 2,
                                   "expired": False}])
        verified = verify_waste_return(wr["id"], approved=True)
        assert verified["status"] == "VERIFIED"
        resp = api.verify_waste_return_record(wr["id"], {"approved": True},
                                              make_coordinator_headers("coord-1"))
        validate_error(resp, ApiErrorId.ERR_WASTE_RECORD_NOT_REPORTED)
        # Over-on-hand waste report (on_hand is 8 after the verification).
        resp = api.create_waste_return_record(
            {"patient_id": pat, "record_type": "WASTE",
             "activity_month": "2026-05",
             "lines": [{"sku": "DIALYSATE_2L", "units": 100,
                        "expired": False}]},
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_ON_HAND)
