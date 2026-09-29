"""Depth coverage: revision cycles, fork-join onboarding and the two multi-hop
cascades."""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    Craft,
    DoseDirection,
    DoseReason,
    ExecutionStatus,
    Priority,
    REASON_SCHEDULE_POSTURE_AUTO_DEFERRAL,
    REASON_WORK_ORDER_DEFERRED,
    RwpStatus,
    SchedulePosture,
    StationUnit,
    WorkOrderOrigin,
    WorkOrderStatus,
    WorkOrderType,
    WorkerStatus,
    api_client,
    assert_dose_budget_consistent,
    assert_scope_rollup_consistent,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_draft_rwp,
    given_emergent_item,
    given_outage,
    given_planned_work_order,
    given_rad_area,
    given_schedule_activity,
    given_supplemental_worker,
    make_access_authority_headers,
    make_outage_director_headers,
    make_rad_protection_manager_headers,
    read_activity,
    read_outage,
    read_rwp,
    read_work_order,
    read_worker,
    set_clock,
    validate_error,
    validate_success,
)

FIRST_RETURN = "First vendor drawing revision B received"
SECOND_RETURN = "Second vendor drawing revision C received"


class TestWorkOrderRevisionCycle:
    def _approved_work_order(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="2R26", cost_budget_usd=40000000)
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.MODIFICATION,
            title="Reactor coolant pump seal replacement",
            estimated_hours=200,
            estimated_cost_usd=1200000,
            estimated_dose_mrem=0,
        )
        return outage, work_order

    def test_approved_planned_loop_can_be_walked_twice(self):
        """Two full laps of the revision loop leave the work order APPROVED
        again, holding the second return reason and a version bumped once per
        hop.

        PRD 3.2: "The move recomputes the scope cost roll-up and increments the
        outage's `version` by 1, and the `APPROVED → PLANNED → APPROVED` loop may
        be walked any number of times."

        Design: Difficulty/non_linear_state_machine/work_order_revision_cycle_traverses_approved_planned_twice
        """
        _outage, work_order = self._approved_work_order()
        assert work_order["status"] == WorkOrderStatus.APPROVED

        first_return = validate_success(
            api_client.return_work_order_to_planning(
                work_order["id"], FIRST_RETURN, make_outage_director_headers()
            )
        )
        assert first_return["status"] == WorkOrderStatus.PLANNED
        assert first_return["return_reason"] == FIRST_RETURN

        validate_success(
            api_client.approve_work_order_scope(
                work_order["id"], make_outage_director_headers()
            )
        )
        validate_success(
            api_client.return_work_order_to_planning(
                work_order["id"], SECOND_RETURN, make_outage_director_headers()
            )
        )
        final = validate_success(
            api_client.approve_work_order_scope(
                work_order["id"], make_outage_director_headers()
            )
        )
        assert final["status"] == WorkOrderStatus.APPROVED
        assert final["return_reason"] == SECOND_RETURN, (
            "the second return reason overwrites the first"
        )
        assert final["version"] == 7, (
            "create, plan, approve, return, approve, return, approve is seven "
            "mutations, and version starts at 1"
        )

    def test_scope_rollup_follows_the_work_order_out_of_and_back_into_the_base(self):
        """Returning the only approved work order to PLANNED empties the rollup
        base entirely; re-approving it restores the 8 percent tier.

        PRD 3.2: "First, `approved_scope_cost_usd` is the sum of
        `estimated_cost_usd` over the outage's work orders whose status is
        `APPROVED`, `EXECUTING` or `COMPLETE`, rounded half up to two decimal
        places; work orders in `SCOPED`, `PLANNED` or `DEFERRED` are excluded
        entirely."

        Design: Difficulty/non_linear_state_machine/work_order_revision_cycle_traverses_approved_planned_twice
        """
        outage, work_order = self._approved_work_order()
        assert read_outage(outage["id"])["approved_scope_cost_usd"] == pytest.approx(
            1200000.00, abs=0.01
        )

        validate_success(
            api_client.return_work_order_to_planning(
                work_order["id"], FIRST_RETURN, make_outage_director_headers()
            )
        )
        mid = read_outage(outage["id"])
        assert mid["approved_scope_cost_usd"] == pytest.approx(0.00, abs=0.01)
        assert mid["scope_contingency_usd"] == pytest.approx(0.00, abs=0.01)
        assert mid["total_scope_cost_usd"] == pytest.approx(0.00, abs=0.01)

        validate_success(
            api_client.approve_work_order_scope(
                work_order["id"], make_outage_director_headers()
            )
        )
        validate_success(
            api_client.return_work_order_to_planning(
                work_order["id"], SECOND_RETURN, make_outage_director_headers()
            )
        )
        validate_success(
            api_client.approve_work_order_scope(
                work_order["id"], make_outage_director_headers()
            )
        )
        final = read_outage(outage["id"])
        assert final["approved_scope_cost_usd"] == pytest.approx(1200000.00, abs=0.01)
        assert final["scope_contingency_usd"] == pytest.approx(96000.00, abs=0.01)
        assert final["total_scope_cost_usd"] == pytest.approx(1296000.00, abs=0.01)
        assert_scope_rollup_consistent(final)


class TestSupplementalWorkerForkJoin:
    def _requested_worker(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="2R26", required_training_modules=4)
        worker = given_supplemental_worker(
            outage["id"],
            full_name="R. Ostrander",
            craft=Craft.PIPEFITTER,
            sponsoring_contractor="Bartlett Nuclear",
        )
        return outage, worker

    def test_training_branch_alone_never_reaches_badge_ready(self):
        """Completing all four training modules moves the worker to SCREENING
        with training_status COMPLETE, but background_status is still PENDING, so
        the badge attempt is refused.

        PRD 3.5: "Neither branch alone reaches `BADGE_READY`; whichever branch
        lands second is the one that trips the join."

        Design: Difficulty/non_linear_state_machine/supplemental_worker_fork_join_needs_both_branches
        """
        _outage, worker = self._requested_worker()
        after_training = validate_success(
            api_client.record_training_completion(
                worker["id"], 4, make_access_authority_headers()
            )
        )
        assert after_training["status"] == WorkerStatus.SCREENING
        assert after_training["training_status"] == "COMPLETE"
        assert after_training["background_status"] == "PENDING"
        assert after_training["training_modules_completed"] == 4

        response = api_client.badge_worker(
            worker["id"], "B-1001", make_access_authority_headers()
        )
        validate_error(response, ApiErrorId.WORKER_STATE_INVALID.value)
        assert read_worker(worker["id"])["badge_number"] is None

    def test_second_branch_trips_the_join_and_the_badge_reprojects_the_count(self):
        """With training already COMPLETE, the CLEAR background result is the
        branch that lands second and moves the worker to BADGE_READY; badging
        then reprojects the outage's badged headcount.

        PRD 3.5: "The badge number is stored, the outage's `badged_worker_count`
        is reprojected as the count of the outage's workers in `BADGED`, and the
        outage's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/supplemental_worker_fork_join_needs_both_branches
        """
        outage, worker = self._requested_worker()
        validate_success(
            api_client.record_training_completion(
                worker["id"], 4, make_access_authority_headers()
            )
        )
        joined = validate_success(
            api_client.record_background_result(
                worker["id"], "CLEAR", make_access_authority_headers()
            )
        )
        assert joined["status"] == WorkerStatus.BADGE_READY
        assert joined["background_status"] == "CLEAR"

        badged = validate_success(
            api_client.badge_worker(worker["id"], "B-1001", make_access_authority_headers())
        )
        assert badged["status"] == WorkerStatus.BADGED
        assert badged["badge_number"] == "B-1001"
        assert read_outage(outage["id"])["badged_worker_count"] == 1


def _scope_locked_outage_with_discretionary_scope():
    """WO1 is CRITICAL and APPROVED; WO3 is DISCRETIONARY and left in PLANNED
    with one activity and one DRAFT permit hanging off it."""
    set_clock(CLOCK_EPOCH)
    rad_area = given_rad_area(
        station_unit=StationUnit.UNIT_1,
        area_code="RA-3",
        dose_rate_mrem_per_hr=25,
        occupancy_limit_workers=10,
        survey_buffer_hours=2,
    )
    outage = given_outage(
        station_unit=StationUnit.UNIT_1,
        designation="2R26",
        duration_target_hours=720,
        dose_budget_total_mrem=1000,
        cost_budget_usd=40000000,
        required_badged_workers=0,
    )
    given_approved_core_load_pattern(outage["id"])
    wo1 = given_approved_work_order(
        outage["id"],
        wo_type=WorkOrderType.MODIFICATION,
        title="Reactor coolant pump seal replacement",
        estimated_hours=300,
        estimated_cost_usd=900000,
        estimated_dose_mrem=300,
        regulatory_commitment=True,
        requires_rad_work=True,
    )
    wo3 = given_planned_work_order(
        outage["id"],
        wo_type=WorkOrderType.MAINTENANCE,
        title="Turbine building lighting refurbishment",
        estimated_hours=150,
        estimated_cost_usd=250000,
        estimated_dose_mrem=600,
        requires_rad_work=True,
    )
    a1 = given_schedule_activity(
        outage["id"],
        label="Cooldown and depressurize",
        planned_start_offset_hours=0,
        planned_duration_hours=200,
    )
    a2 = given_schedule_activity(
        outage["id"],
        label="RCP seal replacement",
        planned_start_offset_hours=200,
        planned_duration_hours=300,
        work_order_id=wo1["id"],
        predecessor_activity_id=a1["id"],
    )
    a3 = given_schedule_activity(
        outage["id"],
        label="Lighting refurbishment",
        planned_start_offset_hours=500,
        planned_duration_hours=150,
        work_order_id=wo3["id"],
        predecessor_activity_id=a2["id"],
    )
    rwp3 = given_draft_rwp(
        wo3["id"],
        rad_area["id"],
        worker_count=2,
        shielding_factor=0.5,
        planned_start_offset_hours=500,
        planned_duration_hours=6,
    )
    validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
    item = given_emergent_item(
        wo3["id"],
        description="Cracked conduit hanger behind panel 4B",
        estimated_hours=90,
        estimated_cost_usd=400000,
        estimated_dose_mrem=150,
    )
    return {
        "outage_id": outage["id"],
        "wo1_id": wo1["id"],
        "wo3_id": wo3["id"],
        "a1_id": a1["id"],
        "a2_id": a2["id"],
        "a3_id": a3["id"],
        "rwp3_id": rwp3["id"],
        "item_id": item["id"],
    }


def _dispose_approved(item_id):
    return validate_success(
        api_client.dispose_emergent_item(
            item_id,
            "APPROVED",
            make_outage_director_headers(),
            disposition_note="Repair before restoring lighting scope",
        )
    )


class TestEmergentApprovalCascade:
    def test_minted_work_order_and_activity_follow_the_discovering_work_order(self):
        """The cascade mints an already-APPROVED MAINTENANCE work order scored by
        the ordinary rule, plus one activity chained behind the latest-finishing
        activity of the discovering work order.

        PRD 3.8: "**Step 3** mints a schedule activity for that new work order:
        its `label` is the literal prefix `EMERGENT: ` followed by the item's
        `description`, its `planned_duration_hours` is the item's
        `estimated_hours`, its `predecessor_activity_id` is the activity the
        terminal-activity selector returns over the *discovering* work order, and
        its `planned_start_offset_hours` is that predecessor's
        `planned_start_offset_hours` plus the new activity's own
        `planned_duration_hours`."

        Design: Difficulty/transitive_cascade/emergent_approval_cascade_defers_discretionary_and_voids_permit
        """
        ctx = _scope_locked_outage_with_discretionary_scope()
        before = read_outage(ctx["outage_id"])
        assert before["schedule_posture"] == SchedulePosture.ON_TRACK
        assert before["projected_duration_hours"] == pytest.approx(650.00, abs=0.01)

        disposed = _dispose_approved(ctx["item_id"])
        minted_id = disposed["created_work_order_id"]
        assert minted_id is not None

        minted = read_work_order(minted_id)
        assert minted["origin"] == WorkOrderOrigin.EMERGENT
        assert minted["status"] == WorkOrderStatus.APPROVED
        assert minted["wo_type"] == WorkOrderType.MAINTENANCE
        assert minted["estimated_hours"] == pytest.approx(90, abs=0.01)
        assert minted["priority_score"] == pytest.approx(49.00, abs=0.01)
        assert minted["priority"] == Priority.HIGH

        activities = validate_success(
            api_client.list_schedule_activities(
                make_outage_director_headers(), work_order_id=minted_id
            )
        )
        assert len(activities) == 1, "the cascade mints exactly one activity"
        minted_activity = activities[0]
        # PRD 3.8 step 3: the offset is the *predecessor's*
        # planned_start_offset_hours (a3 starts at 500) plus the new activity's
        # own planned_duration_hours (90) — 590.00, not the predecessor's finish.
        assert minted_activity["planned_start_offset_hours"] == pytest.approx(590, abs=0.01)
        assert minted_activity["planned_duration_hours"] == pytest.approx(90, abs=0.01)
        assert minted_activity["predecessor_activity_id"] == ctx["a3_id"]

    def test_posture_slip_auto_defers_discretionary_scope_and_voids_its_draft_permit(self):
        """The projection reaches 740.00 against a 792.00 AT_RISK ceiling, and
        that slip out of ON_TRACK auto-defers the DISCRETIONARY work order,
        cancelling its activity and voiding its permit without any ledger row.

        PRD 3.8: "**Step 6** is the posture auto-deferral: if `schedule_posture`
        was `ON_TRACK` before this request and is `AT_RISK` or
        `RECOVERY_REQUIRED` after step 5, then every work order of the outage
        whose `priority` is `DISCRETIONARY` and whose status is `SCOPED` or
        `PLANNED` moves to `DEFERRED` with `deferral_reason` set to the literal
        `SCHEDULE_POSTURE_AUTO_DEFERRAL`, processed in ascending work-order
        `created_at` order."

        Design: Difficulty/transitive_cascade/emergent_approval_cascade_defers_discretionary_and_voids_permit
        """
        ctx = _scope_locked_outage_with_discretionary_scope()
        _dispose_approved(ctx["item_id"])

        outage = read_outage(ctx["outage_id"])
        assert outage["schedule_posture"] == SchedulePosture.AT_RISK

        deferred = read_work_order(ctx["wo3_id"])
        assert deferred["status"] == WorkOrderStatus.DEFERRED
        assert deferred["deferral_reason"] == REASON_SCHEDULE_POSTURE_AUTO_DEFERRAL

        assert read_activity(ctx["a3_id"])["execution_status"] == ExecutionStatus.CANCELLED

        permit = read_rwp(ctx["rwp3_id"])
        assert permit["status"] == RwpStatus.VOIDED
        assert permit["void_reason"] == REASON_WORK_ORDER_DEFERRED

        rows = validate_success(
            api_client.list_dose_transactions(
                ctx["rwp3_id"], make_rad_protection_manager_headers()
            )
        )
        assert rows == [], "voiding a permit that never left DRAFT appends no ledger row"
        assert outage["dose_committed_mrem"] == pytest.approx(0.00, abs=0.01)
        assert outage["dose_budget_remaining_mrem"] == pytest.approx(1000.00, abs=0.01)

    def test_step_eight_reprojection_does_not_re_evaluate_the_posture(self):
        """The final reprojection drops the projection back to 500.00 --- below
        the 720-hour target --- yet the posture keeps the AT_RISK value fixed at
        step 5.

        PRD 3.8: "Crucially, `schedule_posture` is **not** re-evaluated after step
        7 — the value fixed in step 5 is the value this request returns, even
        though step 7 has meanwhile removed scope that would have shortened the
        projection."

        Design: Difficulty/transitive_cascade/emergent_approval_cascade_defers_discretionary_and_voids_permit
        """
        ctx = _scope_locked_outage_with_discretionary_scope()
        _dispose_approved(ctx["item_id"])

        outage = read_outage(ctx["outage_id"])
        assert outage["projected_duration_hours"] == pytest.approx(500.00, abs=0.01)
        assert outage["risk_adjusted_duration_hours"] == pytest.approx(595.00, abs=0.01)
        assert outage["critical_path_activity_id"] == ctx["a2_id"]
        assert outage["schedule_posture"] == SchedulePosture.AT_RISK, (
            "500.00 is inside the 720-hour target, so only the step-5 freeze "
            "explains an AT_RISK posture"
        )
        assert outage["approved_emergent_hours"] == pytest.approx(90.00, abs=0.01)
        assert outage["approved_scope_cost_usd"] == pytest.approx(1300000.00, abs=0.01)
        assert outage["scope_contingency_usd"] == pytest.approx(104000.00, abs=0.01)
        assert outage["total_scope_cost_usd"] == pytest.approx(1404000.00, abs=0.01)
        assert_scope_rollup_consistent(outage)


def _scope_locked_outage_with_three_draft_permits():
    """One approved inspection work order carrying three drafted permits worth
    750.00, 432.00 and 180.00 mrem against a 1000-mrem budget."""
    set_clock(CLOCK_EPOCH)
    rad_area = given_rad_area(
        station_unit=StationUnit.UNIT_1,
        area_code="RA-4",
        dose_rate_mrem_per_hr=25,
        occupancy_limit_workers=10,
        survey_buffer_hours=2,
    )
    outage = given_outage(
        station_unit=StationUnit.UNIT_1,
        designation="2R26",
        duration_target_hours=720,
        dose_budget_total_mrem=1000,
        cost_budget_usd=40000000,
    )
    given_approved_core_load_pattern(outage["id"])
    work_order = given_approved_work_order(
        outage["id"],
        wo_type=WorkOrderType.INSPECTION,
        title="Reactor cavity inspection campaign",
        estimated_hours=200,
        estimated_cost_usd=500000,
        estimated_dose_mrem=400,
        regulatory_commitment=True,
        requires_rad_work=True,
    )
    rwp_a = given_draft_rwp(
        work_order["id"],
        rad_area["id"],
        worker_count=5,
        shielding_factor=0,
        planned_start_offset_hours=0,
        planned_duration_hours=5,
    )
    rwp_b = given_draft_rwp(
        work_order["id"],
        rad_area["id"],
        worker_count=3,
        shielding_factor=0.2,
        planned_start_offset_hours=20,
        planned_duration_hours=6,
    )
    rwp_c = given_draft_rwp(
        work_order["id"],
        rad_area["id"],
        worker_count=2,
        shielding_factor=0.5,
        planned_start_offset_hours=40,
        planned_duration_hours=6,
    )
    validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
    return {
        "outage_id": outage["id"],
        "work_order_id": work_order["id"],
        "rwp_a_id": rwp_a["id"],
        "rwp_b_id": rwp_b["id"],
        "rwp_c_id": rwp_c["id"],
    }


class TestRwpApprovalHoldCascade:
    def test_approval_commits_one_ledger_row_and_moves_the_posture(self):
        """Approving the 750.00-mrem permit writes a single COMMIT row, leaves
        250.00 of a 1000-mrem budget and takes the posture to RESTRICTED.

        PRD 3.7: "Hop one appends a dose ledger row whose `rwp_id` is the permit,
        whose `direction` is `COMMIT`, whose `amount_mrem` is the permit's
        `committed_dose_mrem` and whose `reason` is `RWP_APPROVED`."

        Design: Difficulty/transitive_cascade/rwp_approval_cascade_holds_other_drafts_for_alara
        """
        ctx = _scope_locked_outage_with_three_draft_permits()
        approved = validate_success(
            api_client.approve_rwp(
                ctx["rwp_a_id"],
                make_rad_protection_manager_headers(),
                alara_review_reference="ALARA-2R26-007",
            )
        )
        assert approved["status"] == RwpStatus.APPROVED
        assert approved["committed_dose_mrem"] == pytest.approx(750.00, abs=0.01)

        rows = validate_success(
            api_client.list_dose_transactions(
                ctx["rwp_a_id"], make_rad_protection_manager_headers()
            )
        )
        assert len(rows) == 1
        assert rows[0]["direction"] == DoseDirection.COMMIT
        assert rows[0]["amount_mrem"] == pytest.approx(750.00, abs=0.01)
        assert rows[0]["reason"] == DoseReason.RWP_APPROVED

        outage = read_outage(ctx["outage_id"])
        assert outage["dose_committed_mrem"] == pytest.approx(750.00, abs=0.01)
        assert outage["dose_budget_remaining_mrem"] == pytest.approx(250.00, abs=0.01)
        assert outage["alara_posture"] == "RESTRICTED"
        assert_dose_budget_consistent(outage)

    def test_hold_cascade_reaches_only_drafts_above_two_hundred_mrem(self):
        """The 432.00-mrem draft is parked in HELD_FOR_ALARA while the
        180.00-mrem draft is left alone, and neither has any ledger row.

        PRD 3.7: "Draft permits at or below that 200-mrem threshold are left in
        `DRAFT`."

        Design: Difficulty/transitive_cascade/rwp_approval_cascade_holds_other_drafts_for_alara
        """
        ctx = _scope_locked_outage_with_three_draft_permits()
        validate_success(
            api_client.approve_rwp(
                ctx["rwp_a_id"],
                make_rad_protection_manager_headers(),
                alara_review_reference="ALARA-2R26-007",
            )
        )
        held = read_rwp(ctx["rwp_b_id"])
        untouched = read_rwp(ctx["rwp_c_id"])
        assert held["committed_dose_mrem"] == pytest.approx(432.00, abs=0.01)
        assert untouched["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)
        assert held["status"] == RwpStatus.HELD_FOR_ALARA
        assert untouched["status"] == RwpStatus.DRAFT

        rows = validate_success(
            api_client.list_dose_transactions(
                ctx["rwp_b_id"], make_rad_protection_manager_headers()
            )
        )
        assert rows == [], "being held for ALARA review commits nothing"
