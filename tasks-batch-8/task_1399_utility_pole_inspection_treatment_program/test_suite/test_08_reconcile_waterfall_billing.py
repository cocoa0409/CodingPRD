"""Cycle reconcile: task-terminal gate, funding waterfall, production billing, and the
immutable BacklogSnapshot (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_backlog_snapshot,
    assert_budget_invariant,
    create_budget,
    create_crew,
    create_manual_task,
    create_open_cycle,
    create_pole,
    create_replacement_order,
    create_verified_treatment,
    get_budget,
    get_crew,
    get_cycle,
    get_order,
    get_snapshots_for_cycle,
    reconcile_cycle,
    set_clock,
    validate_error,
    validate_success,
)


class TestReconcilePrecondition:
    def test_reconcile_with_open_tasks_rejected(self, api, program_manager_headers):
        """PRD §3.9: "Reconcile is refused while any of the cycle's tasks remain
        non-terminal — `tasks_terminal` must equal `tasks_total`, otherwise the request
        is rejected with `ERR_CYCLE_TASKS_OPEN` — and the named budget must resolve."

        Design: Corner/state_machines/reconcile_with_open_tasks_rejected
        """
        budget = create_budget(fiscal_year=2026, total_cents=1000)
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        pole = create_pole(pole_number="P-RO", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        create_manual_task(cycle["id"], pole["id"])
        resp = api.reconcile_inspection_cycle(cycle["id"], {"budget_id": budget["id"]},
                                              program_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CYCLE_TASKS_OPEN)
        assert get_cycle(cycle["id"])["status"] == "OPEN"
        assert get_snapshots_for_cycle(cycle["id"]) == [], (
            "a refused reconcile writes no snapshot"
        )


class TestWaterfallFunding:
    def _setup_waterfall(self, api):
        """O1 (FEEDER_CRITICAL, joint-use, 1965 -> priority 80, cost 300000),
        O2 (joint-use, 1965 -> 65, cost 200000), O3 (plain 1990 -> 50, cost 100000);
        budget 500000."""
        budget = create_budget(fiscal_year=2026, total_cents=500000)
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        p1 = create_pole(pole_number="P-W1", install_date="1965-01-01",
                         gis_tag="FEEDER_CRITICAL", joint_use=True,
                         attachment_count_declared=1)
        p2 = create_pole(pole_number="P-W2", install_date="1965-01-01",
                         gis_tag="URBAN", joint_use=True,
                         attachment_count_declared=1)
        p3 = create_pole(pole_number="P-W3", install_date="1990-01-01",
                         gis_tag="URBAN")
        o1 = create_replacement_order(p1["id"], estimated_cost_cents=300000)
        o2 = create_replacement_order(p2["id"], estimated_cost_cents=200000)
        o3 = create_replacement_order(p3["id"], estimated_cost_cents=100000)
        return budget, cycle, o1, o2, o3

    def test_waterfall_candidate_priority_scores(self, api, program_manager_headers):
        """PRD §3.8: "Its composition is fixed and evaluated in a pinned order: start
        with a deficiency of 100 minus the pole's `current_remaining_strength_pct`,
        where a null strength counts as 50.00; add a deferral term of 5 points per
        deferral; add 10 points when the pole's `joint_use` flag is true; add 5 points
        when the pole's installation year is 1969 or earlier. That raw sum is then
        subject to the criticality floor — when the pole's `gis_tag` is
        `FEEDER_CRITICAL`, the sum is raised to at least 80 — and finally the score is
        capped at 100."

        Design: Difficulty/combinatorial_formula/waterfall_pinned_eval_order_exact_fit
        """
        _, _, o1, o2, o3 = self._setup_waterfall(api)
        # All strengths null -> deficiency 50 each.
        assert o1["priority_score"] == 80, "raw 65 floored to 80 (FEEDER_CRITICAL)"
        assert o2["priority_score"] == 65, "50 + joint_use 10 + age 5"
        assert o3["priority_score"] == 50, "deficiency only"

    def test_waterfall_funds_in_priority_order_with_skip(
            self, api, program_manager_headers):
        """PRD §3.9: "then rank all candidates by `priority_score` descending, breaking
        ties by `created_at` ascending; then walk the ranking, funding each order whose
        `escalated_cost_cents` is less than or equal to the remaining snapshot —
        funding moves the order to `FUNDED`, adds the cost to `committed_cents`,
        subtracts it from the remaining amount, and sets the order's `budget_id` —
        while an order whose cost exceeds the remainder is left `QUEUED` and the walk
        continues to lower-ranked orders rather than stopping."
        PRD §3.9: "As with manual funding, the boundary is inclusive: an order whose
        escalated cost exactly equals the remaining funds is funded."

        Design: Difficulty/combinatorial_formula/waterfall_pinned_eval_order_exact_fit
        """
        budget, cycle, o1, o2, o3 = self._setup_waterfall(api)
        reconcile_cycle(cycle["id"], budget["id"])
        assert get_order(o1["id"])["status"] == "FUNDED", "priority 80 funds first"
        assert get_order(o2["id"])["status"] == "FUNDED", (
            "cost 200000 equals the remaining 200000 — inclusive boundary funds"
        )
        assert get_order(o3["id"])["status"] == "QUEUED", (
            "unaffordable order is skipped and left QUEUED"
        )

    def test_waterfall_budget_and_snapshot_figures(self, api, program_manager_headers):
        """PRD §3.9: "Step five writes the permanent record: a `BacklogSnapshot` whose
        `snapshot_seq` is a per-cycle monotonically increasing sequence starting at
        one, recording the reconciled `cycle_id`, the `budget_id` used for the
        waterfall, the `queued_count` of orders still `QUEUED` after the waterfall,
        their combined `queued_escalated_cost_cents`, the `funded_count` of orders this
        reconcile moved from `QUEUED` to `FUNDED`, the budget's post-waterfall
        `budget_available_cents` and `budget_committed_cents`, and the `crew_billings`
        array of per-crew objects pairing each `crew_id` with its `billing_cents`."

        Design: Difficulty/combinatorial_formula/waterfall_pinned_eval_order_exact_fit
        """
        budget, cycle, o1, o2, o3 = self._setup_waterfall(api)
        reconcile_cycle(cycle["id"], budget["id"])
        after = get_budget(budget["id"])
        assert after["committed_cents"] == 500000
        assert after["available_cents"] == 0
        assert_budget_invariant(after)

        snapshots = get_snapshots_for_cycle(cycle["id"])
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert_backlog_snapshot(snap)
        assert snap["snapshot_seq"] == 1
        assert snap["funded_count"] == 2
        assert snap["queued_count"] == 1
        assert snap["queued_escalated_cost_cents"] == 100000
        assert snap["budget_available_cents"] == 0
        assert snap["budget_committed_cents"] == 500000
        assert snap["budget_id"] == budget["id"]


class TestProductionBilling:
    def _setup_billing(self, api):
        """Crew with three VERIFIED orders: CCA_WRAP x SOUTHERN_PINE,
        PENTA_GEL x DOUGLAS_FIR, COPPER_NAPHTHENATE x WESTERN_RED_CEDAR.
        The clock advances one day before reconcile so the applications fall strictly
        before the reconcile instant (PRD §3.9 in-scope window)."""
        budget = create_budget(fiscal_year=2026, total_cents=10000000)
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0,
                                  strength_variant_policy="CONSERVATIVE")
        crew = create_crew(crew_code="CR-B")
        p1 = create_pole(pole_number="P-B1", species="SOUTHERN_PINE")
        p2 = create_pole(pole_number="P-B2", species="DOUGLAS_FIR", gis_lat=45.1,
                         gis_lon=-122.1)
        p3 = create_pole(pole_number="P-B3", species="WESTERN_RED_CEDAR", gis_lat=45.2,
                         gis_lon=-122.2)
        create_verified_treatment(p1["id"], crew["id"], product_code="CCA_WRAP",
                                  cost_cents=17500, work_start_date="2026-08-10",
                                  work_end_date="2026-08-12")
        create_verified_treatment(p2["id"], crew["id"], product_code="PENTA_GEL",
                                  cost_cents=21000, work_start_date="2026-08-12",
                                  work_end_date="2026-08-15")
        create_verified_treatment(p3["id"], crew["id"],
                                  product_code="COPPER_NAPHTHENATE", cost_cents=14500,
                                  work_start_date="2026-08-15",
                                  work_end_date="2026-08-18")
        return budget, cycle, crew

    def test_production_billing_per_line_rounding_total(
            self, api, program_manager_headers):
        """PRD §3.9: "Each in-scope order contributes a line amount built from two
        separately rounded components: the product's base rate — 17,500 cents for
        `CCA_WRAP`, 21,000 for `PENTA_GEL`, 14,500 for `COPPER_NAPHTHENATE` —
        multiplied by the treated pole's species multiplier — 1.00 for
        `SOUTHERN_PINE`, 1.15 for `DOUGLAS_FIR`, 0.90 for `WESTERN_RED_CEDAR`, 1.05 for
        `LARCH` — rounded half-up to whole cents; plus the order's even share of the
        40,000-cent mobilization allowance, that is 40,000 divided by the crew's
        in-scope order count, rounded half-up to whole cents. The rounding order is
        pinned and contractual: each line component is rounded per order first, and
        only then are the lines summed into the crew's subtotal — summing first and
        rounding once yields a different cents total and is non-conformant."

        Design: Difficulty/combinatorial_formula/production_billing_per_line_rounding
        """
        budget, cycle, crew = self._setup_billing(api)
        set_clock("2026-08-02T00:00:00Z")
        reconcile_cycle(cycle["id"], budget["id"])
        read = get_crew(crew["id"])
        # lines: 17500+13333=30833, 24150+13333=37483, 13050+13333=26383
        # subtotal 94699; bonus round_half_up(94699*0.05)=4735 (in-season, lifetime 100);
        # penalty 0 -> 99434. Sum-then-round would give 99435.
        assert read["current_cycle_billing_cents"] == 99434, (
            f"per-line rounding pins 99434, got {read['current_cycle_billing_cents']}"
        )

    def test_production_billing_snapshot_crew_billings(
            self, api, program_manager_headers):
        """PRD §3.9: "the result, floored at zero, is the crew's `billing_cents`,
        stored on `current_cycle_billing_cents`" and the snapshot carries "the
        `crew_billings` array of per-crew objects pairing each `crew_id` with its
        `billing_cents`."
        PRD §3.9: "when every in-scope order reached `VERIFIED` no later than 120 days
        after the cycle opened, and the crew's lifetime quality score is at least
        90.00, an early-completion bonus of five percent of the subtotal, rounded
        half-up to whole cents, is added".

        Design: Difficulty/combinatorial_formula/production_billing_per_line_rounding
        """
        budget, cycle, crew = self._setup_billing(api)
        set_clock("2026-08-02T00:00:00Z")
        reconcile_cycle(cycle["id"], budget["id"])
        snapshots = get_snapshots_for_cycle(cycle["id"])
        assert len(snapshots) == 1
        billings = snapshots[0]["crew_billings"]
        assert len(billings) == 1
        assert billings[0]["crew_id"] == crew["id"]
        assert billings[0]["billing_cents"] == 99434


class TestSnapshotImmutability:
    def test_snapshot_is_immutable_without_version(self, api, program_manager_headers):
        """PRD §2.4: "The `BacklogSnapshot` resource is the single exception: it
        carries `id` and `created_at` only. Both `updated_at` and `version` are absent
        on snapshots, because a snapshot is an immutable record written once at
        reconcile time and never modified thereafter."
        PRD §3.9: "a `BacklogSnapshot` whose `snapshot_seq` is a per-cycle
        monotonically increasing sequence starting at one".

        Design: Corner/entities/snapshot_is_immutable_without_version
        """
        budget = create_budget(fiscal_year=2026, total_cents=1000)
        cycle = create_open_cycle(year=2026, cycle_length_years=10, sample_pct=0)
        reconcile_cycle(cycle["id"], budget["id"])
        snapshots = get_snapshots_for_cycle(cycle["id"])
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert_backlog_snapshot(snap)
        assert snap["snapshot_seq"] == 1
        assert snap["queued_count"] == 0
        assert snap["funded_count"] == 0
        assert snap["budget_available_cents"] == 1000
        assert snap["budget_committed_cents"] == 0

        by_id = validate_success(
            api.get_backlog_snapshot(snap["id"], program_manager_headers)
        )
        assert_backlog_snapshot(by_id)
        assert by_id["snapshot_seq"] == 1
