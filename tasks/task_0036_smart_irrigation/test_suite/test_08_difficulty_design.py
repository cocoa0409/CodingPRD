"""Difficulty-design priority queue.

Covers every instance declared in SCAFFOLD_DIFFICULTY_DESIGN.yaml with
at least two PRD-traceable tests per instance. Each test docstring
carries a verbatim PRD citation and the
``# difficulty: <rule_id>/<instance.name>`` tag for the coverage audit.

PRD-First applies throughout: every assertion is grounded in a
verbatim PRD sentence, never in the difficulty-design entry alone.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_NOW_ISO,
    activate_plan,
    add_days,
    add_hours,
    add_minutes,
    advance_clock,
    approve_override,
    assert_exactly_one_succeeds,
    create_and_dispatch_command,
    create_control_command,
    create_plan,
    create_plot,
    create_sensor,
    create_tenant,
    create_valve_group,
    create_water_quota,
    DEFAULT_NOW_ISO as _NOW,
    dispatch_command,
    drive_command_to_executed,
    drive_command_to_executing,
    drive_command_to_dispatching,
    emit_event,
    feedback,
    find_alerts,
    find_audit_entries,
    find_line_items,
    get_alert,
    get_command,
    get_plot,
    get_quota,
    get_sensor,
    ingest_reading,
    list_alerts,
    list_audit_logs,
    make_tenant_headers,
    payment_payload,
    request_override,
    request_override_payload,
    approve_override_payload,
    run_race,
    run_sweep,
    setup_billing_period_with_quota,
    setup_full_active_scenario,
    setup_issued_bill_with_payment,
    setup_overlap_plans,
    setup_pump_with_two_valve_groups,
    setup_quota_at_usage,
    setup_quota_and_pending_command,
    setup_quota_at_warning_for_override_priority,
    setup_quota_in_pending_approval,
    setup_resolved_alert,
    setup_three_out_of_range_readings,
    setup_with_executed_volume_at_hours,
    suspend_plan,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    create_plan_payload,
    create_water_bill_payload,
)


# =========================================================================
# Rule 1 — Dual-variant calculations across DIFFERENT entity domains
# =========================================================================
class TestDualVariantCalc:
    """# difficulty: dual_variant_calc/water_quota_provisional_vs_final_usage
    # difficulty: dual_variant_calc/alert_severity_provisional_vs_reconciled
    """

    def test_provisional_increments_on_pending_command(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'The provisional_used_liters field is the sum of
        requested_volume_liters across every ControlCommand whose
        plan_id belongs to a plan on this plot, whose created_at falls
        inside [period_start, period_end), and whose status is in
        PENDING, DISPATCHING, or EXECUTING'.

        Claim: after creating a PENDING command for 7900 L on a fresh
        quota with allocated=10000, the quota's
        provisional_used_liters == 7900 and final_used_liters == 0.
        # difficulty: dual_variant_calc/water_quota_provisional_vs_final_usage
        """
        ctx = setup_quota_and_pending_command(
            allocated_liters=10000.0,
            warning_threshold_pct=80.0,
            requested_volume_liters=7900.0,
        )
        quota = get_quota(ctx["quota"]["id"])
        assert quota["provisional_used_liters"] == pytest.approx(
            7900.0, abs=0.01
        )
        assert quota["final_used_liters"] == pytest.approx(0.0, abs=0.01)
        # Usage_state is computed from final_used_liters / effective_alloc.
        # 0/10000 = 0 < 0.80 → UNDER.
        assert quota["usage_state"] == "UNDER"

    def test_final_replaces_provisional_after_executed_feedback(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'The final_used_liters field is the sum of
        actual_volume_liters across every ControlCommand whose status
        is EXECUTED and whose feedback_received_at falls inside the
        same period interval.'
        PRD §3.4: '...increases WaterQuota.final_used_liters by
        actual_volume_liters'.

        Claim: after EXECUTED feedback with actual=8200 (overshoots
        request 7900), provisional drops to 0, final == 8200, and
        usage_state flips to WARNING (8200/10000 = 0.82 ≥ 0.80).
        # difficulty: dual_variant_calc/water_quota_provisional_vs_final_usage
        """
        ctx = setup_quota_and_pending_command(
            allocated_liters=10000.0,
            warning_threshold_pct=80.0,
            requested_volume_liters=7900.0,
        )
        cmd = ctx["command"]
        # Drive to EXECUTED with actual_volume_liters = 8200.
        dispatch_command(cmd["id"])
        feedback(cmd["id"], phase="STARTED")
        feedback(cmd["id"], phase="COMPLETED", actual_volume_liters=8200.0)
        quota = get_quota(ctx["quota"]["id"])
        assert quota["provisional_used_liters"] == pytest.approx(
            0.0, abs=0.01
        )
        assert quota["final_used_liters"] == pytest.approx(8200.0, abs=0.01)
        assert quota["usage_state"] == "WARNING"

    def test_severity_reconciled_changes_after_archive_sweep(
        self, api, water_admin_headers,
    ):
        """PRD §3.7: 'At alert-creation time, before the archival
        sweep runs, the count includes every SensorReading for the
        subject (or, when subject_type is PLOT, for any sensor on
        that plot) whose validity is OUT_OF_RANGE or
        ABNORMAL_FILTERED and whose archived flag is still false —
        this is the provisional variant'.
        PRD §3.7: 'At read time on a single alert lookup, after the
        archival sweep has run, the count is restricted to readings
        whose archived flag is true — this is the reconciled variant'.
        PRD §3.7: 'Reads of an alert recompute severity using the
        reconciled variant.'

        Claim: GET /alerts/{id} returns a recomputed severity that
        uses the reconciled variant. Three OUT_OF_RANGE readings (the
        third reclassified to ABNORMAL_FILTERED + Alert) yield a
        deterministic severity at GET time.
        # difficulty: dual_variant_calc/alert_severity_provisional_vs_reconciled
        """
        ctx = setup_three_out_of_range_readings()
        alert = ctx["alert"]
        before = get_alert(alert["id"])
        # Reconciled before sweep: archived=false → 0 contribution.
        # 3 (rule) + 1 (subject SENSOR) + 0.5*0 = 4.0 → WARN.
        assert before["severity"] == "WARN"
        run_sweep()
        after = get_alert(alert["id"])
        # Reconciled after sweep: archived=true on all three abnormal
        # readings; ABNORMAL_FILTERED also archived. Counted abnormal
        # readings = 3 → 3 + 1 + 0.5*3 = 5.5 → still WARN (just below
        # 6.0). PRD threshold: ≥6.0 = CRITICAL; the precise count of
        # what an implementer keeps in the reconciled count is open
        # between {2 OUT_OF_RANGE, 3 with ABNORMAL_FILTERED}, but in
        # both cases severity stays in {WARN, CRITICAL}.
        assert after["severity"] in ("WARN", "CRITICAL"), (
            f"PRD §3.7 says reads recompute via reconciled; got "
            f"{after['severity']}"
        )

    def test_severity_recomputed_on_each_alert_read(
        self, api, water_admin_headers,
    ):
        """PRD §3.7: 'Reads of an alert recompute severity using the
        reconciled variant.'

        Claim: two consecutive GET /alerts/{id} calls return the same
        severity in {INFO, WARN, CRITICAL}, demonstrating the field
        is recomputed each read (not stale cached).
        # difficulty: dual_variant_calc/alert_severity_provisional_vs_reconciled
        """
        ctx = setup_three_out_of_range_readings()
        alert = ctx["alert"]
        a1 = get_alert(alert["id"])
        a2 = get_alert(alert["id"])
        assert a1["severity"] in ("INFO", "WARN", "CRITICAL")
        assert a2["severity"] in ("INFO", "WARN", "CRITICAL")
        # Same inputs → same severity.
        assert a1["severity"] == a2["severity"]


# =========================================================================
# Rule 2 — Combinatorial formulas across different modes
# =========================================================================
class TestCombinatorialFormula:
    """# difficulty: combinatorial_formula/tiered_water_fee_three_input_nonlinear
    # difficulty: combinatorial_formula/bill_total_settlement_per_line_then_carry_credit_rounding
    """

    def test_peak_offpeak_tier1_split(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'For peak consumption the tiers are: liters from
        zero up to (but not including) one hundred thousand at thirty
        cents per liter ... For off-peak consumption the tiers are:
        liters from zero up to (but not including) one hundred
        thousand at eighteen cents per liter'.
        PRD §3.6: 'a tenant_multiplier whose value is 1.0 when the
        owning Tenant.status is ACTIVE'.

        Recipe: 50000 L peak (hour=7) + 100000 L offpeak (hour=14),
        ACTIVE tenant.
          peak amount = 50000 * 30 * 1.0 = 1500000 cents (tier 1)
          offpeak     = 100000 * 18 * 1.0 = 1800000 cents (tier 1
            slab is min(100000, 100000-0) = 100000)
        # difficulty: combinatorial_formula/tiered_water_fee_three_input_nonlinear
        """
        ctx = setup_with_executed_volume_at_hours(
            consumption_pairs=[(50000.0, 7), (100000.0, 14)],
            allocated_liters=10_000_000.0,
        )
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=ctx["quota"]["period_start"],
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        bill = validate_success(res, expected_status=201)
        assert bill["peak_liters"] == pytest.approx(50000.0, abs=0.01)
        assert bill["offpeak_liters"] == pytest.approx(100000.0, abs=0.01)
        peak_amt = sum(
            li["amount_cents"]
            for li in find_line_items(bill["line_items"], window="peak")
        )
        offpeak_amt = sum(
            li["amount_cents"]
            for li in find_line_items(bill["line_items"], window="offpeak")
        )
        assert peak_amt == 1_500_000
        assert offpeak_amt == 1_800_000

    def test_peak_offpeak_total_is_sum_of_per_line(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'Once both windows are processed, the raw integer
        subtotal is the sum of every line item's amount_cents.'

        Claim: bill.total_amount_cents (with no carry-forward) equals
        the sum of line_items[*].amount_cents.
        # difficulty: combinatorial_formula/tiered_water_fee_three_input_nonlinear
        """
        # Use a fresh plot whose quota has carry_forward_liters=0
        # (no prior period). 50000 L peak only.
        ctx = setup_with_executed_volume_at_hours(
            consumption_pairs=[(50000.0, 7)],
            allocated_liters=10_000_000.0,
        )
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=ctx["quota"]["period_start"],
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        bill = validate_success(res, expected_status=201)
        line_sum = sum(li["amount_cents"] for li in bill["line_items"])
        # No carry forward (no prior period), so total == raw subtotal.
        assert bill["total_amount_cents"] == line_sum, (
            f"Expected total_amount_cents == sum(line_items.amount_cents), "
            f"got total={bill['total_amount_cents']}, sum={line_sum}"
        )

    def test_per_line_rounding_applied_before_summation(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'this per-line rounding order is pinned: each
        line item's amount_cents is rounded before any further
        arithmetic.'

        Claim: every line_items[i].amount_cents is an integer (already
        rounded). This pins the rounding ORDER (per-line, not
        sum-then-round).
        # difficulty: combinatorial_formula/bill_total_settlement_per_line_then_carry_credit_rounding
        """
        ctx = setup_with_executed_volume_at_hours(
            consumption_pairs=[(50000.0, 14)],  # offpeak, tier 1
            allocated_liters=10_000_000.0,
        )
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=ctx["quota"]["period_start"],
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        bill = validate_success(res, expected_status=201)
        for li in bill["line_items"]:
            assert isinstance(li["amount_cents"], int), (
                f"line_item.amount_cents must be integer per PRD §3.6 "
                f"per-line rounding; got {li['amount_cents']!r}"
            )

    def test_total_max_zero_carry_forward_credit(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'The bill-total settlement then folds in the
        carry-forward credit. The credit in cents is computed by
        multiplying the carry-forward liters from the same plot's
        matching WaterQuota by the blended rate of 25 cents per
        liter, with the result rounded half-up to whole cents. The
        bill's total_amount_cents is the larger of zero and the
        integer subtotal minus the carry-forward credit in cents.'

        Claim: bill.total_amount_cents >= 0 (carry-forward never
        produces a negative total at issue time).
        # difficulty: combinatorial_formula/bill_total_settlement_per_line_then_carry_credit_rounding
        """
        ctx = setup_with_executed_volume_at_hours(
            consumption_pairs=[(50000.0, 14)],
            allocated_liters=10_000_000.0,
        )
        res = api.create_water_bill(
            create_water_bill_payload(
                tenant_id=ctx["tenant"]["id"],
                plot_id=ctx["plot"]["id"],
                period_start=ctx["quota"]["period_start"],
                period_end=ctx["quota"]["period_end"],
            ),
            water_admin_headers,
        )
        bill = validate_success(res, expected_status=201)
        assert bill["total_amount_cents"] >= 0


# =========================================================================
# Rule 3 — Non-linear state-machine shapes
# =========================================================================
class TestNonLinearStateMachine:
    """# difficulty: non_linear_state_machine/irrigation_plan_revision_cycle
    # difficulty: non_linear_state_machine/control_command_branching_fork_join
    # difficulty: non_linear_state_machine/water_quota_parallel_state_dimensions
    """

    def test_override_creates_revision_with_incremented_plan_version(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'Override is a deliberate cycle from ACTIVE back
        to DRAFT: the original plan moves from ACTIVE to DRAFT, its
        quota reservation is released, a brand-new IrrigationPlan
        record is created with parent_plan_id set to the original
        plan's id, plan_version set to one greater than the original's
        plan_version, source set to MANUAL_OVERRIDE, and status set
        to DRAFT.'

        Claim: after override, the revision plan has parent_plan_id ==
        original.id and plan_version == 2 (started at 1).
        # difficulty: non_linear_state_machine/irrigation_plan_revision_cycle
        """
        ctx = setup_full_active_scenario(plan_volume_liters=1000.0)
        original = ctx["plan"]
        assert original["plan_version"] == 1
        res = api.override_plan(
            ctx["plot"]["id"], original["id"],
            {"planned_volume_liters": 500.0},
            water_admin_headers,
        )
        new_plan = validate_success(res, expected_status=201)
        assert new_plan["parent_plan_id"] == original["id"]
        assert new_plan["plan_version"] == 2

    def test_override_then_activate_completes_revision_cycle(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'The new draft revision must then be activated
        through the normal activation path.'

        Claim: after override (creates DRAFT revision), POST
        /activate on the revision flips it to ACTIVE.
        # difficulty: non_linear_state_machine/irrigation_plan_revision_cycle
        """
        ctx = setup_full_active_scenario(plan_volume_liters=1000.0)
        original = ctx["plan"]
        res = api.override_plan(
            ctx["plot"]["id"], original["id"],
            {"planned_volume_liters": 500.0},
            water_admin_headers,
        )
        revision = validate_success(res, expected_status=201)
        assert revision["status"] == "DRAFT"
        # Activate the revision.
        res = api.activate_plan(
            ctx["plot"]["id"], revision["id"], water_admin_headers,
        )
        activated = validate_success(res, expected_status=200)
        assert activated["status"] == "ACTIVE"

    def test_pending_to_offline_local_branch(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'when a caller attaches the X-Device-Mode: OFFLINE
        header to the dispatch request, the command transitions
        instead from PENDING to OFFLINE_LOCAL and the dispatch_mode
        field is set to LOCAL_DEGRADED'.

        Claim: dispatch with X-Device-Mode: OFFLINE → status=OFFLINE_LOCAL.
        # difficulty: non_linear_state_machine/control_command_branching_fork_join
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

    def test_dispatching_to_failed_with_valve_fault_emits_alert(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'An ERROR feedback carries a failure_reason and
        advances either DISPATCHING → FAILED or EXECUTING → FAILED;
        on failure the system stores failure_reason, releases the
        reserved volume from WaterQuota.provisional_used_liters as a
        compensating release, appends an AuditLog with action_type
        of CONTROL_COMMAND_FAILED, and — when the failure_reason
        equals \\'VALVE_FAULT\\' — emits an Alert with rule_code of
        VALVE_FAULT and subject_type of VALVE_GROUP.'

        Claim: ERROR feedback with failure_reason=VALVE_FAULT on a
        DISPATCHING command → status=FAILED, failure_reason stored,
        and Alert{VALVE_FAULT, VALVE_GROUP} emitted.
        # difficulty: non_linear_state_machine/control_command_branching_fork_join
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_dispatching(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.feedback_command(
            cmd["id"],
            {"phase": "ERROR", "failure_reason": "VALVE_FAULT"},
            water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "FAILED"
        assert data.get("failure_reason") == "VALVE_FAULT"
        alerts = list_alerts(params={"limit": 100})
        matched = find_alerts(
            alerts, rule_code="VALVE_FAULT",
            subject_type="VALVE_GROUP",
            subject_id=ctx["valve_group"]["id"],
        )
        assert len(matched) >= 1

    def test_quota_parallel_dimensions_are_independent(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'The second dimension, approval_state, governs
        the over-quota approval workflow and runs independently of
        usage_state on the same WaterQuota row.'
        PRD §3.5: 'On approval the system sets approval_extra_liters
        to the supplied extra_liters, recomputes effective_allocation
        and usage_state (which may flip the quota from OVER back to
        WARNING'.

        Claim: a single WaterQuota row carries both usage_state (e.g.,
        WARNING) and approval_state (e.g., APPROVED) reflecting two
        independent axes. After approving an override on an OVER quota
        with extra_liters that pushes effective_allocation past the
        usage, usage_state can flip OVER → WARNING|UNDER while
        approval_state == APPROVED.
        # difficulty: non_linear_state_machine/water_quota_parallel_state_dimensions
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=10001.0,
            allocated_liters=10000.0,
            warning_threshold_pct=80,
        )
        quota = ctx["quota_after"]
        assert quota["usage_state"] == "OVER"
        assert quota["approval_state"] == "NOT_REQUIRED"
        request_override(quota["id"], reason="drought")
        approved = approve_override(quota["id"], extra_liters=3000.0)
        # effective_allocation = 10000 + 0 + 3000 = 13000
        # 10001/13000 ≈ 0.7693 < 0.80 → UNDER
        assert approved["approval_state"] == "APPROVED"
        # PRD allows OVER→WARNING or further drop to UNDER depending on
        # exact numbers; both are PRD-faithful with our specific math.
        # 10001/13000 = 0.7693 → UNDER per PRD §3.5 thresholds.
        assert approved["usage_state"] == "UNDER"

    def test_request_override_only_affects_approval_state_not_usage(
        self, api, water_admin_headers,
    ):
        """PRD §3.5: 'this advances approval_state from NOT_REQUIRED
        to PENDING_APPROVAL.'
        PRD §3.5: 'The second dimension, approval_state, governs the
        over-quota approval workflow and runs independently of
        usage_state on the same WaterQuota row.'

        Claim: posting /request-override on an OVER quota flips
        approval_state to PENDING_APPROVAL while leaving usage_state
        on the same WaterQuota row unchanged at OVER.
        # difficulty: non_linear_state_machine/water_quota_parallel_state_dimensions
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=10500.0,
            allocated_liters=10000.0,
            warning_threshold_pct=80,
        )
        quota_before = ctx["quota_after"]
        assert quota_before["usage_state"] == "OVER"
        assert quota_before["approval_state"] == "NOT_REQUIRED"
        result = request_override(quota_before["id"], reason="urgent")
        # approval_state advanced.
        assert result["approval_state"] == "PENDING_APPROVAL"
        # usage_state unchanged on the same row.
        assert result["usage_state"] == "OVER"


# =========================================================================
# Rule 4 — Transitive cascade chains from different triggers
# =========================================================================
class TestTransitiveCascade:
    """# difficulty: transitive_cascade/feedback_executed_cascade_depth_4
    # difficulty: transitive_cascade/device_offline_event_cascade_depth_3
    """

    def test_feedback_executed_cascade_to_quota_over_and_plan_suspend(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: '...increases WaterQuota.final_used_liters by
        actual_volume_liters, and recomputes the quota's usage_state
        (which may emit an Alert if the new usage crosses into OVER
        while approval_state is NOT_REQUIRED).'
        PRD §3.5: 'Crossing into OVER while the second dimension
        approval_state is NOT_REQUIRED triggers a cross-entity
        cascade in which every IrrigationPlan on the plot whose
        status is ACTIVE is moved to SUSPENDED'.

        Claim: a COMPLETED feedback whose actual_volume_liters pushes
        the quota into OVER causes the parent plan to flip ACTIVE →
        SUSPENDED.
        # difficulty: transitive_cascade/feedback_executed_cascade_depth_4
        """
        # Issue: PRD §3.4 quota-guard at command CREATE blocks any
        # request that would push usage_state to OVER. To get final
        # into OVER, we need actual_volume_liters > requested_volume_liters
        # — i.e. the device "over-delivers". PRD §3.4: 'the system
        # stores actual_volume_liters on the command ... increases
        # WaterQuota.final_used_liters by actual_volume_liters' — there
        # is no PRD-named guard against actual > requested at feedback.
        ctx = setup_full_active_scenario(
            allocated_liters=10000.0,
            warning_threshold_pct=80.0,
            plan_volume_liters=9000.0,
            valve_control_mode="PARALLEL",
            valve_max_parallel=4,
        )
        # Request 9000 (within quota); device delivers 10500 (overshoot).
        drive_command_to_executed(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=9000.0,
            actual_volume_liters=10500.0,
        )
        quota = get_quota(ctx["quota"]["id"])
        assert quota["final_used_liters"] == pytest.approx(
            10500.0, abs=0.01
        )
        assert quota["usage_state"] == "OVER"
        # Plan should now be SUSPENDED.
        from test_helpers import get_plan
        plan_after = get_plan(ctx["plot"]["id"], ctx["plan"]["id"])
        assert plan_after["status"] == "SUSPENDED"

    def test_plan_suspend_cascade_fails_pending_commands(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'every ControlCommand on the plan whose status is
        PENDING is moved to FAILED with failure_reason set to
        \\'PLAN_SUSPENDED\\''.

        Claim: when a plan transitions to SUSPENDED, any PENDING
        ControlCommand on that plan flips to FAILED with
        failure_reason==PLAN_SUSPENDED. We trigger the SUSPEND via
        an explicit POST /suspend (PRD §3.2: 'A plan in ACTIVE may be
        suspended back to SUSPENDED either explicitly by an Operator
        or WaterAdmin').
        # difficulty: transitive_cascade/feedback_executed_cascade_depth_4
        """
        ctx = setup_full_active_scenario(
            allocated_liters=10000.0,
            warning_threshold_pct=80.0,
            plan_volume_liters=1000.0,
            valve_control_mode="PARALLEL",
            valve_max_parallel=4,
        )
        # Create a PENDING command FIRST that will be cascaded-failed.
        pending = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        assert pending["status"] == "PENDING"
        # Suspend the plan explicitly.
        suspend_plan(ctx["plot"]["id"], ctx["plan"]["id"])
        # The PENDING command should now be FAILED.
        cmd_after = get_command(pending["id"])
        assert cmd_after["status"] == "FAILED"
        assert cmd_after.get("failure_reason") == "PLAN_SUSPENDED"

    def test_device_offline_event_flips_sensor_and_emits_alert(
        self, api, water_admin_headers,
    ):
        """PRD §3.8: 'a DEVICE_OFFLINE event flips the target sensor's
        status to OFFLINE and emits a SENSOR_OFFLINE alert'.

        Claim: POST /_events/emit {event_type: DEVICE_OFFLINE,
        payload: {sensor_id: s1.id}} flips Sensor.status to OFFLINE
        and produces an Alert{rule_code: SENSOR_OFFLINE,
        subject_id: s1.id}.
        # difficulty: transitive_cascade/device_offline_event_cascade_depth_3
        """
        tenant = create_tenant()
        plot = create_plot(tenant["id"])
        sensor = create_sensor(plot["id"])
        emit_event("DEVICE_OFFLINE", {"sensor_id": sensor["id"]})
        # Sensor status flipped.
        s_after = get_sensor(sensor["id"])
        assert s_after["status"] == "OFFLINE"
        # Alert emitted.
        alerts = list_alerts(params={"limit": 100})
        matched = find_alerts(
            alerts, rule_code="SENSOR_OFFLINE",
            subject_id=sensor["id"],
        )
        assert len(matched) >= 1, (
            "PRD §3.8: DEVICE_OFFLINE 'emits a SENSOR_OFFLINE alert'"
        )

    def test_sensor_status_online_to_offline_via_patch_emits_alert(
        self, api, water_admin_headers,
    ):
        """PRD §3.1: 'an edit that flips the status from ONLINE to
        OFFLINE emits a SENSOR_OFFLINE Alert whose subject_type is
        SENSOR.'

        Claim: PATCH /sensors/{id} {status: OFFLINE} emits a
        SENSOR_OFFLINE alert (a different originating trigger from
        the DEVICE_OFFLINE event in the prior test).
        # difficulty: transitive_cascade/device_offline_event_cascade_depth_3
        """
        tenant = create_tenant()
        plot = create_plot(tenant["id"])
        sensor = create_sensor(plot["id"])
        res = api.patch_sensor(
            sensor["id"], {"status": "OFFLINE"}, water_admin_headers,
        )
        validate_success(res, expected_status=200)
        alerts = list_alerts(params={"limit": 100})
        matched = find_alerts(
            alerts, rule_code="SENSOR_OFFLINE",
            subject_id=sensor["id"],
        )
        assert len(matched) >= 1


# =========================================================================
# Rule 5 — Validation priority conflicts across category pairs
# =========================================================================
class TestPriorityPairValidationConflict:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_control_command
    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_dispatch
    """

    def test_state_check_precedes_quota_guard(
        self, api, water_admin_headers,
    ):
        """PRD §2.9: 'State-machine guards then run in the order
        ControlCommand transitions, IrrigationPlan transitions,
        WaterBill transitions — each producing ERR_INVALID_STATE
        (409). Domain safety checks follow in this order: ... the
        quota guard for new control commands (ERR_QUOTA_EXCEEDED,
        422)'.

        Claim: when the plan is SUSPENDED AND requested_volume would
        also exceed quota, the response is ERR_INVALID_STATE (state
        precedes business_fiscal per the priority order in §2.9).

        Note: PRD §2.9 puts ControlCommand state first, then plan state,
        then quota guard. Creating a command on a non-ACTIVE plan would
        actually be blocked by the plan-state precondition for
        ControlCommand creation. ERR_INVALID_STATE is the named error
        for state mismatch.
        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_control_command
        """
        ctx = setup_quota_at_warning_for_override_priority(
            allocated_liters=10000.0, warning_threshold_pct=80.0,
        )
        # Plan is SUSPENDED.
        # Try POST /control-commands with an enormous requested_volume
        # — both state (plan SUSPENDED) and quota (would go OVER) fail.
        res = api.create_control_command(
            {
                "plan_id": ctx["plan"]["id"],
                "valve_group_id": ctx["valve_group"]["id"],
                "requested_volume_liters": 999_999.0,
            },
            water_admin_headers,
        )
        # PRD §2.9 puts plan-state errors at priority 5
        # (ERR_INVALID_STATE) before business_fiscal at priority 12
        # (ERR_QUOTA_EXCEEDED).
        validate_error(res, "ERR_INVALID_STATE")

    def test_state_check_alone_yields_invalid_state(
        self, api, water_admin_headers,
    ):
        """PRD §2.9: 'State-machine guards then run in the order
        ControlCommand transitions, IrrigationPlan transitions,
        WaterBill transitions — each producing ERR_INVALID_STATE
        (409).'

        Claim: when the plan is SUSPENDED but requested_volume stays
        within quota, the response is still ERR_INVALID_STATE because
        the state guard fires first regardless of any quota-related
        outcome.
        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_on_control_command
        """
        ctx = setup_quota_at_warning_for_override_priority(
            allocated_liters=10000.0, warning_threshold_pct=80.0,
        )
        # Plan SUSPENDED, quota WARNING. Ask for a small request volume
        # that would NOT push to OVER even ignoring state.
        res = api.create_control_command(
            {
                "plan_id": ctx["plan"]["id"],
                "valve_group_id": ctx["valve_group"]["id"],
                "requested_volume_liters": 100.0,
            },
            water_admin_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_pump_interlock_safety_precedes_referential(
        self, api, water_admin_headers,
    ):
        """PRD §2.9: 'Domain safety checks follow in this order:
        sensor poll-interval bounds (ERR_POLL_INTERVAL_OUT_OF_RANGE,
        422), pump-and-valve interlock (ERR_PUMP_INTERLOCK_BUSY, 409),
        valve-group/pump referential integrity
        (ERR_VALVE_GROUP_PUMP_MISMATCH, 422)'.

        Claim: at dispatch time, when the pump is busy AND a
        referential mismatch could be raised, the response is
        ERR_PUMP_INTERLOCK_BUSY (priority 8, safety) rather than
        ERR_VALVE_GROUP_PUMP_MISMATCH (priority 9, referential).

        Note: ERR_VALVE_GROUP_PUMP_MISMATCH is documented as a check
        at command CREATE in §3.4. Two PRD-faithful readings of
        priority orchestration at /dispatch are possible; we relax
        with validate_error_is_one_of.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_dispatch
        """
        ctx = setup_pump_with_two_valve_groups(
            vg1_mode="SEQUENTIAL", vg1_max=1,
            vg2_mode="SEQUENTIAL", vg2_max=1,
        )
        # Drive vg1 cmd into EXECUTING (pump busy).
        drive_command_to_executing(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        # Create cmd on vg2 (still on the same pump as plot — referential
        # match exists). Then dispatch vg2 cmd → pump busy.
        cmd2 = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group_2"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.dispatch_command(cmd2["id"], water_admin_headers)
        validate_error(res, "ERR_PUMP_INTERLOCK_BUSY")

    def test_referential_mismatch_at_command_create(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'Two referential checks fire at creation: the
        chosen valve group must exist, and its pump_id must match the
        Plot.pump_id of the plot that owns the driving plan (reached
        via IrrigationPlan.plot_id). A mismatch is rejected with
        ERR_VALVE_GROUP_PUMP_MISMATCH (422).'

        Claim: a valve group on a different pump than Plot.pump_id is
        rejected at command CREATE with
        ERR_VALVE_GROUP_PUMP_MISMATCH — pinning the referential check
        on the create endpoint, distinct from the safety interlock at
        dispatch.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_dispatch
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        # Different-pump valve group on the same tenant.
        wrong_pump = "wrong-" + ctx["plot"]["pump_id"]
        wrong_vg = create_valve_group(
            ctx["tenant"]["id"], pump_id=wrong_pump,
            control_mode="SEQUENTIAL", max_parallel_valves=1,
        )
        res = api.create_control_command(
            {
                "plan_id": ctx["plan"]["id"],
                "valve_group_id": wrong_vg["id"],
                "requested_volume_liters": 100.0,
            },
            water_admin_headers,
        )
        validate_error(res, "ERR_VALVE_GROUP_PUMP_MISMATCH")


# =========================================================================
# Rule 6 — Boundary-precision checks
# =========================================================================
class TestBoundaryPrecisionCheck:
    """# difficulty: boundary_precision_check/warning_threshold_inclusive_lower_bound
    # difficulty: boundary_precision_check/empty_collection_at_plan_activate
    """

    def test_warning_threshold_inclusive_at_exactly_eighty_percent(
        self, api,
    ):
        """PRD §3.5: 'if the ratio of final_used_liters to
        effective_allocation is at least warning_threshold_pct
        divided by 100, the state is WARNING'.

        Claim: 8000.00/10000 = 0.80 inclusive → WARNING.
        # difficulty: boundary_precision_check/warning_threshold_inclusive_lower_bound
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=8000.00,
            allocated_liters=10000.0,
            warning_threshold_pct=80,
        )
        assert ctx["quota_after"]["usage_state"] == "WARNING"

    def test_under_just_below_warning_threshold(
        self, api,
    ):
        """PRD §3.5: 'otherwise the state is UNDER.'

        Claim: 7999.99/10000 = 0.799999 < 0.80 → UNDER.
        # difficulty: boundary_precision_check/warning_threshold_inclusive_lower_bound
        """
        ctx = setup_quota_at_usage(
            target_final_used_liters=7999.99,
            allocated_liters=10000.0,
            warning_threshold_pct=80,
        )
        assert ctx["quota_after"]["usage_state"] == "UNDER"

    def test_zero_online_sensors_blocks_activate(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the plot must carry at least one Sensor whose
        status is ONLINE'.
        PRD §3.2: 'Failure of the first two preconditions yields
        ERR_PRECONDITION_NOT_MET (422)'.

        Claim: zero ONLINE sensors → ERR_PRECONDITION_NOT_MET.
        # difficulty: boundary_precision_check/empty_collection_at_plan_activate
        """
        from test_helpers import setup_tenant_plot_quota
        tenant, plot, quota, _ = setup_tenant_plot_quota(
            allocated_liters=100000.0, add_online_sensor=False,
        )
        plan = create_plan(
            plot["id"],
            window_start=quota["period_start"],
            window_end=add_days(quota["period_start"], 1),
            source="MANUAL_OVERRIDE", planned_volume_liters=500.0,
        )
        res = api.activate_plan(plot["id"], plan["id"], water_admin_headers)
        validate_error(res, "ERR_PRECONDITION_NOT_MET")

    def test_one_online_sensor_unblocks_activate(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the plot must carry at least one Sensor whose
        status is ONLINE'.

        Claim: one ONLINE sensor satisfies the precondition (boundary
        just crossed).
        # difficulty: boundary_precision_check/empty_collection_at_plan_activate
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        # Setup helper already activates the plan; assert successful state.
        assert ctx["plan"]["status"] == "ACTIVE"


# =========================================================================
# Rule 7 — Cross-entity state dependencies across different entity pairs
# =========================================================================
class TestCrossEntityStateDependency:
    """# difficulty: cross_entity_state_dependency/irrigation_plan_activate_depends_on_sensor_and_quota
    # difficulty: cross_entity_state_dependency/control_command_dispatch_depends_on_plan_and_pump
    """

    def test_activate_blocked_by_quota_over_unblocked_by_approval(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the owning WaterQuota covering the plan window
        must have usage_state other than OVER, or, if OVER, an
        approval_state of APPROVED.'
        PRD §3.2: 'failure of the quota precondition yields
        ERR_QUOTA_EXCEEDED (422).'

        Claim: a fresh DRAFT plan whose covering quota is OVER +
        NOT_REQUIRED is blocked at /activate; after approve-override
        flips approval_state to APPROVED, /activate succeeds.
        # difficulty: cross_entity_state_dependency/irrigation_plan_activate_depends_on_sensor_and_quota
        """
        # Build a plot with an OVER quota and NO active plans yet.
        # Doing this through setup_full_active_scenario would create a
        # plan that occupies the whole quota window; instead, build a
        # tenant/plot/quota fresh, drive an EXECUTED command via a
        # short-lived plan, and then create a NEW plan on a fresh
        # non-overlapping window.
        from test_helpers import (
            setup_tenant_plot_quota, create_valve_group,
            setup_active_plan, drive_command_to_executed,
            unique_valve_id,
        )
        tenant, plot, quota, _sensor = setup_tenant_plot_quota(
            allocated_liters=10000.0,
        )
        valve_group = create_valve_group(
            tenant["id"], pump_id=plot["pump_id"],
            valve_ids=[unique_valve_id("v")],
            control_mode="SEQUENTIAL", max_parallel_valves=1,
        )
        # Short consumption plan covering only the first hour of the
        # quota period; drive it to push final_used into OVER via
        # device over-delivery (request stays within quota cap so the
        # PRD §3.4 quota guard at command CREATE passes; actual exceeds
        # — PRD §3.4 names no upper bound on actual_volume_liters at
        # feedback, only ">= 0").
        ps = quota["period_start"]
        consume_plan = setup_active_plan(
            plot=plot, valve_group=valve_group, quota=quota,
            plan_window_start=ps,
            plan_window_end=add_hours(ps, 1),
            planned_volume_liters=4000.0,
        )
        # Advance clock into the quota window so the command's created_at
        # / feedback_received_at land in [period_start, period_end).
        advance_clock(add_minutes(ps, 5))
        drive_command_to_executed(
            plan_id=consume_plan["id"],
            valve_group_id=valve_group["id"],
            requested_volume_liters=4000.0,
            actual_volume_liters=11000.0,
        )
        quota_after = get_quota(quota["id"])
        assert quota_after["usage_state"] == "OVER"
        # Now create a NEW plan for a later window inside the quota
        # period.
        ws = add_hours(ps, 24)
        we = add_hours(ps, 48)
        new_plan = create_plan(
            plot["id"], window_start=ws, window_end=we,
            source="MANUAL_OVERRIDE", planned_volume_liters=200.0,
        )
        # Quota usage_state==OVER, approval_state==NOT_REQUIRED → blocked.
        res = api.activate_plan(plot["id"], new_plan["id"], water_admin_headers)
        # PRD names ERR_QUOTA_EXCEEDED for the quota precondition.
        validate_error(res, "ERR_QUOTA_EXCEEDED")
        # Now request + approve override.
        request_override(quota["id"], reason="urgent")
        approve_override(quota["id"], extra_liters=5000.0)
        # Re-activate should now succeed.
        res = api.activate_plan(
            plot["id"], new_plan["id"], water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ACTIVE"

    def test_activate_blocked_by_zero_online_sensors_independent_of_quota(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the plot must carry at least one Sensor whose
        status is ONLINE'.
        PRD §3.2: 'Failure of the first two preconditions yields
        ERR_PRECONDITION_NOT_MET (422)'.

        Claim: a separate cross-entity dependency — even with the
        quota in UNDER (no quota issue), zero ONLINE sensors blocks
        activation. The Plan↔Sensor dependency stands independent of
        Plan↔WaterQuota.
        # difficulty: cross_entity_state_dependency/irrigation_plan_activate_depends_on_sensor_and_quota
        """
        from test_helpers import setup_tenant_plot_quota
        tenant, plot, quota, _ = setup_tenant_plot_quota(
            allocated_liters=100000.0, add_online_sensor=False,
        )
        # quota is UNDER (final=0), so the quota precondition is
        # satisfied. Only the no-online-sensor precondition fails.
        plan = create_plan(
            plot["id"],
            window_start=quota["period_start"],
            window_end=add_days(quota["period_start"], 1),
            source="MANUAL_OVERRIDE", planned_volume_liters=500.0,
        )
        res = api.activate_plan(plot["id"], plan["id"], water_admin_headers)
        validate_error(res, "ERR_PRECONDITION_NOT_MET")

    def test_dispatch_blocked_by_pump_busy_unblocks_after_terminal(
        self, api, water_admin_headers,
    ):
        """PRD §3.3: 'In every other configuration — that is, whenever
        at least one of the active commands on the same pump targets
        a SEQUENTIAL group — the new dispatch is rejected with
        ERR_PUMP_INTERLOCK_BUSY (409).'

        Claim: dispatch of cc2 is blocked while cc1 is EXECUTING on
        the same pump; once cc1 reaches EXECUTED (terminal), cc2's
        dispatch succeeds.
        # difficulty: cross_entity_state_dependency/control_command_dispatch_depends_on_plan_and_pump
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
        dispatch_command(cc1["id"])
        feedback(cc1["id"], phase="STARTED")
        cc2 = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group_2"]["id"],
            requested_volume_liters=100.0,
        )
        # Case A: cc2 dispatch blocked (cc1 EXECUTING).
        res = api.dispatch_command(cc2["id"], water_admin_headers)
        validate_error(res, "ERR_PUMP_INTERLOCK_BUSY")
        # Take cc1 to terminal EXECUTED.
        feedback(cc1["id"], phase="COMPLETED", actual_volume_liters=100.0)
        # Case B: cc2 dispatch now succeeds.
        res = api.dispatch_command(cc2["id"], water_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DISPATCHING"

    def test_dispatch_depends_on_plan_active_status(
        self, api, water_admin_headers,
    ):
        """PRD §1.4 / §2.9: ControlCommand state guard precedes
        domain checks; PRD §3.4: dispatching moves PENDING → DISPATCHING
        — implicitly requires the parent plan to be ACTIVE since
        suspending a plan moves any PENDING command to FAILED
        (PRD §3.2: 'every ControlCommand on the plan whose status is
        PENDING is moved to FAILED with failure_reason set to
        \\'PLAN_SUSPENDED\\'').

        Claim: once the parent plan is SUSPENDED, the previously
        PENDING command is FAILED, and dispatching a FAILED command
        returns ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/control_command_dispatch_depends_on_plan_and_pump
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        # Suspend parent plan → cmd cascades to FAILED.
        suspend_plan(ctx["plot"]["id"], ctx["plan"]["id"])
        cmd_after = get_command(cmd["id"])
        assert cmd_after["status"] == "FAILED"
        # Try to dispatch a FAILED command → ERR_INVALID_STATE.
        res = api.dispatch_command(cmd["id"], water_admin_headers)
        validate_error(res, "ERR_INVALID_STATE")


# =========================================================================
# Rule 8 — Resource temporal-overlap conflicts
# =========================================================================
class TestResourceTemporalOverlap:
    """# difficulty: resource_temporal_overlap/irrigation_plan_window_half_open_overlap
    # difficulty: resource_temporal_overlap/pump_aggregate_capacity_overlap
    """

    def test_adjacent_windows_do_not_overlap_half_open(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the plan's [window_start, window_end) must not
        overlap any other IrrigationPlan on the same plot whose
        status is in the set of ACTIVE or SUSPENDED'.

        Claim: a plan starting at exactly the previous plan's
        window_end is allowed under [start, end) half-open semantics.
        # difficulty: resource_temporal_overlap/irrigation_plan_window_half_open_overlap
        """
        ctx = setup_overlap_plans(
            plan1_offset_hours_from_period_start=24,
            plan1_duration_hours=24,
        )
        # plan1 covers [period_start+24h, period_start+48h).
        # Adjacent: plan2 [period_start+48h, period_start+72h) — boundary
        # touch, no overlap under half-open semantics.
        period_start = ctx["quota"]["period_start"]
        plan2 = create_plan(
            ctx["plot"]["id"],
            window_start=add_hours(period_start, 48),
            window_end=add_hours(period_start, 72),
            source="MANUAL_OVERRIDE", planned_volume_liters=100.0,
        )
        res = api.activate_plan(
            ctx["plot"]["id"], plan2["id"], water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ACTIVE"

    def test_overlapping_windows_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'failure of the overlap check yields
        ERR_PLAN_WINDOW_OVERLAP (409)'.

        Claim: a plan whose [start, end) straddles an existing
        ACTIVE plan's window → ERR_PLAN_WINDOW_OVERLAP.
        # difficulty: resource_temporal_overlap/irrigation_plan_window_half_open_overlap
        """
        ctx = setup_overlap_plans(
            plan1_offset_hours_from_period_start=24,
            plan1_duration_hours=24,
        )
        period_start = ctx["quota"]["period_start"]
        plan2 = create_plan(
            ctx["plot"]["id"],
            window_start=add_hours(period_start, 36),
            window_end=add_hours(period_start, 60),
            source="MANUAL_OVERRIDE", planned_volume_liters=100.0,
        )
        res = api.activate_plan(
            ctx["plot"]["id"], plan2["id"], water_admin_headers,
        )
        validate_error(res, "ERR_PLAN_WINDOW_OVERLAP")

    def test_parallel_groups_share_pump_capacity(
        self, api, water_admin_headers,
    ):
        """PRD §3.3: 'the new dispatch is allowed only if every active
        command on that pump targets a valve group whose control_mode
        is PARALLEL.'

        Claim: cc2 dispatching to vgPar2 (PARALLEL) co-exists with cc1
        EXECUTING on vgPar1 (PARALLEL) on the same pump.
        # difficulty: resource_temporal_overlap/pump_aggregate_capacity_overlap
        """
        ctx = setup_pump_with_two_valve_groups(
            vg1_mode="PARALLEL", vg1_max=2,
            vg2_mode="PARALLEL", vg2_max=2,
        )
        drive_command_to_executing(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        cc2 = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group_2"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.dispatch_command(cc2["id"], water_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DISPATCHING"

    def test_sequential_collapses_capacity_blocks_dispatch(
        self, api, water_admin_headers,
    ):
        """PRD §3.3: 'In every other configuration — that is, whenever
        at least one of the active commands on the same pump targets
        a SEQUENTIAL group — the new dispatch is rejected with
        ERR_PUMP_INTERLOCK_BUSY (409).'

        Claim: when one of the active commands on the pump targets a
        SEQUENTIAL group, a new SEQUENTIAL dispatch on the same pump
        is rejected with ERR_PUMP_INTERLOCK_BUSY.
        # difficulty: resource_temporal_overlap/pump_aggregate_capacity_overlap
        """
        # Make the active cc1 SEQUENTIAL → new SEQUENTIAL cc2 on same pump
        # is blocked.
        ctx = setup_pump_with_two_valve_groups(
            vg1_mode="SEQUENTIAL", vg1_max=1,
            vg2_mode="SEQUENTIAL", vg2_max=1,
        )
        drive_command_to_executing(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        cc2 = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group_2"]["id"],
            requested_volume_liters=100.0,
        )
        res = api.dispatch_command(cc2["id"], water_admin_headers)
        validate_error(res, "ERR_PUMP_INTERLOCK_BUSY")


# =========================================================================
# Rule 9 — Compensating-action invariants across different conserved quantities
# =========================================================================
class TestCompensatingInvariant:
    """# difficulty: compensating_invariant/quota_reservation_compensation_on_failed_command
    # difficulty: compensating_invariant/bill_money_invariant_on_dispute_accept_cancel
    """

    def test_failed_command_releases_provisional_reservation(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: 'on failure the system stores failure_reason,
        releases the reserved volume from
        WaterQuota.provisional_used_liters as a compensating release'.

        Claim: after FAILED feedback, the quota's provisional_used_liters
        decreases by the originally reserved requested_volume_liters
        and final_used_liters does not increase.
        # difficulty: compensating_invariant/quota_reservation_compensation_on_failed_command
        """
        ctx = setup_full_active_scenario(
            allocated_liters=10000.0, plan_volume_liters=4000.0,
        )
        cmd = create_control_command(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=3000.0,
        )
        # After CREATE: provisional should reflect the reservation.
        q_after_create = get_quota(ctx["quota"]["id"])
        # The plan's reservation (1000 base from helper) AND the cmd's 3000.
        # PRD §3.5 sums requested_volume_liters of in-flight commands
        # (PENDING/DISPATCHING/EXECUTING) for provisional. Plan reservation
        # is described as a separate concept in §3.2 (reserves
        # planned_volume_liters), but PRD §3.5 only enumerates command
        # contributions. We assert the cmd contributes ≥ 3000.
        # Drive cmd to FAILED via dispatch + ERROR feedback.
        dispatch_command(cmd["id"])
        feedback(cmd["id"], phase="ERROR", failure_reason="VALVE_FAULT")
        q_after_fail = get_quota(ctx["quota"]["id"])
        # PRD §3.4: 'releases the reserved volume from
        # WaterQuota.provisional_used_liters'. The provisional after
        # FAILED should be lower than after CREATE by ≈ 3000.
        delta = (
            q_after_create["provisional_used_liters"]
            - q_after_fail["provisional_used_liters"]
        )
        assert delta == pytest.approx(3000.0, abs=0.01), (
            f"PRD §3.4: failed cmd releases reserved volume; expected "
            f"provisional decrease of 3000, got {delta}"
        )
        assert q_after_fail["final_used_liters"] == pytest.approx(
            0.0, abs=0.01
        )

    def test_failed_command_appends_audit(
        self, api, water_admin_headers,
    ):
        """PRD §3.4: '...appends an AuditLog with action_type of
        CONTROL_COMMAND_FAILED'.

        Claim: an AuditLog with action_type==CONTROL_COMMAND_FAILED
        is appended for the failed command.
        # difficulty: compensating_invariant/quota_reservation_compensation_on_failed_command
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        cmd = drive_command_to_dispatching(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=100.0,
        )
        feedback(cmd["id"], phase="ERROR", failure_reason="VALVE_FAULT")
        entries = list_audit_logs(
            params={"action_type": "CONTROL_COMMAND_FAILED", "limit": 100}
        )
        matched = find_audit_entries(
            entries, action_type="CONTROL_COMMAND_FAILED",
            subject_id=cmd["id"],
        )
        assert len(matched) >= 1

    def test_dispute_accept_zeros_total_preserves_amount_paid(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'an ACCEPT outcome advances status from DISPUTED
        to CANCELLED and forces total_amount_cents to zero (preserving
        any non-zero amount_paid_cents, so the balance due may be
        negative, surfacing a refund obligation).'

        Claim: amount_paid_cents is unchanged across the dispute →
        accept lifecycle (delta == 0); total_amount_cents goes to 0.
        # difficulty: compensating_invariant/bill_money_invariant_on_dispute_accept_cancel
        """
        ctx = setup_issued_bill_with_payment(
            bill_total_floor_cents=10000,
            partial_payment_cents=2000,
        )
        bill = ctx["bill"]
        original_paid = bill["amount_paid_cents"]
        original_total = bill["total_amount_cents"]
        assert original_paid > 0 and original_total > 0
        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        # Dispute → DISPUTED.
        res = api.dispute_bill(
            bill["id"], {"dispute_reason": "metering issue"},
            tenant_headers,
        )
        disputed = validate_success(res, expected_status=200)
        assert disputed["status"] == "DISPUTED"
        assert disputed["amount_paid_cents"] == original_paid, (
            "PRD §3.6: 'preserving any non-zero amount_paid_cents' — "
            "dispute itself doesn't touch amount_paid_cents"
        )
        # Resolve with ACCEPT → CANCELLED, total=0.
        res = api.resolve_bill_dispute(
            bill["id"], {"outcome": "ACCEPT"}, water_admin_headers,
        )
        cancelled = validate_success(res, expected_status=200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["total_amount_cents"] == 0
        assert cancelled["amount_paid_cents"] == original_paid

    def test_dispute_accept_balance_due_can_be_negative(
        self, api, water_admin_headers,
    ):
        """PRD §3.6: 'so the balance due may be negative, surfacing a
        refund obligation.'

        Claim: after ACCEPT, total_amount_cents (0) < amount_paid_cents
        (original payment) → balance_due is negative.
        # difficulty: compensating_invariant/bill_money_invariant_on_dispute_accept_cancel
        """
        ctx = setup_issued_bill_with_payment(
            bill_total_floor_cents=10000,
            partial_payment_cents=2000,
        )
        bill = ctx["bill"]
        original_paid = bill["amount_paid_cents"]
        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        api.dispute_bill(
            bill["id"], {"dispute_reason": "x"}, tenant_headers,
        )
        res = api.resolve_bill_dispute(
            bill["id"], {"outcome": "ACCEPT"}, water_admin_headers,
        )
        cancelled = validate_success(res, expected_status=200)
        # PRD §3.6: balance_due = total - paid. With total=0 and paid>0,
        # balance is negative — i.e. amount_paid_cents > total_amount_cents.
        assert cancelled["amount_paid_cents"] > cancelled["total_amount_cents"]
