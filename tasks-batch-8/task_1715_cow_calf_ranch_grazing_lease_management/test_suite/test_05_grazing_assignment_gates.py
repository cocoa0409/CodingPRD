"""Grazing assignment creation gates: lease coverage, drought gates, pasture
condition vs budget precedence, and the inclusive AUM budget boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_lease,
    assert_aum,
    assert_pasture_ledger_invariant,
    complete_assignment,
    create_and_activate_lease,
    create_assignment,
    create_drought_assessment,
    create_herd_group,
    create_lease,
    create_pasture,
    create_ranch,
    finalize_assessment,
    get_herd_group,
    get_pasture,
    get_ranch,
    get_success_data,
    list_destock_orders,
    validate_error,
    validate_success,
)

RANCH_MGR = TEST_USERS["ranch_manager_headers"]
RANGE_MGR = TEST_USERS["range_manager_headers"]


class TestCoveringLeaseGate:
    def _setup(self, api):
        ranch = create_ranch(name="Gate Ranch", hq_state="OR")
        pasture = create_pasture(ranch["id"], name="Leased Bench", acreage=800,
                                 tenure="LEASED", base_capacity_aum=200)
        lease = create_lease(ranch["id"], pasture["id"], lessor_name="Taylor",
                             aum_allotment=200, rate_per_aum_cents=2400,
                             overage_tier1_cap_aum=30,
                             overage_tier1_rate_cents=2800,
                             overage_tier2_rate_cents=3500)
        group = create_herd_group(ranch["id"], group_name="Cows", head_count=10,
                                  avg_weight_lbs=1000)
        return ranch, pasture, lease, group

    def test_draft_lease_blocks_assignment_then_active_admits(self, api):
        """PRD §3.9: "When the pasture's tenure is `LEASED`, at least one
        `ACTIVE` lease must cover it — deeded ground carries no lease
        requirement — and the absence of any active covering lease fails with
        `ERR_LEASE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_covering_lease
        """
        ranch, pasture, lease, group = self._setup(api)
        # Lease still DRAFT — no ACTIVE covering lease exists.
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": group["id"],
             "ranch_id": ranch["id"], "start_date": "2026-06-01",
             "planned_end_date": "2026-06-30"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)

        activate_lease(lease["id"])
        asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                                start_date="2026-06-01",
                                planned_end_date="2026-07-01")
        assert asg["assignment_status"] == "ACTIVE"
        assert_aum(asg["reserved_aum"], 10.0, "10 head x 1.0 AU x 30d / 30")

    def test_suspended_lease_blocks_assignment_again(self, api):
        """PRD §3.9: "When the pasture's tenure is `LEASED`, at least one
        `ACTIVE` lease must cover it — deeded ground carries no lease
        requirement — and the absence of any active covering lease fails with
        `ERR_LEASE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_covering_lease
        """
        ranch, pasture, lease, group = self._setup(api)
        activate_lease(lease["id"])
        create_assignment(pasture["id"], group["id"], ranch["id"],
                          start_date="2026-06-01", planned_end_date="2026-07-01")
        validate_success(api.suspend_lease(lease["id"], RANGE_MGR))
        # SUSPENDED is not ACTIVE — the cycle-sensitive gate closes again.
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": group["id"],
             "ranch_id": ranch["id"], "start_date": "2026-08-01",
             "planned_end_date": "2026-08-31"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)


class TestDroughtPostureGate:
    def _setup_alert_ranch(self, api):
        """Ranch finalized ALERT with a negative deficit (no destock order)."""
        ranch = create_ranch(name="Alert Ranch", hq_state="WY")
        p1 = create_pasture(ranch["id"], name="N", acreage=1500,
                            base_capacity_aum=300)
        p2 = create_pasture(ranch["id"], name="S", acreage=1000,
                            base_capacity_aum=200)
        group = create_herd_group(ranch["id"], group_name="Stockers",
                                  animal_class="GROWING", head_count=30,
                                  avg_weight_lbs=800)
        assessment = create_drought_assessment(
            ranch["id"], "2026-08-01",
            [{"pasture_id": p1["id"], "production_pct_of_normal": 70},
             {"pasture_id": p2["id"], "production_pct_of_normal": 70}])
        finalize_assessment(assessment["id"], ranch["version"])
        return ranch, p1, group, assessment

    def test_alert_posture_blocks_new_assignment(self, api):
        """PRD §2.11: "Second, it gates new grazing commitments: while the
        ranch's posture is `ALERT` or `CRITICAL`, any attempt to create a
        grazing assignment is rejected with
        `ERR_DROUGHT_POSTURE_BLOCKS_COMMITMENT` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/assignment_blocked_by_drought_posture
        """
        ranch, p1, group, _a = self._setup_alert_ranch(api)
        assert get_ranch(ranch["id"])["drought_posture"] == "ALERT"
        # No destock order exists (deficit < 0), so the posture gate surfaces.
        resp = api.create_grazing_assignment(
            {"pasture_id": p1["id"], "herd_group_id": group["id"],
             "ranch_id": ranch["id"], "start_date": "2026-08-05",
             "planned_end_date": "2026-09-04"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_DROUGHT_POSTURE_BLOCKS_COMMITMENT,
                       expected_status=422)

    def test_alert_assessment_figures_and_no_destock_order(self, api):
        """PRD §3.8: "The `resulting_posture` maps that percentage onto the four
        postures: 90 or higher yields `NORMAL`, at least 75 but below 90 yields
        `WATCH`, at least 55 but below 75 yields `ALERT`, and below 55 yields
        `CRITICAL`."
        PRD §3.8: "When the finalized `deficit_aum_per_30d` is strictly greater
        than zero — whatever posture resulted — finalization also creates a
        destock order whose `order_status` opens at `OPEN`"

        Design: Difficulty/cross_entity_state_dependency/assignment_blocked_by_drought_posture
        """
        ranch, _p1, _g, assessment = self._setup_alert_ranch(api)
        from test_helpers import assert_pct1
        data = get_success_data(api.get_drought_assessment(assessment["id"],
                                                           RANGE_MGR))
        assert data["resulting_posture"] == "ALERT", "70.0 is below 75"
        assert_pct1(data["ranch_production_pct"], 70.0)
        assert_aum(data["deficit_aum_per_30d"], -47.5, "22.5 demand - 70.0 supply")
        assert_aum(data["monthly_supply_aum"], 70.0, "500 x 0.70 / 5")
        assert_aum(data["monthly_demand_aum"], 22.5, "30 GROWING @800 x 0.75")
        orders, meta = list_destock_orders(ranch["id"])
        assert meta["total_count"] == 0, "a negative deficit creates no order"
        assert orders == []


class TestClosedPastureBeatsBudget:
    def _setup(self, api):
        """Pasture (base 50) with 40.0 AUM consumed, then CLOSED; a second
        group whose 60-day demand (63.6) would also blow the 10.0 budget."""
        ranch = create_ranch(name="Prio Ranch", hq_state="MT")
        pasture = create_pasture(ranch["id"], name="Trap", acreage=300,
                                 base_capacity_aum=50, min_rest_days=45)
        g1 = create_herd_group(ranch["id"], group_name="Cows A", head_count=20,
                               avg_weight_lbs=1000)
        a1 = create_assignment(pasture["id"], g1["id"], ranch["id"],
                               start_date="2026-05-01",
                               planned_end_date="2026-06-30")
        complete_assignment(a1["id"], "2026-06-30")  # consumed 40.0
        validate_success(api.close_pasture(pasture["id"], RANGE_MGR))
        g2 = create_herd_group(ranch["id"], group_name="Cows B", head_count=30,
                               avg_weight_lbs=1200)
        return ranch, pasture, g1, g2

    def test_closed_pasture_state_error_wins_over_budget(self, api):
        """PRD §2.8: "Every request is validated against an ordered cascade, and
        the first failing check determines the returned error — later checks are
        never evaluated once an earlier one has failed."
        PRD §2.9: "Only `CLOSED` blocks creation, with
        `ERR_PASTURE_NOT_GRAZEABLE`."

        Design: Difficulty/priority_pair_validation_conflict/resting_closed_pasture_vs_budget_state_wins
        """
        ranch, pasture, _g1, g2 = self._setup(api)
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": g2["id"],
             "ranch_id": ranch["id"], "start_date": "2026-09-01",
             "planned_end_date": "2026-10-31"}, RANGE_MGR)
        # reserved 63.6 > available 10.0 also fails, but the state gate is
        # earlier in the cascade and owns the error.
        validate_error(resp, ApiErrorId.ERR_PASTURE_NOT_GRAZEABLE)
        after = get_pasture(pasture["id"])
        assert after["condition_status"] == "CLOSED"
        assert_aum(after["committed_aum"], 0.0, "no side effects leaked")

    def test_closed_pasture_rejects_even_within_budget(self, api):
        """PRD §3.9: "The pasture must not be `CLOSED`, or the create fails with
        `ERR_PASTURE_NOT_GRAZEABLE`; recall from §2.9 that a `RESTING` pasture
        does not fail this gate, because rest is enforced by the buffer rule
        below rather than by the status itself."

        Design: Difficulty/priority_pair_validation_conflict/resting_closed_pasture_vs_budget_state_wins
        """
        ranch, pasture, g1, _g2 = self._setup(api)
        # A 9-day stay needing 6.0 AUM fits the 10.0 remaining — the state
        # gate alone produces the rejection.
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": g1["id"],
             "ranch_id": ranch["id"], "start_date": "2026-09-01",
             "planned_end_date": "2026-09-10"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_PASTURE_NOT_GRAZEABLE)


class TestAumBudgetBoundary:
    def _setup(self, api):
        """Pasture (base 100) with exactly 60.0 committed, leaving 40.00."""
        ranch = create_ranch(name="Edge Ranch", hq_state="MT")
        pasture = create_pasture(ranch["id"], name="Exact", acreage=500,
                                 base_capacity_aum=100, min_rest_days=45)
        ga = create_herd_group(ranch["id"], group_name="A", head_count=30,
                               avg_weight_lbs=1000)
        gb = create_herd_group(ranch["id"], group_name="B", head_count=20,
                               avg_weight_lbs=1001)
        gc = create_herd_group(ranch["id"], group_name="C", head_count=20,
                               avg_weight_lbs=1000)
        create_assignment(pasture["id"], ga["id"], ranch["id"],
                          start_date="2026-06-01", planned_end_date="2026-07-31")
        return ranch, pasture, gb, gc

    def test_demand_just_over_available_rejected(self, api):
        """PRD §2.9: "A new grazing reservation is permitted whenever its
        reserved amount is less than or equal to `available_aum` — an exact fit
        is allowed — and is refused with `ERR_AUM_BUDGET_EXCEEDED` only when the
        reservation strictly exceeds what remains."

        Design: Difficulty/boundary_precision_check/aum_budget_exact_equality_boundary
        """
        ranch, pasture, gb, _gc = self._setup(api)
        # 20 cows @1001 lbs factor 1.0003 -> 40.01 AUM against 40.00 available.
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": gb["id"],
             "ranch_id": ranch["id"], "start_date": "2026-09-15",
             "planned_end_date": "2026-11-14"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_AUM_BUDGET_EXCEEDED,
                       expected_status=422)

    def test_demand_exactly_equal_available_admitted(self, api):
        """PRD §2.9: "A new grazing reservation is permitted whenever its
        reserved amount is less than or equal to `available_aum` — an exact fit
        is allowed — and is refused with `ERR_AUM_BUDGET_EXCEEDED` only when the
        reservation strictly exceeds what remains."

        Design: Difficulty/boundary_precision_check/aum_budget_exact_equality_boundary
        """
        ranch, pasture, _gb, gc = self._setup(api)
        asg = create_assignment(pasture["id"], gc["id"], ranch["id"],
                                start_date="2026-09-15",
                                planned_end_date="2026-11-14")
        assert_aum(asg["reserved_aum"], 40.0, "20 x 1.0000 x 60 / 30")
        after = get_pasture(pasture["id"])
        assert_aum(after["committed_aum"], 100.0)
        assert_aum(after["available_aum"], 0.0, "exact fit drains the budget")
        assert_pasture_ledger_invariant(after)


class TestLeaseWindowNesting:
    def test_assignment_outside_lease_window_rejected(self, api):
        """PRD §3.9: "Window nesting follows for leased ground: when an `ACTIVE`
        covering lease exists but the assignment's window from `start_date` to
        `planned_end_date` does not lie within the lease's inclusive window from
        its `start_date` to its `end_date`, the create is rejected with
        `ERR_ASSIGNMENT_OUTSIDE_LEASE_WINDOW` (HTTP 422)."

        Design: Corner/validations/assignment_outside_lease_window_rejected
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=1600,
                                 tenure="LEASED", base_capacity_aum=500)
        # The covering lease must still be ACTIVE at the attempt: its window
        # straddles the startup clock (2026-08-01, PRD §2.4) so the priority-14
        # nesting gate is what fires, not the priority-8 lease-status gate.
        create_and_activate_lease(ranch["id"], pasture["id"], aum_allotment=500,
                                  start_date="2026-01-01", end_date="2026-12-31")
        group = create_herd_group(ranch["id"], group_name="G", head_count=10,
                                  avg_weight_lbs=1000)
        resp = api.create_grazing_assignment(
            {"pasture_id": pasture["id"], "herd_group_id": group["id"],
             "ranch_id": ranch["id"], "start_date": "2026-06-01",
             "planned_end_date": "2027-02-01"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_LEASE_WINDOW,
                       expected_status=422)


class TestImmediateConsistency:
    def test_committed_visible_on_next_read(self, api):
        """PRD §3.9: "The assignment is `ACTIVE` from the moment of creation,
        and its `reserved_aum` is immediately added into the pasture's
        `committed_aum`."
        PRD §2.9: "`committed_aum` is the sum of `reserved_aum` over the
        pasture's assignments whose `assignment_status` is `ACTIVE`"

        Design: Corner/consistency_model/immediate_consistency_after_assignment_create
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=900,
                                 base_capacity_aum=200)
        group = create_herd_group(ranch["id"], group_name="G", head_count=20,
                                  avg_weight_lbs=1000)
        asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                                start_date="2026-06-01",
                                planned_end_date="2026-07-31")
        assert asg["assignment_status"] == "ACTIVE"
        assert_aum(asg["reserved_aum"], 40.0, "20 x 1.0 x 60 / 30")
        after = get_pasture(pasture["id"])
        assert_aum(after["committed_aum"], 40.0)
        assert_aum(after["available_aum"], 160.0)
