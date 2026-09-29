"""Lifecycle coverage: initial states, declared transitions, preconditions,
cascades, terminal lockdown and the two automatic bubble-up transitions."""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    BackgroundStatus,
    ConstraintStatus,
    CoreLoadPatternStatus,
    Craft,
    ExecutionStatus,
    HoldPointType,
    OutageStatus,
    ReservationPurpose,
    ReservationStatus,
    RwpStatus,
    SchedulePosture,
    StartupTestStatus,
    TrainingStatus,
    WorkOrderStatus,
    WorkerStatus,
    api_client,
    assert_same_instant,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_core_load_pattern,
    given_draft_rwp,
    given_executing_outage,
    given_outage,
    given_planned_work_order,
    given_pool_cell_reservation,
    given_rad_area,
    given_reviewed_outage,
    given_schedule_activity,
    given_spent_fuel_pool,
    given_startup_test,
    given_started_activity,
    given_supplemental_worker,
    given_work_order,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    read_activity,
    read_outage,
    read_pattern,
    read_pool,
    read_reservation,
    read_rwp,
    read_startup_test,
    read_work_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInitialStates:
    def test_five_machines_open_in_their_declared_initial_states(self):
        """One pass over five entities, including the activity's two independent
        dimensions which initialise to NOT_STARTED and CLEAR separately.

        PRD 3.4: "At creation the predicate is evaluated exactly once: the
        activity is created `BLOCKED` when a predecessor is supplied whose
        `execution_status` is anything other than `COMPLETE`, and `CLEAR`
        otherwise — including the case where the supplied predecessor is already
        `COMPLETE`."

        Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_states
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24", required_training_modules=4)
        assert outage["status"] == OutageStatus.PLANNING

        work_order = given_work_order(outage["id"], title="Feedwater pump overhaul")
        assert work_order["status"] == WorkOrderStatus.SCOPED

        activity = given_schedule_activity(
            outage["id"], label="A1", planned_start_offset_hours=0, planned_duration_hours=100
        )
        assert activity["execution_status"] == ExecutionStatus.NOT_STARTED
        assert activity["constraint_status"] == ConstraintStatus.CLEAR

        pattern = given_core_load_pattern(outage["id"])
        assert pattern["status"] == CoreLoadPatternStatus.DRAFT
        assert pattern["created_by_user_id"] == "re-alpha"
        assert pattern["approved_by_user_id"] is None

        worker = given_supplemental_worker(
            outage["id"],
            full_name="R. Kowalski",
            craft=Craft.PIPEFITTER,
            sponsoring_contractor="Northline Mechanical",
        )
        assert worker["status"] == WorkerStatus.REQUESTED
        assert worker["background_status"] == BackgroundStatus.PENDING
        assert worker["training_status"] == TrainingStatus.PENDING
        assert worker["training_modules_completed"] == 0
        assert worker["badge_number"] is None


class TestLockScope:
    def _planning_outage_ready_to_lock(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        work_order = given_approved_work_order(
            outage["id"],
            title="Feedwater pump overhaul",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        return outage, work_order

    def test_the_happy_path_stamps_the_logical_clock_and_bumps_the_version_once(self):
        """Locking scope stamps scope_locked_at from the clock reading at request
        time, advances the version by exactly one, and reprojects the roll-up at
        the tier-one 8 percent rate.

        PRD 3.6: "On success `scope_locked_at` is stamped with the current
        logical-clock instant."

        Design: Corner/state_machines/lock_scope_moves_outage_from_planning_to_scope_locked
        """
        outage, work_order = self._planning_outage_ready_to_lock()
        before = read_outage(outage["id"])
        assert before["scope_locked_at"] is None
        set_clock("2026-08-20T06:00:00Z")

        locked = validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers())
        )
        assert locked["status"] == OutageStatus.SCOPE_LOCKED
        assert_same_instant(locked["scope_locked_at"], "2026-08-20T06:00:00Z", "scope_locked_at")
        assert locked["version"] == before["version"] + 1
        assert locked["approved_scope_cost_usd"] == pytest.approx(1000.00, abs=0.01)
        assert locked["scope_contingency_usd"] == pytest.approx(80.00, abs=0.01)
        assert locked["total_scope_cost_usd"] == pytest.approx(1080.00, abs=0.01)
        assert read_work_order(work_order["id"])["status"] == WorkOrderStatus.APPROVED

    def test_without_an_approved_work_order_the_gate_reports_the_work_order_state(self):
        """With the reload design already approved but no work order past PLANNED,
        the refusal names the work-order precondition and leaves the outage in
        PLANNING with no stamp.

        PRD 3.6: "The outage must own at least one work order in `APPROVED`,
        otherwise the request is rejected with `ERR_WORK_ORDER_STATE_INVALID` — an
        outage with nothing approved has no baseline to freeze."

        Design: Corner/state_machines/lock_scope_enforces_its_two_preconditions_in_declared_order
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        given_planned_work_order(outage["id"], title="Feedwater pump overhaul")

        validate_error(
            api_client.lock_scope(outage["id"], make_outage_director_headers()),
            ApiErrorId.WORK_ORDER_STATE_INVALID.value,
        )
        after = read_outage(outage["id"])
        assert after["status"] == OutageStatus.PLANNING
        assert after["scope_locked_at"] is None

    def test_with_only_a_draft_reload_design_the_gate_reports_the_pattern(self):
        """An approved work order satisfies the first condition, so the second
        surfaces: a DRAFT pattern does not open the gate, and approving it does.

        PRD 3.6: "And the outage must own at least one core loading pattern in
        `APPROVED`, otherwise `ERR_CORE_LOAD_PATTERN_NOT_APPROVED`."

        Design: Corner/state_machines/lock_scope_enforces_its_two_preconditions_in_declared_order
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        pattern = given_core_load_pattern(outage["id"])
        given_approved_work_order(outage["id"], title="Feedwater pump overhaul")

        validate_error(
            api_client.lock_scope(outage["id"], make_outage_director_headers()),
            ApiErrorId.CORE_LOAD_PATTERN_NOT_APPROVED.value,
        )
        assert read_outage(outage["id"])["status"] == OutageStatus.PLANNING

        validate_success(
            api_client.approve_core_load_pattern(
                pattern["id"], make_reactor_engineer_headers("re-beta")
            )
        )
        locked = validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers())
        )
        assert locked["status"] == OutageStatus.SCOPE_LOCKED

    def test_the_cascade_reaches_only_the_scoped_branch_of_the_scope(self):
        """The SCOPED work order is auto-deferred and drags its activity and its
        draft permit down with it, while the APPROVED work order's own branch is
        left untouched and no dose row is written anywhere.

        PRD 3.6: "For each work order deferred by that step, its activities in
        `NOT_STARTED` move to `CANCELLED` and its permits in `DRAFT` or
        `HELD_FOR_ALARA` move to `VOIDED` with `void_reason` set to
        `WORK_ORDER_DEFERRED`; because a `SCOPED` work order can hold no approved
        permit, no dose ledger row is appended anywhere in this cascade."

        Design: Corner/state_machines/lock_scope_cascades_down_only_into_scoped_work_orders
        """
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(area_code="CTMT-EL471", dose_rate_mrem_per_hr=25)
        outage = given_outage(designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        approved = given_approved_work_order(
            outage["id"],
            title="WO-A feedwater pump overhaul",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        activity_a = given_schedule_activity(
            outage["id"],
            label="A-A pump overhaul",
            planned_start_offset_hours=0,
            planned_duration_hours=10,
            work_order_id=approved["id"],
        )
        scoped = given_work_order(
            outage["id"],
            title="WO-B insulation replacement",
            estimated_hours=40,
            estimated_cost_usd=2000,
            estimated_dose_mrem=0,
            requires_rad_work=True,
        )
        activity_b = given_schedule_activity(
            outage["id"],
            label="A-B insulation",
            planned_start_offset_hours=0,
            planned_duration_hours=40,
            work_order_id=scoped["id"],
        )
        permit = given_draft_rwp(scoped["id"], rad_area["id"])

        locked = validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers())
        )
        assert locked["status"] == OutageStatus.SCOPE_LOCKED

        deferred = read_work_order(scoped["id"])
        assert deferred["status"] == WorkOrderStatus.DEFERRED
        assert deferred["deferral_reason"] == "SCOPE_LOCK_AUTO_DEFERRAL"
        assert read_activity(activity_b["id"])["execution_status"] == ExecutionStatus.CANCELLED
        voided = read_rwp(permit["id"])
        assert voided["status"] == RwpStatus.VOIDED
        assert voided["void_reason"] == "WORK_ORDER_DEFERRED"

        assert read_work_order(approved["id"])["status"] == WorkOrderStatus.APPROVED
        assert read_activity(activity_a["id"])["execution_status"] == ExecutionStatus.NOT_STARTED

        rows, _meta = validate_paginated(
            api_client.list_dose_transactions(permit["id"], make_outage_director_headers())
        )
        assert rows == []
        assert locked["dose_committed_mrem"] == pytest.approx(0.00, abs=0.01)
        assert locked["projected_duration_hours"] == pytest.approx(10.00, abs=0.01)
        assert locked["approved_scope_cost_usd"] == pytest.approx(1000.00, abs=0.01)


class TestInvalidAndIdempotentTransitions:
    def test_planning_a_work_order_twice_is_refused_and_writes_nothing(self):
        """plan is declared only out of SCOPED, so the second call is a
        not-declared transition and leaves both the status and the version where
        the first call left them.

        PRD 3.2: "An `OutagePlanner` moves it `SCOPED → PLANNED`; the work order
        must be in `SCOPED`, and the owning outage must be in `PLANNING`,
        `SCOPE_LOCKED` or `EXECUTION`, otherwise `ERR_OUTAGE_STATE_INVALID` is
        returned."

        Design: Corner/state_machines/planning_an_already_planned_work_order_rejected
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        planned = given_planned_work_order(outage["id"], title="Feedwater pump overhaul")
        assert planned["status"] == WorkOrderStatus.PLANNED

        validate_error(
            api_client.plan_work_order(planned["id"], make_outage_planner_headers()),
            ApiErrorId.WORK_ORDER_STATE_INVALID.value,
        )
        after = read_work_order(planned["id"])
        assert after["status"] == WorkOrderStatus.PLANNED
        assert after["version"] == planned["version"]

    def test_releasing_a_released_reservation_neither_succeeds_nor_double_credits(self):
        """release is declared only out of RESERVED, so the duplicate call is
        refused, the first release reason survives, and the pool ledger is not
        credited a second time.

        PRD 3.3: "Both `CONSUMED` and `RELEASED` are terminal."

        Design: Corner/state_machines/releasing_an_already_released_reservation_rejected
        """
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            cells_total=1200, cells_baseline_occupied=900, full_core_offload_reserve_cells=193
        )
        outage = given_outage(designation="1R24")
        reservation = given_pool_cell_reservation(
            outage["id"],
            pool["id"],
            cells_requested=250,
            purpose=ReservationPurpose.CONTINGENCY,
        )
        validate_success(
            api_client.release_pool_cell_reservation(
                reservation["id"],
                "Contingency offload not required",
                make_reactor_engineer_headers(),
            )
        )
        pool_after_release = read_pool(pool["id"])

        validate_error(
            api_client.release_pool_cell_reservation(
                reservation["id"], "Duplicate release", make_reactor_engineer_headers()
            ),
            ApiErrorId.POOL_RESERVATION_STATE_INVALID.value,
        )

        row = read_reservation(reservation["id"])
        assert row["status"] == ReservationStatus.RELEASED
        assert row["release_reason"] == "Contingency offload not required"

        final = read_pool(pool["id"])
        assert final["cells_reserved"] == 0
        assert final["cells_available"] == 300
        assert final["protected_cells_available"] == 107
        assert final["version"] == pool_after_release["version"]

    def test_a_reviewed_outage_refuses_both_a_second_review_and_a_relock(self):
        """REVIEWED is terminal, so neither a second review nor a lock-scope is
        admitted, and the figures the first review computed are not overwritten.

        PRD 3.6: "The lifecycle runs `PLANNING → SCOPE_LOCKED → EXECUTION →
        STARTUP → ONLINE → REVIEWED`, with `REVIEWED` terminal."

        Design: Corner/state_machines/reviewed_outage_rejects_every_further_transition
        """
        ctx = given_reviewed_outage(
            actual_duration_hours=780,
            actual_cost_usd=42000000,
            outage={
                "designation": "1R24",
                "duration_target_hours": 720,
                "dose_budget_total_mrem": 5000,
                "cost_budget_usd": 40000000,
            },
            work_order={
                "title": "Feedwater pump overhaul",
                "estimated_hours": 10,
                "estimated_cost_usd": 1000,
                "estimated_dose_mrem": 0,
            },
        )
        reviewed = ctx["outage"]
        assert reviewed["status"] == OutageStatus.REVIEWED

        validate_error(
            api_client.post_outage_review(
                ctx["outage_id"],
                {
                    "actual_duration_hours": 999,
                    "actual_cost_usd": 99000000,
                    "review_notes": "Second review attempt",
                },
                make_outage_director_headers(),
            ),
            ApiErrorId.OUTAGE_STATE_INVALID.value,
        )
        validate_error(
            api_client.lock_scope(ctx["outage_id"], make_outage_director_headers()),
            ApiErrorId.OUTAGE_STATE_INVALID.value,
        )

        after = read_outage(ctx["outage_id"])
        assert after["status"] == OutageStatus.REVIEWED
        assert after["version"] == reviewed["version"]
        assert after["actual_duration_hours"] == pytest.approx(780, abs=0.01)
        assert after["actual_cost_usd"] == pytest.approx(42000000, abs=0.01)
        assert after["duration_variance_pct"] == pytest.approx(8.33, abs=0.01)
        assert after["dose_variance_pct"] == pytest.approx(-100.00, abs=0.01)
        assert after["cost_variance_pct"] == pytest.approx(5.00, abs=0.01)
        assert after["outage_performance_index"] == pytest.approx(94.84, abs=0.01)
        assert after["adjusted_performance_index"] == pytest.approx(94.84, abs=0.01)


class TestAutomaticBubbleUpTransitions:
    def test_the_outage_stays_in_startup_until_the_second_test_is_satisfied(self):
        """Satisfying one of two tests leaves the compound parent in STARTUP;
        satisfying the second carries it to ONLINE inside that same request.

        PRD 3.6: "the outage moves to `ONLINE` automatically at the moment the
        last of its startup tests reaches `SATISFIED`, provided the outage was in
        `STARTUP` and every one of its tests is then `SATISFIED`."

        Design: Corner/state_machines/outage_bubbles_to_online_only_after_the_last_startup_test
        """
        ctx = given_executing_outage(
            outage={"designation": "1R24"},
            work_order={
                "title": "Feedwater pump overhaul",
                "estimated_hours": 10,
                "estimated_cost_usd": 1000,
                "estimated_dose_mrem": 0,
            },
        )
        first = given_startup_test(
            ctx["outage_id"],
            test_code="STP-01",
            sequence_index=1,
            hold_point_type=HoldPointType.STATION,
            predicted_reactivity_pcm=500,
        )
        second = given_startup_test(
            ctx["outage_id"],
            test_code="STP-02",
            sequence_index=2,
            hold_point_type=HoldPointType.STATION,
            predicted_reactivity_pcm=800,
        )
        validate_success(
            api_client.defer_work_order(
                ctx["work_order_id"],
                "Deferred to the next refueling window",
                make_outage_director_headers(),
            )
        )
        validate_success(
            api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers())
        )

        satisfied_first = validate_success(
            api_client.satisfy_startup_test(
                first["id"], 500, make_regulatory_affairs_headers("ra-beta")
            )
        )
        assert satisfied_first["status"] == StartupTestStatus.SATISFIED
        assert satisfied_first["reactivity_deviation_pcm"] == pytest.approx(0.00, abs=0.01)
        assert satisfied_first["satisfied_by_user_id"] == "ra-beta"
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.STARTUP

        satisfied_second = validate_success(
            api_client.satisfy_startup_test(
                second["id"], 800, make_regulatory_affairs_headers("ra-beta")
            )
        )
        assert satisfied_second["status"] == StartupTestStatus.SATISFIED
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.ONLINE

    def test_a_work_order_is_dragged_to_executing_then_complete_by_its_activity(self):
        """No work-order endpoint drives either hop: starting the single linked
        activity carries the order out of APPROVED, and completing it carries the
        order to COMPLETE, which is still inside the cost roll-up set.

        PRD 3.4: "The second hop bubbles upward: when the activity names a work
        order and every activity of that work order now sits in either `COMPLETE`
        or `CANCELLED`, the work order moves `EXECUTING → COMPLETE`."

        Design: Corner/state_machines/work_order_bubbles_to_complete_when_its_last_activity_completes
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        work_order = given_approved_work_order(
            outage["id"],
            title="WO-A feedwater pump overhaul",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        activity = given_schedule_activity(
            outage["id"],
            label="A-A pump overhaul",
            planned_start_offset_hours=0,
            planned_duration_hours=10,
            work_order_id=work_order["id"],
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )

        given_started_activity(activity["id"])
        assert read_work_order(work_order["id"])["status"] == WorkOrderStatus.EXECUTING

        validate_success(
            api_client.complete_activity(activity["id"], make_outage_planner_headers())
        )
        assert read_work_order(work_order["id"])["status"] == WorkOrderStatus.COMPLETE

        final_activity = read_activity(activity["id"])
        assert final_activity["started_at"] is not None
        assert final_activity["completed_at"] is not None
        assert read_outage(outage["id"])["approved_scope_cost_usd"] == pytest.approx(
            1000.00, abs=0.01
        )


class TestParallelDimensionsAndPostureOverride:
    def test_completing_the_predecessor_moves_only_the_constraint_dimension(self):
        """Starting A1 leaves A2 blocked, completing A1 clears A2 without touching
        its execution status, and the projection never moves because it consumes
        planned hours alone.

        PRD 3.4: "Its first cascade hop works the other state dimension: every
        activity whose `predecessor_activity_id` names the just-completed activity
        has its `constraint_status` recomputed to `CLEAR`, processed in ascending
        `created_at` order, and their `execution_status` values are left entirely
        alone."

        Design: Corner/state_machines/activity_constraint_dimension_moves_independently_of_execution_dimension
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        given_approved_work_order(
            outage["id"],
            title="Feedwater pump overhaul",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        first = given_schedule_activity(
            outage["id"],
            label="A1 cavity flood-up",
            planned_start_offset_hours=0,
            planned_duration_hours=100,
        )
        second = given_schedule_activity(
            outage["id"],
            label="A2 core offload",
            planned_start_offset_hours=100,
            planned_duration_hours=100,
            predecessor_activity_id=first["id"],
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )
        baseline = read_outage(outage["id"])
        assert baseline["projected_duration_hours"] == pytest.approx(200.00, abs=0.01)
        assert baseline["risk_adjusted_duration_hours"] == pytest.approx(220.00, abs=0.01)

        validate_error(
            api_client.start_activity(second["id"], make_outage_planner_headers()),
            ApiErrorId.PREDECESSOR_NOT_COMPLETE.value,
        )

        started = given_started_activity(first["id"])
        assert started["execution_status"] == ExecutionStatus.IN_PROGRESS
        mid = read_activity(second["id"])
        assert mid["constraint_status"] == ConstraintStatus.BLOCKED
        assert mid["execution_status"] == ExecutionStatus.NOT_STARTED

        validate_success(
            api_client.complete_activity(first["id"], make_outage_planner_headers())
        )
        cleared = read_activity(second["id"])
        assert cleared["constraint_status"] == ConstraintStatus.CLEAR
        assert cleared["execution_status"] == ExecutionStatus.NOT_STARTED

        now_started = given_started_activity(second["id"])
        assert now_started["execution_status"] == ExecutionStatus.IN_PROGRESS
        assert read_activity(second["id"])["constraint_status"] == ConstraintStatus.CLEAR

        after = read_outage(outage["id"])
        assert after["projected_duration_hours"] == pytest.approx(200.00, abs=0.01)
        assert after["risk_adjusted_duration_hours"] == pytest.approx(220.00, abs=0.01)

    def test_an_out_of_tolerance_measurement_succeeds_and_forces_the_posture(self):
        """A 200-pcm deviation is recorded on a 200 response rather than rejected,
        and the posture is driven to RECOVERY_REQUIRED even though the projection
        is 0.00 against a 720-hour target.

        PRD 3.9: "The request succeeds with HTTP 200, the measurement is recorded
        in `measured_reactivity_pcm` and `reactivity_deviation_pcm`,
        `satisfied_by_user_id` stays null, and the outage's `schedule_posture` is
        forced to `RECOVERY_REQUIRED` regardless of what
        `projected_duration_hours` says, remaining there until the next schedule
        reprojection runs."

        Design: Corner/state_machines/failed_startup_test_forces_recovery_required_posture
        """
        ctx = given_executing_outage(
            outage={"designation": "1R24", "duration_target_hours": 720},
            work_order={
                "title": "Feedwater pump overhaul",
                "estimated_hours": 10,
                "estimated_cost_usd": 1000,
                "estimated_dose_mrem": 0,
            },
        )
        test_row = given_startup_test(
            ctx["outage_id"],
            test_code="STP-01",
            sequence_index=1,
            hold_point_type=HoldPointType.STATION,
            predicted_reactivity_pcm=500,
        )
        validate_success(
            api_client.defer_work_order(
                ctx["work_order_id"],
                "Deferred to the next refueling window",
                make_outage_director_headers(),
            )
        )
        validate_success(
            api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers())
        )

        response = api_client.satisfy_startup_test(
            test_row["id"], 700, make_regulatory_affairs_headers("ra-beta")
        )
        failed = validate_success(response, 200)
        assert failed["status"] == StartupTestStatus.FAILED
        assert failed["measured_reactivity_pcm"] == pytest.approx(700, abs=0.01)
        assert failed["reactivity_deviation_pcm"] == pytest.approx(200.00, abs=0.01)
        assert read_startup_test(test_row["id"])["satisfied_by_user_id"] is None

        after = read_outage(ctx["outage_id"])
        assert after["projected_duration_hours"] == pytest.approx(0.00, abs=0.01)
        assert after["duration_target_hours"] == pytest.approx(720, abs=0.01)
        assert after["schedule_posture"] == SchedulePosture.RECOVERY_REQUIRED
        assert after["status"] == OutageStatus.STARTUP


class TestCoreLoadPatternSupersession:
    def test_creating_retires_a_draft_while_approving_retires_the_prior_approval(self):
        """A newer submission supersedes only the live DRAFT; an already APPROVED
        design survives a further submission untouched and is retired only when
        the newer design is itself approved.

        PRD 3.3: "Because only one draft design per outage is ever live, the
        submission also moves any existing pattern of the same outage that is still
        in `DRAFT` to `SUPERSEDED`, bumping that pattern's own `version` by 1 — a
        design under revision is superseded rather than deleted."

        Design: Corner/state_machines/core_load_pattern_supersession_differs_by_prior_status
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")

        first = given_core_load_pattern(outage["id"], discharge_assembly_count=76)
        second = given_core_load_pattern(outage["id"], discharge_assembly_count=80)
        assert read_pattern(first["id"])["status"] == CoreLoadPatternStatus.SUPERSEDED

        approved_second = validate_success(
            api_client.approve_core_load_pattern(
                second["id"], make_reactor_engineer_headers("re-beta")
            )
        )
        assert approved_second["status"] == CoreLoadPatternStatus.APPROVED
        assert approved_second["reactivity_margin_pcm"] == pytest.approx(1586.00, abs=0.01)
        assert approved_second["approved_by_user_id"] == "re-beta"

        third = given_core_load_pattern(outage["id"], discharge_assembly_count=84)
        assert read_pattern(second["id"])["status"] == CoreLoadPatternStatus.APPROVED

        validate_success(
            api_client.approve_core_load_pattern(
                third["id"], make_reactor_engineer_headers("re-beta")
            )
        )
        assert read_pattern(third["id"])["status"] == CoreLoadPatternStatus.APPROVED
        assert read_pattern(second["id"])["status"] == CoreLoadPatternStatus.SUPERSEDED

        rows, _meta = validate_paginated(
            api_client.list_core_load_patterns(
                outage["id"],
                make_reactor_engineer_headers(),
                status=CoreLoadPatternStatus.APPROVED,
            )
        )
        assert [row["id"] for row in rows] == [third["id"]]
