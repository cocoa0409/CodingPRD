"""Valve groups, control commands, pump-and-valve interlock, offline-local.

PRD references:
  - §3.3 Valve Groups and the Pump-and-Valve Interlock
  - §3.4 Control Commands, Feedback, and the Offline-Local Branch
  - §2.10 Concurrency and Race Resolution (interlock + duplicate feedback)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_control_command,
    assert_valve_group,
    assert_exactly_one_succeeds,
    create_control_command,
    create_control_command_payload,
    create_plot,
    create_tenant,
    create_valve_group,
    create_valve_group_payload,
    dispatch_command,
    drive_command_to_dispatching,
    drive_command_to_executed,
    drive_command_to_executing,
    feedback,
    feedback_payload,
    find_alerts,
    list_alerts,
    list_audit_logs,
    find_audit_entries,
    run_race,
    setup_full_active_scenario,
    setup_pump_with_two_valve_groups,
    unique_pump_id,
    unique_valve_id,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §3.3 — Valve group constraints
# ===========================================================================
class TestValveGroupConstraints:
    def test_create_valve_group_succeeds(self, api, water_admin_headers):
        """PRD §3.3: 'A WaterAdmin configures a valve group by
        supplying the owning tenant_id, a name, the pump_id of the
        pump that feeds every valve in the group, the ordered
        valve_ids array, the control_mode (one of SEQUENTIAL or
        PARALLEL), and the max_parallel_valves cap.'

        Claim: valid valve-group creation returns 201 with the
        canonical fields.
        """
        tenant = create_tenant()
        res = api.create_valve_group(
            create_valve_group_payload(
                tenant_id=tenant["id"], control_mode="PARALLEL",
                max_parallel_valves=4,
                valve_ids=[unique_valve_id(), unique_valve_id()],
            ),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_valve_group(data)

    def test_empty_valve_ids_rejected(self, api, water_admin_headers):
        """PRD §3.3: 'the valve_ids array must be non-empty (and may
        carry at most 16 entries)'.
        PRD §3.3: 'Three internal constraints are enforced together
        as ERR_VALVE_GROUP_INVALID (422)'.

        Claim: empty valve_ids → ERR_VALVE_GROUP_INVALID.
        """
        tenant = create_tenant()
        res = api.create_valve_group(
            create_valve_group_payload(
                tenant_id=tenant["id"], valve_ids=[]
            ),
            water_admin_headers,
        )
        validate_error(res, "ERR_VALVE_GROUP_INVALID")

    def test_sequential_with_max_parallel_greater_than_one_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §3.3: 'control_mode of SEQUENTIAL forces
        max_parallel_valves to equal 1.'
        PRD §3.3: 'Three internal constraints are enforced together
        as ERR_VALVE_GROUP_INVALID (422)'.

        Claim: SEQUENTIAL + max_parallel_valves=2 → ERR_VALVE_GROUP_INVALID.
        """
        tenant = create_tenant()
        res = api.create_valve_group(
            create_valve_group_payload(
                tenant_id=tenant["id"],
                control_mode="SEQUENTIAL",
                max_parallel_valves=2,
            ),
            water_admin_headers,
        )
        validate_error(res, "ERR_VALVE_GROUP_INVALID")

    def test_max_parallel_zero_rejected(self, api, water_admin_headers):
        """PRD §3.3: 'the max_parallel_valves must be at least 1'.

        Claim: max_parallel_valves=0 → ERR_VALVE_GROUP_INVALID.
        """
        tenant = create_tenant()
        res = api.create_valve_group(
            create_valve_group_payload(
                tenant_id=tenant["id"],
                control_mode="PARALLEL",
                max_parallel_valves=0,
            ),
            water_admin_headers,
        )
        validate_error(res, "ERR_VALVE_GROUP_INVALID")


# ===========================================================================
# §3.4 — ControlCommand creation: referential check
# ===========================================================================
class TestControlCommandCreate:
    def test_valve_group_pump_mismatch_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'Two referential checks fire at creation: the
        chosen valve group must exist, and its pump_id must match
        the Plot.pump_id of the plot that owns the driving plan
        (reached via IrrigationPlan.plot_id). A mismatch is rejected
        with ERR_VALVE_GROUP_PUMP_MISMATCH (422).'

        Claim: valve group on a different pump than Plot.pump_id →
        ERR_VALVE_GROUP_PUMP_MISMATCH.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        # Create a second valve group on a DIFFERENT pump than plot.
        other_pump = unique_pump_id("otherpump")
        wrong_vg = create_valve_group(
            ctx["tenant"]["id"],
            pump_id=other_pump,
            control_mode="SEQUENTIAL",
            max_parallel_valves=1,
        )
        res = api.create_control_command(
            create_control_command_payload(
                plan_id=ctx["plan"]["id"],
                valve_group_id=wrong_vg["id"],
                requested_volume_liters=100.0,
            ),
            water_admin_headers,
        )
        validate_error(res, "ERR_VALVE_GROUP_PUMP_MISMATCH")

    def test_create_control_command_returns_pending(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'A successful creation reserves the volume and
        stores the command in PENDING.'

        Claim: POST /control-commands returns 201 with status=PENDING.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        res = api.create_control_command(
            create_control_command_payload(
                plan_id=ctx["plan"]["id"],
                valve_group_id=ctx["valve_group"]["id"],
                requested_volume_liters=100.0,
            ),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_control_command(data)
        assert data["status"] == "PENDING"


# ===========================================================================
# §3.3 / §3.4 — Pump-and-valve interlock
# ===========================================================================
class TestPumpValveInterlock:
    def test_sequential_pump_busy_blocks_second_dispatch(
        self, api, water_admin_headers,
    ):
        """PRD §3.3: 'When a ControlCommand is dispatched, the system
        locates the pump that feeds the target valve group via
        ValveGroup.pump_id. If any other ControlCommand whose target
        group sits on the same pump_id is currently in DISPATCHING
        or EXECUTING, the new dispatch is allowed only if every
        active command on that pump targets a valve group whose
        control_mode is PARALLEL. In every other configuration —
        that is, whenever at least one of the active commands on the
        same pump targets a SEQUENTIAL group — the new dispatch is
        rejected with ERR_PUMP_INTERLOCK_BUSY (409).'

        Claim: dispatching a SEQUENTIAL cmd while another SEQUENTIAL
        cmd is EXECUTING on the same pump → ERR_PUMP_INTERLOCK_BUSY.
        """
        ctx = setup_pump_with_two_valve_groups(
            vg1_mode="SEQUENTIAL", vg1_max=1,
            vg2_mode="SEQUENTIAL", vg2_max=1,
        )
        # First command: drive to EXECUTING (occupies the pump).
        first = drive_command_to_executing(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        assert first["status"] == "EXECUTING"
        # Second command on the SAME pump via vg2.
        second_pending = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group_2"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.dispatch_command(
            second_pending["id"], water_admin_headers,
        )
        validate_error(res, "ERR_PUMP_INTERLOCK_BUSY")

    def test_parallel_groups_co_exist_on_same_pump(
        self, api, water_admin_headers,
    ):
        """PRD §3.3: 'the new dispatch is allowed only if every
        active command on that pump targets a valve group whose
        control_mode is PARALLEL.'

        Claim: two PARALLEL valve groups on the same pump → both
        dispatches succeed (no interlock).
        """
        ctx = setup_pump_with_two_valve_groups(
            vg1_mode="PARALLEL", vg1_max=2,
            vg2_mode="PARALLEL", vg2_max=2,
        )
        first = drive_command_to_executing(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        assert first["status"] == "EXECUTING"
        second_pending = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group_2"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.dispatch_command(
            second_pending["id"], water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DISPATCHING"

    def test_concurrent_sequential_dispatch_exactly_one_wins(
        self, api,
    ):
        """PRD §2.10: 'When two ControlCommand dispatches target valve
        groups that share the same pump_id and at least one group is
        in SEQUENTIAL mode, the system serialises on the status flip
        from PENDING to DISPATCHING for that pump; the loser receives
        ERR_PUMP_INTERLOCK_BUSY with HTTP 409.'

        Claim: two simultaneous SEQUENTIAL dispatches on the same
        pump → exactly one succeeds, the other gets HTTP 4xx.
        """
        ctx = setup_pump_with_two_valve_groups(
            vg1_mode="SEQUENTIAL", vg1_max=1,
            vg2_mode="SEQUENTIAL", vg2_max=1,
        )
        cc1 = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        cc2 = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group_2"]["id"],
            requested_volume_liters=100.0,
        )
        from test_helpers import TEST_USERS
        results = run_race(
            lambda: api.dispatch_command(
                cc1["id"], TEST_USERS["water_admin_headers"]
            ),
            lambda: api.dispatch_command(
                cc2["id"], TEST_USERS["water_admin_headers"]
            ),
        )
        assert_exactly_one_succeeds(*results)


# ===========================================================================
# §3.4 — Dispatch happy path + audit
# ===========================================================================
class TestDispatchHappyPath:
    def test_dispatch_pending_to_dispatching(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'Dispatching the command moves it from PENDING to
        DISPATCHING'.

        Claim: POST /dispatch on a PENDING command → status=DISPATCHING.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.dispatch_command(cmd["id"], water_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DISPATCHING"

    def test_dispatch_appends_control_command_issued_audit(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'An AuditLog record with action_type of
        CONTROL_COMMAND_ISSUED is appended on a successful dispatch.'

        Claim: an audit entry with action_type==CONTROL_COMMAND_ISSUED
        is created.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_dispatching(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        entries = list_audit_logs(
            params={"action_type": "CONTROL_COMMAND_ISSUED", "limit": 100}
        )
        matched = find_audit_entries(
            entries, action_type="CONTROL_COMMAND_ISSUED",
            subject_id=cmd["id"],
        )
        assert len(matched) >= 1


# ===========================================================================
# §3.4 — Offline-local branch
# ===========================================================================
class TestOfflineLocalDispatch:
    def test_offline_header_routes_to_offline_local(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'when a caller attaches the X-Device-Mode: OFFLINE
        header to the dispatch request, the command transitions instead
        from PENDING to OFFLINE_LOCAL and the dispatch_mode field is
        set to LOCAL_DEGRADED'.

        Claim: dispatch with X-Device-Mode: OFFLINE → status=OFFLINE_LOCAL,
        dispatch_mode=LOCAL_DEGRADED.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        headers = dict(water_admin_headers)
        headers["X-Device-Mode"] = "OFFLINE"
        res = api.dispatch_command(cmd["id"], headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "OFFLINE_LOCAL"
        assert data["dispatch_mode"] == "LOCAL_DEGRADED"

    def test_remote_dispatch_default_mode_remote(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'With the header absent the dispatch_mode is
        REMOTE.'

        Claim: dispatch without X-Device-Mode header →
        dispatch_mode=REMOTE.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.dispatch_command(cmd["id"], water_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["dispatch_mode"] == "REMOTE"


# ===========================================================================
# §3.4 — Feedback transitions and side effects
# ===========================================================================
class TestFeedbackTransitions:
    def test_started_phase_dispatching_to_executing(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'A STARTED feedback advances DISPATCHING →
        EXECUTING with no other side effect.'

        Claim: phase=STARTED on a DISPATCHING cmd → status=EXECUTING.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_dispatching(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.feedback_command(
            cmd["id"], feedback_payload(phase="STARTED"),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "EXECUTING"

    def test_completed_phase_executing_to_executed_sets_actual_volume(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'A COMPLETED feedback carries an
        actual_volume_liters (which must be at least zero) and advances
        either EXECUTING → EXECUTED or OFFLINE_LOCAL → EXECUTED; on
        success the system stores actual_volume_liters on the
        command, sets feedback_received_at to the current time,
        refreshes the parent Plot.last_irrigated_at, increases
        WaterQuota.final_used_liters by actual_volume_liters'.

        Claim: COMPLETED feedback → status=EXECUTED, actual_volume_liters
        stored, feedback_received_at populated.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_executing(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.feedback_command(
            cmd["id"],
            feedback_payload(phase="COMPLETED", actual_volume_liters=98.5),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "EXECUTED"
        assert data["actual_volume_liters"] == pytest.approx(98.5, abs=0.01)
        assert data.get("feedback_received_at") is not None

    def test_completed_refreshes_plot_last_irrigated_at(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: '...refreshes the parent Plot.last_irrigated_at'.

        Claim: after a COMPLETED feedback, GET /plots/{id} has a
        non-null last_irrigated_at.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        assert ctx["plot"].get("last_irrigated_at") is None
        drive_command_to_executed(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
            actual_volume_liters=100.0,
        )
        res = api.get_plot(ctx["plot"]["id"], water_admin_headers)
        plot = validate_success(res, expected_status=200)
        assert plot.get("last_irrigated_at") is not None

    def test_error_phase_with_valve_fault_emits_alert(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'when the failure_reason equals \\'VALVE_FAULT\\',
        emits an Alert with rule_code of VALVE_FAULT and subject_type
        of VALVE_GROUP.'

        Claim: ERROR feedback with failure_reason=VALVE_FAULT → Alert
        emitted with rule_code=VALVE_FAULT and subject_type=VALVE_GROUP.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_dispatching(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.feedback_command(
            cmd["id"],
            feedback_payload(phase="ERROR", failure_reason="VALVE_FAULT"),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "FAILED"
        alerts = list_alerts(params={"limit": 100})
        matched = find_alerts(
            alerts, rule_code="VALVE_FAULT",
            subject_type="VALVE_GROUP",
            subject_id=ctx["valve_group"]["id"],
        )
        assert len(matched) >= 1, (
            "PRD §3.4 says VALVE_FAULT failure_reason emits an Alert "
            "on the VALVE_GROUP"
        )

    def test_duplicate_completed_feedback_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'Feedback for a command not in the expected
        state (for instance, a second COMPLETED feedback for a
        command that has already reached EXECUTED) is rejected with
        ERR_FEEDBACK_ALREADY_RECORDED (409)'.

        Claim: second COMPLETED on EXECUTED → ERR_FEEDBACK_ALREADY_RECORDED.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_executed(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
            actual_volume_liters=100.0,
        )
        # Second COMPLETED on the same EXECUTED command.
        res = api.feedback_command(
            cmd["id"],
            feedback_payload(phase="COMPLETED", actual_volume_liters=10.0),
            water_admin_headers,
        )
        validate_error(res, "ERR_FEEDBACK_ALREADY_RECORDED")

    def test_concurrent_completed_feedback_exactly_one_wins(
        self, api,
    ):
        """PRD §2.10: 'When two devices post EXECUTED feedback for the
        same ControlCommand, the system serialises on the status flip
        from EXECUTING to EXECUTED; only the first feedback advances
        state and debits the quota, and the duplicate is rejected with
        ERR_FEEDBACK_ALREADY_RECORDED and HTTP 409.'

        Claim: two simultaneous COMPLETED feedbacks on EXECUTING cmd
        → exactly one succeeds.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_executing(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        from test_helpers import TEST_USERS
        results = run_race(
            lambda: api.feedback_command(
                cmd["id"],
                feedback_payload(phase="COMPLETED", actual_volume_liters=100.0),
                TEST_USERS["water_admin_headers"],
            ),
            lambda: api.feedback_command(
                cmd["id"],
                feedback_payload(phase="COMPLETED", actual_volume_liters=99.0),
                TEST_USERS["water_admin_headers"],
            ),
        )
        assert_exactly_one_succeeds(*results)


# ===========================================================================
# §3.4 — Suspend cascade kills PENDING commands
# ===========================================================================
class TestSuspendCascadesPendingCommands:
    def test_suspend_active_plan_fails_pending_commands(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'Suspension has two cross-entity cascades: every
        ControlCommand on the plan whose status is PENDING is moved
        to FAILED with failure_reason set to \\'PLAN_SUSPENDED\\''.

        Claim: PENDING commands on a plan transition to FAILED with
        failure_reason=='PLAN_SUSPENDED' when the plan is suspended.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=1000.0)
        cmd = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        assert cmd["status"] == "PENDING"
        # Suspend the parent plan.
        res = api.suspend_plan(
            ctx["plot"]["id"], ctx["plan"]["id"], water_admin_headers,
        )
        validate_success(res, expected_status=200)
        # Re-fetch the command.
        res = api.get_control_command(cmd["id"], water_admin_headers)
        cmd_after = validate_success(res, expected_status=200)
        assert cmd_after["status"] == "FAILED"
        assert cmd_after.get("failure_reason") == "PLAN_SUSPENDED"
