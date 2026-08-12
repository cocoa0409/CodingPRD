"""Fleet compliance: work orders, inspections, grounding and credential
cascades reaching service days."""
from test_helpers import (
    ApiErrorId,
    build_service_day,
    create_active_contract,
    create_active_driver,
    create_bus,
    create_district,
    create_inspection,
    create_route,
    create_work_order,
    get_success_data,
    post_work_order_event,
    set_clock,
    setup_ops_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import FLEET, FINANCE, HR, OPS


class TestWorkOrderOpensShop:
    def test_side_effect_workorder_open_moves_bus_in_shop(self, api):
        """PRD section 3.4: "Creating one with a `bus_id`, a `category` of `PM`,
        `REPAIR`, or `INSPECTION_FOLLOWUP`, and a `description` opens it in
        `OPEN` and immediately moves the bus from `IN_SERVICE` or `GROUNDED` to
        `IN_SHOP`."

        Design: Corner/state_machines/side_effect_workorder_open_moves_bus_in_shop
        """
        district = create_district(name="D-SM5")
        bus = create_bus(district["id"], fleet_number="BS5")
        assert bus["status"] == "IN_SERVICE"

        work_order = create_work_order(bus["id"], category="PM",
                                       description="Oil change")
        assert work_order["status"] == "OPEN"

        bus_after = validate_success(api.get_bus(bus["id"], FLEET))
        assert bus_after["status"] == "IN_SHOP", (
            "the work order side effect lands in the same request")


class TestWorkOrderPartsReorderLoop:
    def test_workorder_parts_reorder_loop_cycle(self, api):
        """PRD section 3.4: "`DIAGNOSE` moves `OPEN` to `DIAGNOSING`;
        `ORDER_PARTS` moves `DIAGNOSING` to `WAITING_PARTS`; `START_REPAIR`
        moves `DIAGNOSING` to `IN_REPAIR`; `PARTS_RECEIVED` moves
        `WAITING_PARTS` to `IN_REPAIR`; and a further `ORDER_PARTS` from
        `IN_REPAIR` loops back to `WAITING_PARTS` for the parts re-order cycle."
        PRD section 3.4: "`COMPLETE` moves `IN_REPAIR` to `COMPLETED` and
        requires both `labor_minutes` and `parts_cost_cents` in the payload."
        PRD section 3.4: "Either completion or cancellation returns the bus to
        `IN_SERVICE` when three conditions all hold: no other work order on the
        bus remains in `OPEN`, `DIAGNOSING`, `WAITING_PARTS`, or `IN_REPAIR`; no
        inspection on the bus stands at `FAILED` or `OVERDUE`; and the bus's
        `next_inspection_due` is on or after the clock date."

        Design: Corner/state_machines/workorder_parts_reorder_loop_cycle
        """
        district = create_district(name="D-SM6")
        bus = create_bus(district["id"], fleet_number="BS6")
        work_order = create_work_order(bus["id"], category="REPAIR",
                                       description="Transmission")

        post_work_order_event(work_order["id"], "DIAGNOSE")
        post_work_order_event(work_order["id"], "START_REPAIR")
        waiting = post_work_order_event(work_order["id"], "ORDER_PARTS")
        assert waiting["status"] == "WAITING_PARTS", "looped out of IN_REPAIR"
        repairing = post_work_order_event(work_order["id"], "PARTS_RECEIVED")
        assert repairing["status"] == "IN_REPAIR", "loop closed"
        completed = post_work_order_event(work_order["id"], "COMPLETE",
                                          labor_minutes=240, parts_cost_cents=8999)
        assert completed["status"] == "COMPLETED"
        assert completed["labor_minutes"] == 240
        assert completed["parts_cost_cents"] == 8999

        bus_after = validate_success(api.get_bus(bus["id"], FLEET))
        assert bus_after["status"] == "IN_SERVICE", (
            "last open work order completed; no FAILED/OVERDUE inspection; "
            "next_inspection_due on or after the clock date")


class TestInspectionRecoveryCycle:
    def test_inspection_fail_reschedule_pass_recovery_cycle(self, api):
        """PRD section 3.4: "The re-inspection loop is cyclic: a `FAILED`
        inspection may be rescheduled back to `SCHEDULED` with a new
        `scheduled_date` on or after the clock date (an earlier date is rejected
        with `ERR_INVALID_TIME_RANGE`), clearing `result` and `completed_on` to
        null."
        PRD section 3.4: "Recording `PASS` sets `completed_on` to the clock date,
        moves the inspection to `PASSED`, updates the bus's
        `next_inspection_due` from the supplied value, and — provided no work
        order on the bus remains open — returns a `GROUNDED` or `IN_SHOP` bus to
        `IN_SERVICE`."

        Design: Corner/state_machines/inspection_fail_reschedule_pass_recovery_cycle
        """
        district = create_district(name="D-SM7")
        bus = create_bus(district["id"], fleet_number="BS7",
                         next_inspection_due="2026-05-31")
        inspection = create_inspection(bus["id"], scheduled_date="2026-05-10",
                                       inspector_ref="ST-1")
        failed = get_success_data(api.record_inspection_result(
            inspection["id"], {"result": "FAIL"}, FLEET))
        assert failed["status"] == "FAILED"
        assert validate_success(api.get_bus(bus["id"], FLEET))["status"] == "GROUNDED"

        rescheduled = get_success_data(api.reschedule_inspection(
            inspection["id"], {"scheduled_date": "2026-05-20"}, FLEET))
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["result"] is None, "result cleared on reschedule"
        assert rescheduled["completed_on"] is None, "completed_on cleared"

        passed = get_success_data(api.record_inspection_result(
            inspection["id"], {"result": "PASS", "next_inspection_due": "2026-11-20"},
            FLEET))
        assert passed["status"] == "PASSED"

        bus_after = validate_success(api.get_bus(bus["id"], FLEET))
        assert bus_after["status"] == "IN_SERVICE", "recovery from GROUNDED"
        assert bus_after["next_inspection_due"] == "2026-11-20"


class TestInspectionOverdueSystemTransition:
    def test_inspection_overdue_system_transition_grounds_bus(self, api):
        """PRD section 3.4: "Time itself is a hazard: when the logical clock
        advances past a `SCHEDULED` inspection's `scheduled_date` with no result
        recorded, the inspection flips to `OVERDUE` and the exact same grounding
        cascade fires — bus to `GROUNDED`, future assignments cancelled
        `BUS_GROUNDED`, shortage recomputed."

        Design: Corner/state_machines/inspection_overdue_system_transition_grounds_bus
        """
        district = create_district(name="D-SM11")
        bus = create_bus(district["id"], fleet_number="BS11")
        inspection = create_inspection(bus["id"], scheduled_date="2026-05-10",
                                       inspector_ref="ST-2")

        set_clock("2026-05-11T00:00:00Z")

        insp_after = validate_success(api.get_inspection(inspection["id"], FLEET))
        assert insp_after["status"] == "OVERDUE", (
            "scheduled_date 2026-05-10 precedes the new clock date 2026-05-11")
        bus_after = validate_success(api.get_bus(bus["id"], FLEET))
        assert bus_after["status"] == "GROUNDED", "overdue cascade grounds the bus"


class TestInspectionFailCascade:
    def _armed_confirmed_day_with_inspection(self, api):
        ctx = setup_ops_scenario(district_name="D-CAS1")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-03")
        confirm_assignment = get_success_data(api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS))
        assert confirm_assignment["status"] == "CONFIRMED"
        inspection = create_inspection(ctx["bus"]["id"], scheduled_date="2026-05-10",
                                       inspector_ref="ST-1")
        return ctx, day, assignments[0], inspection

    def test_inspection_fail_grounds_bus(self, api):
        """PRD section 3.4: "Recording `FAIL` sets `completed_on`, moves the
        inspection to `FAILED`, grounds the bus, and cancels every assignment on
        that bus in `PLANNED` or `CONFIRMED` on days dated on or after the clock
        date with `cancellation_reason` `BUS_GROUNDED`, recomputing shortage
        fields on each affected day."
        PRD section 2.5: "At server startup the clock is exactly
        `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_to_service_day
        """
        ctx, day, assignment, inspection = (
            self._armed_confirmed_day_with_inspection(api))
        failed = get_success_data(api.record_inspection_result(
            inspection["id"], {"result": "FAIL"}, FLEET))
        assert failed["status"] == "FAILED"
        assert failed["completed_on"] == "2026-05-01", (
            "completed_on is stamped from the logical clock")

        bus_after = validate_success(api.get_bus(ctx["bus"]["id"], FLEET))
        assert bus_after["status"] == "GROUNDED", "link 1: inspection -> bus"

    def test_grounded_bus_cancels_confirmed_assignment(self, api):
        """PRD section 3.4: "Recording `FAIL` sets `completed_on`, moves the
        inspection to `FAILED`, grounds the bus, and cancels every assignment on
        that bus in `PLANNED` or `CONFIRMED` on days dated on or after the clock
        date with `cancellation_reason` `BUS_GROUNDED`, recomputing shortage
        fields on each affected day."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_to_service_day
        """
        ctx, day, assignment, inspection = (
            self._armed_confirmed_day_with_inspection(api))
        get_success_data(api.record_inspection_result(
            inspection["id"], {"result": "FAIL"}, FLEET))

        asg_after = validate_success(api.get_assignment(assignment["id"], OPS))
        assert asg_after["status"] == "CANCELLED", "link 2: bus -> assignment"
        assert asg_after["cancellation_reason"] == "BUS_GROUNDED"

        day_after = validate_success(api.get_service_day(day["id"], OPS))
        assert day_after["uncovered_routes"] == 1, "link 3: day recompute"
        assert day_after["shortage_flag"] is True


class TestCredentialExpiryCascade:
    def _armed_day_with_expiring_endorsement(self, api):
        district = create_district(name="D-CAS2")
        contract = create_active_contract(district["id"], bid_reference="BID-C2")
        create_route(contract["id"], route_code="R1", am_start_minute=420,
                     am_end_minute=480, student_count=40)
        driver = create_active_driver(district["id"], full_name="D Cas2",
                                      license_number="L800",
                                      s_endorsement_expires_on="2026-06-10")
        bus = create_bus(district["id"], fleet_number="BC2")
        day, assignments = build_service_day(contract["id"], "2026-06-12")
        get_success_data(api.confirm_assignment(
            assignments[0]["id"], {"driver_id": driver["id"], "bus_id": bus["id"]}, OPS))
        credentials, _meta = validate_paginated(
            api.list_credentials(HR, params={"driver_id": driver["id"],
                                             "kind": "S_ENDORSEMENT"}))
        return district, driver, bus, day, assignments[0], credentials[0]

    def test_clock_advance_expires_credential_and_suspends_driver(self, api):
        """PRD section 3.3: "Or the logical clock may advance past it: any
        credential whose `expires_on` falls before the new clock date flips from
        `ACTIVE` to `EXPIRED`. Either way, when the lost credential is a `CDL_B`
        or `S_ENDORSEMENT` and its holder is an `ACTIVE` driver, the same
        protective cascade fires: the driver is suspended with
        `suspension_reason` `CREDENTIAL_LAPSED`, their future `CONFIRMED`
        assignments are cancelled with reason `DRIVER_SUSPENDED`, and every
        affected service day recomputes its coverage and shortage fields."

        Design: Difficulty/transitive_cascade/credential_expiry_cascade_to_service_day
        """
        _district, driver, _bus, _day, _asg, credential = (
            self._armed_day_with_expiring_endorsement(api))
        set_clock("2026-06-11T00:00:00Z")

        cred_after = validate_success(api.get_credential(credential["id"], HR))
        assert cred_after["status"] == "EXPIRED", (
            "link 0: clock -> credential; expires_on 2026-06-10 < 2026-06-11")

        driver_after = validate_success(api.get_driver(driver["id"], HR))
        assert driver_after["status"] == "SUSPENDED", "link 1: credential -> driver"
        assert driver_after["suspension_reason"] == "CREDENTIAL_LAPSED"

    def test_suspended_driver_cascade_cancels_confirmed_assignment(self, api):
        """PRD section 3.3: "Either way, when the lost credential is a `CDL_B` or
        `S_ENDORSEMENT` and its holder is an `ACTIVE` driver, the same protective
        cascade fires: the driver is suspended with `suspension_reason`
        `CREDENTIAL_LAPSED`, their future `CONFIRMED` assignments are cancelled
        with reason `DRIVER_SUSPENDED`, and every affected service day recomputes
        its coverage and shortage fields."

        Design: Difficulty/transitive_cascade/credential_expiry_cascade_to_service_day
        """
        _district, driver, _bus, day, assignment, _cred = (
            self._armed_day_with_expiring_endorsement(api))
        set_clock("2026-06-11T00:00:00Z")

        asg_after = validate_success(api.get_assignment(assignment["id"], OPS))
        assert asg_after["status"] == "CANCELLED", (
            "link 2: driver -> assignment; service_date 2026-06-12 is on or "
            "after the clock date")
        assert asg_after["cancellation_reason"] == "DRIVER_SUSPENDED"

        day_after = validate_success(api.get_service_day(day["id"], OPS))
        assert day_after["uncovered_routes"] == 1, "link 3: assignment -> day"
        assert day_after["shortage_flag"] is True


class TestInspectionDayConflict:
    def test_error_inspection_day_conflict_triggerable(self, api):
        """PRD section 3.4: "Scheduling is rejected with
        `ERR_INSPECTION_DAY_CONFLICT` when the bus holds a `CONFIRMED` assignment
        on the proposed date — inspection occupies the whole day, so interval
        arithmetic does not apply."

        Design: Corner/errors/error_inspection_day_conflict_triggerable
        """
        ctx = setup_ops_scenario(district_name="D-ERR13")
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        get_success_data(api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS))

        resp = api.create_inspection(
            {"bus_id": ctx["bus"]["id"], "scheduled_date": "2026-06-01",
             "inspector_ref": "ST-3"},
            FLEET)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_DAY_CONFLICT, 409)


class TestFleetRoleDenial:
    def test_rbac_finance_cannot_record_inspection_returns_403(self, api):
        """PRD section 2.1: "A request whose role is not in the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /busops/inspections/{id}/record-result is authorized
        for FleetManager only.

        Design: Corner/rbac/rbac_finance_cannot_record_inspection_returns_403
        """
        district = create_district(name="D-RB2")
        bus = create_bus(district["id"], fleet_number="BRB2")
        inspection = create_inspection(bus["id"], scheduled_date="2026-05-10",
                                       inspector_ref="ST-4")

        resp = api.record_inspection_result(
            inspection["id"], {"result": "PASS", "next_inspection_due": "2026-11-10"},
            FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        insp_after = validate_success(api.get_inspection(inspection["id"], FLEET))
        assert insp_after["status"] == "SCHEDULED"
