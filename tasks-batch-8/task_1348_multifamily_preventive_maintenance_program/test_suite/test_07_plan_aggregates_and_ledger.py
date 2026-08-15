"""Plan aggregates, budget ledger structure, rounding order, and the
commit/settle and clawback conservation invariants."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_paginated,
    ApiErrorId,
    api_client,
    create_property, create_building, create_unit, create_asset,
    create_batch, add_visit, publish_batch, set_clock, start_visit,
    complete_visit,
    get_plan, get_asset, get_deficiency,
    plan_ledger_entries, visit_ledger_entries, wo_ledger_entries,
    assert_ledger_entries_exactly,
    setup_property_scaffold, setup_published_visit, setup_in_progress_visit,
    setup_completed_visit, setup_wo_completed, verify_work_order,
)


class TestImmutableLedgerEntryHasNoVersion:
    def test_publish_writes_single_visit_commit_without_version_field(self, api):
        """PRD §3.3: "For each non-`CANCELLED` visit, the ledger writes a
        `VISIT_COMMIT` for the estimated visit cost". PRD §2.5: "Four record
        types are append-only and carry **only** `id` and `created_at` — both
        `updated_at` and `version` are absent from them: ComplianceEvidence,
        BudgetLedgerEntry, CapitalForecastSnapshot, and CompletionAudit."

        Design: Corner/entities/immutable_ledger_entry_has_no_update
        """
        ctx = setup_property_scaffold()
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-10T18:00:00Z")
        add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"],
                  ctx["asset"]["id"], ctx["plan"]["id"],
                  scheduled_start="2026-08-10T09:00:00Z")
        publish_batch(batch["id"])

        entries = plan_ledger_entries(ctx["plan"]["id"])
        assert_ledger_entries_exactly(entries, [("VISIT_COMMIT", 3000)])  # 30 min at 6000/h
        entry = entries[0]
        assert "version" not in entry, "append-only ledger entry must not carry version"
        assert "updated_at" not in entry, "append-only ledger entry must not carry updated_at"
        assert entry["source_visit_id"] is not None
        assert entry["source_work_order_id"] is None


class TestLaborPlanHoursVsActualMinutesDivergence:
    """One template estimated 90 minutes; one visit completed in 45 minutes."""

    def _setup(self):
        return setup_published_visit(estimated_labor_minutes=90)

    def test_planned_hours_ceiling_and_zero_actual_before_completion(self, api):
        """PRD §3.2: "`planned_labor_hours` is the forward-looking figure: the
        `estimated_labor_minutes` of every visit under the plan in `SCHEDULED`,
        `NOTIFIED`, `IN_PROGRESS`, or `COMPLETED` are summed, divided by 60, and
        rounded **up** to a whole number of hours. `actual_labor_minutes` is the
        backward-looking figure: the raw sum of technician-recorded
        `actual_minutes` across `COMPLETED` visits only, and zero when none have
        completed."

        Design: Difficulty/dual_variant_calc/labor_plan_hours_vs_actual_minutes_divergence
        """
        ctx = self._setup()
        plan = get_plan(ctx["plan"]["id"])
        assert plan["planned_labor_hours"] == 2, (
            f"ceil(90/60) must be 2, got {plan['planned_labor_hours']}"
        )
        assert plan["actual_labor_minutes"] == 0

    def test_after_completion_planned_still_two_actual_is_45(self, api):
        """PRD §3.2: "`actual_labor_minutes` is the backward-looking figure: the
        raw sum of technician-recorded `actual_minutes` across `COMPLETED` visits
        only". The planned variant keeps counting the COMPLETED visit's 90
        estimated minutes (rounded up to 2 hours) while the actual variant
        records the 45 minutes really worked — the two variants deliberately
        measure different things for the same plan.

        Design: Difficulty/dual_variant_calc/labor_plan_hours_vs_actual_minutes_divergence
        """
        ctx = self._setup()
        set_clock("2026-08-02T09:00:00Z")
        start_visit(ctx["visit"]["id"], technician_id="tech-1")
        complete_visit(ctx["visit"]["id"], 45, 4, technician_id="tech-1")
        plan = get_plan(ctx["plan"]["id"])
        assert plan["planned_labor_hours"] == 2
        assert plan["actual_labor_minutes"] == 45, (
            f"only the 45 recorded minutes count, got {plan['actual_labor_minutes']}"
        )


class TestBudgetBurnRoundingOrder:
    """Rate 6100 cents/hour with a 7-minute template: each visit's cost is
    round_half_up(7 * 6100 / 60) = 712, rounded per event before summing."""

    def _setup_three_completed_visits(self):
        ctx = setup_property_scaffold(
            component_type="APPLIANCE", estimated_labor_minutes=7, frequency_days=30,
            rate_cents_per_hour=6100, warranty_months=12, replacement_cost_cents=100000,
        )
        unit2 = create_unit(ctx["building"]["id"], unit_number="102", occupancy_status="VACANT")
        unit3 = create_unit(ctx["building"]["id"], unit_number="103", occupancy_status="VACANT")
        asset2 = create_asset(unit2["id"], component_type="APPLIANCE",
                              warranty_months=12, replacement_cost_cents=100000)
        asset3 = create_asset(unit3["id"], component_type="APPLIANCE",
                              warranty_months=12, replacement_cost_cents=100000)
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-02T08:00:00Z",
                             window_end="2026-08-02T20:00:00Z")
        v1 = add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"], ctx["asset"]["id"],
                       ctx["plan"]["id"], scheduled_start="2026-08-02T09:00:00Z")
        v2 = add_visit(batch["id"], unit2["id"], ctx["template"]["id"], asset2["id"],
                       ctx["plan"]["id"], scheduled_start="2026-08-02T10:00:00Z")
        v3 = add_visit(batch["id"], unit3["id"], ctx["template"]["id"], asset3["id"],
                       ctx["plan"]["id"], scheduled_start="2026-08-02T11:00:00Z")
        publish_batch(batch["id"])
        visits = []
        for visit, clock in ((v1, "2026-08-02T09:00:00Z"),
                             (v2, "2026-08-02T10:00:00Z"),
                             (v3, "2026-08-02T11:00:00Z")):
            set_clock(clock)
            start_visit(visit["id"], technician_id="tech-1")
            visits.append(complete_visit(visit["id"], 7, 4, technician_id="tech-1"))
        ctx["visits"] = visits
        return ctx

    def test_spent_is_sum_of_per_event_rounded_costs(self, api):
        """PRD §2.7: "First, each individual monetary event is rounded **half-up
        to a whole cent at the moment it is computed**; second, totals are always
        sums of those already-rounded events — the system never sums unrounded
        values and rounds the total." Three events of 712 cents total 2136; a
        sum-then-round implementation would report 2135.

        Design: Difficulty/combinatorial_formula/budget_burn_mode_b_rounding_order
        """
        ctx = self._setup_three_completed_visits()
        plan = get_plan(ctx["plan"]["id"])
        assert plan["spent_cents"] == 2136, (
            f"3 x round_half_up(7*6100/60) = 3 x 712 = 2136, got {plan['spent_cents']}"
        )
        assert plan["committed_cents"] == 0

    def test_each_visit_settle_is_individually_rounded_to_712(self, api):
        """PRD §2.7: "The cost of a completed visit is the technician's recorded
        `actual_minutes` multiplied by the property's
        `default_labor_rate_cents_per_hour`, divided by 60, rounded half-up to a
        whole cent". PRD §2.8: "completion writes a `VISIT_RELEASE` for the
        negative of the estimate followed by a `VISIT_SETTLE` for the positive
        actual cost."

        Design: Difficulty/combinatorial_formula/budget_burn_mode_b_rounding_order
        """
        ctx = self._setup_three_completed_visits()
        for visit in ctx["visits"]:
            assert visit["visit_cost_cents"] == 712, (
                f"per-event cost must be round_half_up(7*6100/60)=712, got {visit['visit_cost_cents']}"
            )
            entries = visit_ledger_entries(visit["id"])
            assert_ledger_entries_exactly(entries, [
                ("VISIT_COMMIT", 712),
                ("VISIT_RELEASE", -712),
                ("VISIT_SETTLE", 712),
            ])


class TestBudgetCommitSettlePairConservesCommitted:
    """Template estimated 30 minutes at 6000 cents/hour (estimate 3000); the
    visit completes with actual_minutes=40 (actual cost 4000)."""

    def test_commit_then_settle_leaves_zero_committed_and_actual_spent(self, api):
        """PRD §2.8: "Per visit, the committed contribution returns to exactly
        zero after cancellation, no-access, or completion, and `spent_cents`
        gains exactly the actual cost on completion."

        Design: Difficulty/compensating_invariant/budget_commit_settle_pair_conserves_committed
        """
        ctx = setup_published_visit(estimated_labor_minutes=30, budget_cents=1000000)
        plan_mid = get_plan(ctx["plan"]["id"])
        assert plan_mid["committed_cents"] == 3000, (
            f"publish commits the 30-minute estimate 3000, got {plan_mid['committed_cents']}"
        )
        assert plan_mid["spent_cents"] == 0

        set_clock("2026-08-02T09:00:00Z")
        start_visit(ctx["visit"]["id"], technician_id="tech-1")
        complete_visit(ctx["visit"]["id"], 40, 4, technician_id="tech-1")

        plan_end = get_plan(ctx["plan"]["id"])
        assert plan_end["committed_cents"] == 0, (
            f"estimate must be fully settled, got committed={plan_end['committed_cents']}"
        )
        assert plan_end["spent_cents"] == 4000, (
            f"spent gains exactly the actual cost 40*6000/60=4000, got {plan_end['spent_cents']}"
        )

    def test_visit_ledger_records_commit_release_settle_triplet(self, api):
        """PRD §2.8: "For a visit: batch publish writes a `VISIT_COMMIT` for the
        positive estimated cost; cancellation or no-access writes a
        `VISIT_RELEASE` for exactly the negative of that estimate, so the pair
        cancels to zero; completion writes a `VISIT_RELEASE` for the negative of
        the estimate followed by a `VISIT_SETTLE` for the positive actual cost."

        Design: Difficulty/compensating_invariant/budget_commit_settle_pair_conserves_committed
        """
        ctx = setup_completed_visit(actual_minutes=40, condition_score=4,
                                    estimated_labor_minutes=30, budget_cents=1000000)
        entries = visit_ledger_entries(ctx["visit"]["id"])
        assert_ledger_entries_exactly(entries, [
            ("VISIT_COMMIT", 3000),
            ("VISIT_RELEASE", -3000),
            ("VISIT_SETTLE", 4000),
        ])


class TestWoFailVerificationClawbackConservesSpend:
    """Work order estimated 200000, completed at actual 180000; the visit that
    found the deficiency settled 4500 (45 minutes at 6000 cents/hour)."""

    def test_clawback_returns_spent_to_pre_completion_value(self, api):
        """PRD §2.8: "Per work order, `spent_cents` gains exactly
        `actual_cost_cents` on completion and loses exactly that amount on a
        failed verification — a complete-then-fail round trip leaves net
        recognized spend unchanged."

        Design: Difficulty/compensating_invariant/wo_fail_verification_clawback_conserves_spend
        """
        ctx = setup_wo_completed(
            actual_minutes=45, condition_score=3,
            component_type="WATER_HEATER", estimated_labor_minutes=45,
            installed_on="2023-01-01T00:00:00Z", replacement_cost_cents=300000,
            estimated_cost_cents=200000, actual_cost_cents=180000,
        )
        plan_peak = get_plan(ctx["plan"]["id"])
        assert plan_peak["spent_cents"] == 184500

        verify_work_order(ctx["work_order"]["id"], "FAIL", auditor_id="aud-2")
        plan_after = get_plan(ctx["plan"]["id"])
        assert plan_after["spent_cents"] == 4500, (
            f"clawback must release exactly the 180000 settle, got {plan_after['spent_cents']}"
        )

    def test_clawback_writes_release_of_settle_ledger_row(self, api):
        """PRD §2.8: "a failed verification writes a `WO_RELEASE` for the negative
        of the actual cost — a clawback of settled spend." PRD §3.6: "the asset
        returns to `OUT_OF_SERVICE`, and the originating deficiency reopens to
        `TRIAGED`."

        Design: Difficulty/compensating_invariant/wo_fail_verification_clawback_conserves_spend
        """
        ctx = setup_wo_completed(
            actual_minutes=45, condition_score=3,
            component_type="WATER_HEATER", estimated_labor_minutes=45,
            installed_on="2023-01-01T00:00:00Z", replacement_cost_cents=300000,
            estimated_cost_cents=200000, actual_cost_cents=180000,
        )
        verify_work_order(ctx["work_order"]["id"], "FAIL", auditor_id="aud-2")

        entries = wo_ledger_entries(ctx["work_order"]["id"])
        assert_ledger_entries_exactly(entries, [
            ("WO_COMMIT", 200000),
            ("WO_RELEASE", -200000),
            ("WO_SETTLE", 180000),
            ("WO_RELEASE", -180000),
        ])
        assert get_asset(ctx["asset"]["id"])["operational_status"] == "OUT_OF_SERVICE"
        assert get_deficiency(ctx["deficiency"]["id"])["status"] == "TRIAGED"


class TestImmediateVisibilityOfAggregates:
    def test_complete_response_and_plan_read_reflect_settlement_immediately(self, api):
        """PRD §3.4: "On success the visit becomes `COMPLETED`, the recorded
        minutes and score are persisted, and the visit's `visit_cost_cents` —
        zero until this moment — is computed per §2.7. The ledger releases the
        committed estimate and settles the actual cost as a compensating pair on
        the visit's `plan_id`. ... The plan's `actual_labor_minutes`,
        `spent_cents`, and `committed_cents` all recompute."

        Design: Corner/consistency_model/immediate_visibility_of_aggregates_after_complete
        """
        ctx = setup_in_progress_visit(estimated_labor_minutes=30)
        completed = complete_visit(ctx["visit"]["id"], 30, 4, technician_id="tech-1")
        assert completed["visit_cost_cents"] == 3000, (
            f"30 minutes at 6000 cents/hour must cost 3000, got {completed['visit_cost_cents']}"
        )
        plan = get_plan(ctx["plan"]["id"])
        assert plan["spent_cents"] == 3000, (
            f"plan spent must reflect the settle in the same act, got {plan['spent_cents']}"
        )
        assert plan["committed_cents"] == 0
        assert plan["actual_labor_minutes"] == 30
