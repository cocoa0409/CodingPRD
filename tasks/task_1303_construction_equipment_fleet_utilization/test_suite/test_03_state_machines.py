"""State machine transitions, preconditions, and terminal lockdowns."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_damage,
    close_assignment,
    confirm_damage,
    dispatch_work_order,
    dispute_damage,
    get_success_data,
    make_active_assignment,
    make_class,
    make_damage_report,
    make_equipment,
    make_fleet_bundle,
    make_lowboy,
    make_mechanic,
    make_project,
    make_reserved_assignment,
    make_transport_job,
    make_work_order,
    run_repair_to_completion,
    set_clock,
    start_work_order_as_mechanic,
    complete_work_order_as_mechanic,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, make_mechanic_headers

_ADMIN = TEST_USERS["fleet_admin_headers"]
_DISP = TEST_USERS["dispatcher_headers"]
_PM = TEST_USERS["project_manager_headers"]


class TestProjectLifecycle:
    def test_suspend_resume_close_cycle(self, api):
        """PRD section 3.1: "an `OPEN` project can be suspended (`OPEN` →
        `SUSPENDED`), a suspended one resumed (`SUSPENDED` → `OPEN`), and
        either an open or suspended project can be closed".

        Design: Corner/state_machines/project_suspend_resume_close_cycle
        """
        proj = make_project(project_code="PRJ-200")
        s1 = validate_success(api.suspend_project(proj["id"], _ADMIN))
        assert s1["status"] == "SUSPENDED"
        s2 = validate_success(api.resume_project(proj["id"], _ADMIN))
        assert s2["status"] == "OPEN"
        s3 = validate_success(api.close_project(proj["id"], _ADMIN))
        assert s3["status"] == "CLOSED"

    def test_close_blocked_while_assignment_active_then_succeeds(self, api):
        """PRD section 3.1: "closure is refused while `active_assignment_count`
        is anything other than zero".

        Design: Corner/state_machines/project_close_blocked_while_assignment_active
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        err = api.close_project(project["id"], _ADMIN)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE)
        assert err.status_code == 409

        set_clock("2026-08-05T09:00:00Z")
        close_assignment(asg["id"])
        closed = validate_success(api.close_project(project["id"], _ADMIN))
        assert closed["status"] == "CLOSED"

    def test_resume_from_open_returns_invalid_state(self, api):
        """PRD section 3.1: "a suspended one resumed (`SUSPENDED` → `OPEN`)";
        resume is declared only from SUSPENDED, so calling it on OPEN has no
        such transition. PRD section 2.7 priority 7: "State-machine legality —
        the requested transition exists from the target's current state — else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/project_resume_from_open_returns_invalid_state
        """
        proj = make_project(project_code="PRJ-202")
        resp = api.resume_project(proj["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_project(proj["id"], _ADMIN))
        assert after["status"] == "OPEN"


class TestMechanicDutyCycle:
    def test_off_duty_blocks_dispatch_then_on_duty_restores(self, api):
        """PRD section 3.4: "a mechanic may be set `OFF_DUTY` only while their
        `active_work_order_count` is zero, and an off-duty mechanic returns
        `OFF_DUTY` → `AVAILABLE` on demand. ... Dispatch assigns an `OPEN` order
        to a mechanic by `mechanic_id`, but only when that mechanic's `status`
        is `AVAILABLE` ... a mechanic who is `ON_JOB`, `OFF_DUTY`, or already
        carrying two active orders is refused with `ERR_MECHANIC_UNAVAILABLE`."

        Design: Corner/state_machines/mechanic_off_duty_cycle_and_dispatch_block
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-203")
        wo = make_work_order(equip["id"], kind="REPAIR")

        off = validate_success(api.off_duty_mechanic(mech["id"], _ADMIN))
        assert off["status"] == "OFF_DUTY"
        err = api.dispatch_work_order(wo["id"], {"mechanic_id": mech["id"]}, _ADMIN)
        validate_error(err, ApiErrorId.ERR_MECHANIC_UNAVAILABLE)
        assert err.status_code == 409

        on = validate_success(api.on_duty_mechanic(mech["id"], _ADMIN))
        assert on["status"] == "AVAILABLE"
        dispatched = validate_success(
            api.dispatch_work_order(wo["id"], {"mechanic_id": mech["id"]}, _ADMIN)
        )
        assert dispatched["status"] == "DISPATCHED"

    def test_off_duty_with_active_work_rejected(self, api):
        """PRD section 3.4: "a mechanic may be set `OFF_DUTY` only while their
        `active_work_order_count` is zero".

        Design: Corner/state_machines/mechanic_off_duty_with_active_work_returns_invalid_state
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-204")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], mech["id"])

        resp = api.off_duty_mechanic(mech["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        mech_after = validate_success(api.get_mechanic(mech["id"], _ADMIN))
        assert mech_after["status"] == "AVAILABLE"
        assert mech_after["active_work_order_count"] == 1


class TestLowboyServiceCycle:
    def test_out_of_service_lockout_while_on_haul_and_return_path(self, api):
        """PRD section 3.5: "A trailer is created `AVAILABLE` and can be taken
        `OUT_OF_SERVICE` and returned to `AVAILABLE` on demand; while a haul
        is underway it sits `ON_Haul`." PRD section 2.7 priority 7 makes the
        out-of-service action illegal from `ON_Haul` (`ERR_INVALID_STATE`).

        Design: Corner/state_machines/lowboy_out_of_service_cycle_and_on_haul_lockout
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, pa, equip = make_fleet_bundle()
        pb = make_project(project_code="PRJ-205B")
        lb = make_lowboy(lowboy_code="LB-205")
        asg = make_active_assignment(equip, pa, start_date="2026-08-03", end_date="2026-08-06")
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])

        tj = make_transport_job(
            equip["id"], pa["id"], pb["id"], lb["id"],
            depart_at="2026-08-05T08:00:00Z", arrive_at="2026-08-05T12:00:00Z",
        )
        validate_success(api.depart_transport_job(tj["id"], _DISP))

        err = api.out_of_service_lowboy(lb["id"], _DISP)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE)
        assert err.status_code == 409

        validate_success(api.deliver_transport_job(tj["id"], _DISP))
        oos = validate_success(api.out_of_service_lowboy(lb["id"], _DISP))
        assert oos["status"] == "OUT_OF_SERVICE"
        back = validate_success(api.return_to_service_lowboy(lb["id"], _DISP))
        assert back["status"] == "AVAILABLE"


class TestAssignmentInvalidTransitions:
    def test_second_activate_returns_invalid_state(self, api):
        """PRD section 3.2: activation is defined on a `RESERVED` assignment;
        PRD section 2.7 priority 7: "State-machine legality — the requested
        transition exists from the target's current state — else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/assignment_activate_from_active_returns_invalid_state
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        resp = api.activate_assignment(asg["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert after["status"] == "ACTIVE"

    def test_close_from_reserved_rejected(self, api):
        """PRD section 3.6: "A `FleetAdmin` closes an assignment that is
        `ACTIVE` or `SUSPENDED`"; close from RESERVED is not a declared
        transition, so priority 7 fires.

        Design: Corner/state_machines/assignment_close_from_reserved_and_cancel_from_active_rejected
        """
        cls, project, equip = make_fleet_bundle()
        asg = make_reserved_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        resp = api.close_assignment(asg["id"], {"close_reason": "COMPLETED"}, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert after["status"] == "RESERVED"

    def test_cancel_from_active_rejected(self, api):
        """PRD section 3.2: "A reservation that is no longer wanted can be
        cancelled while still `RESERVED` (`RESERVED` → `CANCELLED`)" — cancel
        is not declared from ACTIVE.

        Design: Corner/state_machines/assignment_close_from_reserved_and_cancel_from_active_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        resp = api.cancel_assignment(asg["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert after["status"] == "ACTIVE"


class TestTransportInvalidTransitions:
    def test_deliver_from_planned_rejected(self, api):
        """PRD section 3.5: "Delivery (`EN_ROUTE` → `DELIVERED`) returns the
        unit `IN_TRANSIT` → `IDLE`" — deliver is declared only from EN_ROUTE.
        PRD section 2.7 priority 7: "State-machine legality — the requested
        transition exists from the target's current state — else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/transport_deliver_from_planned_and_cancel_from_delivered_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, pa, equip = make_fleet_bundle()
        pb = make_project(project_code="PRJ-B")
        lb = make_lowboy()
        asg = make_active_assignment(equip, pa, start_date="2026-08-03", end_date="2026-08-06")
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])
        tj = make_transport_job(
            equip["id"], pa["id"], pb["id"], lb["id"],
            depart_at="2026-08-05T08:00:00Z", arrive_at="2026-08-05T12:00:00Z",
        )
        resp = api.deliver_transport_job(tj["id"], _DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_transport_job(tj["id"], _DISP))
        assert after["status"] == "PLANNED"

    def test_cancel_from_delivered_rejected(self, api):
        """PRD section 3.5: "Cancelling is possible only from `PLANNED`" — a
        DELIVERED job is terminal for cancel.

        Design: Corner/state_machines/transport_deliver_from_planned_and_cancel_from_delivered_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, pa, equip = make_fleet_bundle()
        pb = make_project(project_code="PRJ-B")
        lb = make_lowboy()
        asg = make_active_assignment(equip, pa, start_date="2026-08-03", end_date="2026-08-06")
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])
        tj = make_transport_job(
            equip["id"], pa["id"], pb["id"], lb["id"],
            depart_at="2026-08-05T08:00:00Z", arrive_at="2026-08-05T12:00:00Z",
        )
        validate_success(api.depart_transport_job(tj["id"], _DISP))
        validate_success(api.deliver_transport_job(tj["id"], _DISP))
        resp = api.cancel_transport_job(tj["id"], _DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_transport_job(tj["id"], _DISP))
        assert after["status"] == "DELIVERED"


class TestTransportSideEffects:
    def test_depart_and_deliver_flip_lowboy_and_site(self, api):
        """PRD section 3.5: "Departure (`PLANNED` → `EN_ROUTE`) requires the
        unit to be `IN_TRANSIT` and flips the lowboy to `ON_Haul`. Delivery
        (`EN_ROUTE` → `DELIVERED`) returns the unit `IN_TRANSIT` → `IDLE`,
        writes the destination into `current_site_id`, and frees the lowboy
        back to `AVAILABLE`."

        Design: Corner/state_machines/transport_depart_and_deliver_side_effects
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, pa, equip = make_fleet_bundle()
        pb = make_project(project_code="PRJ-B")
        lb = make_lowboy()
        asg = make_active_assignment(equip, pa, start_date="2026-08-03", end_date="2026-08-06")
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])
        tj = make_transport_job(
            equip["id"], pa["id"], pb["id"], lb["id"],
            depart_at="2026-08-05T08:00:00Z", arrive_at="2026-08-05T12:00:00Z",
        )

        departed = validate_success(api.depart_transport_job(tj["id"], _DISP))
        assert departed["status"] == "EN_ROUTE"
        lb_mid = validate_success(api.get_lowboy(lb["id"], _DISP))
        assert lb_mid["status"] == "ON_Haul"

        delivered = validate_success(api.deliver_transport_job(tj["id"], _DISP))
        assert delivered["status"] == "DELIVERED"
        equip_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert equip_after["availability_status"] == "IDLE"
        assert equip_after["current_site_id"] == pb["id"]
        lb_after = validate_success(api.get_lowboy(lb["id"], _DISP))
        assert lb_after["status"] == "AVAILABLE"


class TestDamageInvalidTransitions:
    def test_dispute_from_filed_rejected(self, api):
        """PRD section 3.8: "From `ASSESSED` the report can travel three roads.
        A `ProjectManager` may dispute it" — dispute is not declared from
        FILED.

        Design: Corner/state_machines/damage_dispute_from_filed_and_confirm_from_disputed_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d = make_damage_report(equip["id"], project["id"],
                               line_items=[{"description": "x", "amount_cents": 1000}])
        resp = api.dispute_damage_report(d["id"], {"dispute_note": "too early"}, _PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_damage_report(d["id"], _ADMIN))
        assert after["status"] == "FILED"

    def test_confirm_from_disputed_rejected(self, api):
        """PRD section 3.8: "A confirmed report moves `ASSESSED` → `CONFIRMED`"
        — confirm is declared from ASSESSED only, so a DISPUTED report cannot
        be confirmed directly.

        Design: Corner/state_machines/damage_dispute_from_filed_and_confirm_from_disputed_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d = make_damage_report(equip["id"], project["id"],
                               line_items=[{"description": "y", "amount_cents": 2000}])
        assess_damage(d["id"])
        dispute_damage(d["id"], "contested")
        resp = api.confirm_damage_report(d["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_damage_report(d["id"], _ADMIN))
        assert after["status"] == "DISPUTED"
        proj = validate_success(api.get_project(project["id"], _ADMIN))
        assert proj["billed_total_cents"] == 0


class TestDamageVoidLockdown:
    def test_void_from_confirmed_rejected_and_void_from_filed_succeeds(self, api):
        """PRD section 3.8: "a report still in `FILED` or `ASSESSED` can be
        voided (`→ VOIDED`), which posts nothing to any ledger."

        Design: Corner/state_machines/damage_void_from_confirmed_terminal_lockdown
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d_a = make_damage_report(equip["id"], project["id"],
                                 line_items=[{"description": "x", "amount_cents": 1000}])
        assess_damage(d_a["id"])
        confirm_damage(d_a["id"])

        resp = api.void_damage_report(d_a["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        d_b = make_damage_report(equip["id"], project["id"], description="d2",
                                 line_items=[{"description": "y", "amount_cents": 2000}])
        voided = validate_success(api.void_damage_report(d_b["id"], _ADMIN))
        assert voided["status"] == "VOIDED"

        proj = validate_success(api.get_project(project["id"], _ADMIN))
        assert proj["billed_total_cents"] == 1000


class TestWorkOrderInvalidTransitions:
    def test_complete_from_dispatched_rejected(self, api):
        """PRD section 3.4: "Completing an `IN_PROGRESS` order carries the same
        mechanic-ownership check and closes the loop" — complete is declared
        only from IN_PROGRESS, so a DISPATCHED order cannot be completed.
        PRD section 2.7 priority 7: "State-machine legality — the requested
        transition exists from the target's current state — else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/work_order_complete_from_dispatched_and_cancel_from_completed_rejected
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-212")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], mech["id"])
        resp = api.complete_work_order(wo["id"], make_mechanic_headers(mech["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_work_order(wo["id"], _ADMIN))
        assert after["status"] == "DISPATCHED"

    def test_cancel_from_completed_rejected(self, api):
        """PRD section 3.4: "An order can also be cancelled, by a `FleetAdmin`,
        from `OPEN` or `DISPATCHED` but never from `IN_PROGRESS`" — and by
        extension never from terminal COMPLETED (priority-7 state gate).

        Design: Corner/state_machines/work_order_complete_from_dispatched_and_cancel_from_completed_rejected
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-212")
        wo = make_work_order(equip["id"], kind="REPAIR")
        run_repair_to_completion(wo["id"], mech["id"])
        resp = api.cancel_work_order(wo["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = validate_success(api.get_work_order(wo["id"], _ADMIN))
        assert after["status"] == "COMPLETED"


class TestDisposeLockdown:
    def test_markdown_on_disposed_returns_not_available(self, api):
        """PRD section 2.5: "a unit is created `IDLE` and `DISPOSED` is
        terminal." PRD section 3.4 makes mark-down legal only from IDLE or
        ON_RENT; priority 8 maps the availability failure to
        `ERR_EQUIPMENT_NOT_AVAILABLE`.

        Design: Corner/state_machines/equipment_markdown_from_disposed_returns_not_available
        """
        cls = make_class()
        equip = make_equipment(cls["id"])
        validate_success(api.dispose_equipment(equip["id"], {"disposal_method": "SALE"}, _ADMIN))
        resp = api.mark_down_equipment(equip["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_AVAILABLE)
        assert resp.status_code == 409
        after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert after["availability_status"] == "DISPOSED"
