"""Repair authorizations: responsibility split branches, preauthorization
gate, revision loop, and the railcar shop cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_repair,
    close_open_damage_assessments,
    create_railcar,
    create_repair,
    deliver_assignment,
    get_assignment,
    get_railcar,
    get_success_data,
    make_lessee_rep_headers,
    preauthorize_repair,
    return_assignment,
    setup_active_lease_scenario,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["fleet_planner_headers"]
MAINT = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


class TestResponsibilitySplit:
    def test_full_service_wear_split_uses_allowance(self, api):
        """PRD §3.9: "Otherwise — a `FULL_SERVICE` lease with ordinary
        `WEAR_AND_TEAR` — the lessee bears a share of the excess over a wear
        allowance of 25,000 cents: the excess is the amount by which the cost
        exceeds 25,000, floored at zero, and the lessee's share is 40 percent
        of that excess, rounded half-up to a whole cent."
        PRD §3.9: "The flag `lessee_preauth_required` is true exactly when a
        `lease_assignment_id` is present and `lessee_share_cents` exceeds the
        lease's `authorized_repair_cap_cents`."

        Design: Difficulty/combinatorial_formula/repair_split_three_way_branching
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX4001", lease_type="FULL_SERVICE",
            repair_cap_cents=20000, window_start="2026-08-01",
            window_end="2026-12-31",
        )
        repair = create_repair(
            scenario["railcar"]["id"],
            assignment_id=scenario["assignment"]["id"],
            defect_cause="WEAR_AND_TEAR", estimate_cents=100000,
            requires_shop=False, defect_description="worn brake shoes",
        )
        # round_half_up(0.40 x max(0, 100000 - 25000)) = 30000.
        assert repair["lessee_share_cents"] == 30000
        assert repair["lessor_share_cents"] == 70000
        assert repair["lessee_preauth_required"] is True, (
            "30000 exceeds the 20000 cap"
        )

    def test_net_lease_shifts_full_cost_to_lessee(self, api):
        """PRD §3.9: "Otherwise, if the lease behind the linked assignment is
        a `NET` lease, the lessee bears the entire cost."
        PRD §3.9: "The flag `lessee_preauth_required` is true exactly when a
        `lease_assignment_id` is present and `lessee_share_cents` exceeds the
        lease's `authorized_repair_cap_cents`."

        Design: Difficulty/combinatorial_formula/repair_split_three_way_branching
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX4002", lease_type="NET", repair_cap_cents=200000,
            window_start="2026-08-01", window_end="2026-12-31",
        )
        repair = create_repair(
            scenario["railcar"]["id"],
            assignment_id=scenario["assignment"]["id"],
            defect_cause="WEAR_AND_TEAR", estimate_cents=100000,
            requires_shop=False, defect_description="worn brake shoes",
        )
        assert repair["lessee_share_cents"] == 100000
        assert repair["lessor_share_cents"] == 0
        assert repair["lessee_preauth_required"] is False, (
            "100000 does not exceed the 200000 cap"
        )


class TestRevisionCycle:
    def _setup_revision(self, api):
        scenario = setup_active_lease_scenario(
            car_mark="GATX7002", lease_type="NET", repair_cap_cents=50000,
            window_start="2026-08-01", window_end="2026-12-31",
        )
        repair = create_repair(
            scenario["railcar"]["id"],
            assignment_id=scenario["assignment"]["id"],
            defect_cause="WEAR_AND_TEAR", estimate_cents=100000,
            requires_shop=False, defect_description="roof leak",
        )
        # NET lease: lessee share is the full 100000, above the 50000 cap.
        assert repair["lessee_preauth_required"] is True
        preauthorize_repair(repair["id"], scenario["lessee"]["id"])
        return scenario, repair

    def test_revision_recomputes_split_and_resets_preauthorization(self, api):
        """PRD §3.9: "A revision (`REVISION_REQUESTED → UNDER_REVIEW`)
        supplies a fresh positive `estimate_cents` (`ERR_VALIDATION`, 400),
        replaces the estimate, increments `revision_count` by one, recomputes
        the split and the preauthorization flag, and resets
        `lessee_preauthorized` to false — a materially changed estimate voids
        the earlier consent."

        Design: Difficulty/non_linear_state_machine/repair_revision_cycle_resets_preauthorization
        """
        scenario, repair = self._setup_revision(api)
        get_success_data(
            api.request_repair_revision(repair["id"], "too expensive", MAINT)
        )
        revised = validate_success(api.revise_repair(repair["id"], 40000, MAINT))
        assert revised["status"] == "UNDER_REVIEW"
        assert revised["revision_count"] == 1
        # NET lease: the lessee still bears the entire (new) cost.
        assert revised["lessee_share_cents"] == 40000
        assert revised["lessee_preauth_required"] is False, (
            "40000 no longer exceeds the 50000 cap"
        )
        assert revised["lessee_preauthorized"] is False, (
            "The earlier preauthorization was voided by the revise"
        )

    def test_approve_after_revision_succeeds_without_preauthorization(self, api):
        """PRD §3.9: "If `lessee_preauth_required` is set, approval is
        blocked until a `LesseeRep` of the owning lessee has pre-authorized
        the repair, which sets `lessee_preauthorized` true; approving without
        it fails with `ERR_REPAIR_PREAUTH_REQUIRED` (422)." — after the
        revise drops the share below the cap the flag clears, so approval
        proceeds.

        Design: Difficulty/non_linear_state_machine/repair_revision_cycle_resets_preauthorization
        """
        scenario, repair = self._setup_revision(api)
        get_success_data(
            api.request_repair_revision(repair["id"], "too expensive", MAINT)
        )
        get_success_data(api.revise_repair(repair["id"], 40000, MAINT))
        approved = validate_success(api.approve_repair(repair["id"], 40000, MAINT))
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 40000


class TestShopCycle:
    def test_start_work_shops_car_and_saves_prior_status(self, api):
        """PRD §3.2: "From either `AVAILABLE` or `ON_LEASE`, starting work on
        an approved shop repair moves the car to `IN_SHOP`; the prior status
        is saved in `status_before_shop`, and `open_shop_repair_count`
        increments by one."

        Design: Difficulty/non_linear_state_machine/railcar_shop_cycle_restores_prior_status
        """
        car = create_railcar(car_mark="GATX7001", car_type="BOX",
                             built_year=2018)
        repair = create_repair(car["id"], defect_cause="PRE_EXISTING",
                               estimate_cents=80000, requires_shop=True,
                               defect_description="door track")
        approve_repair(repair["id"], 80000)
        get_success_data(api.start_repair_work(repair["id"], MAINT))
        after = get_railcar(car["id"])
        assert after["status"] == "IN_SHOP"
        assert after["status_before_shop"] == "AVAILABLE"
        assert after["open_shop_repair_count"] == 1

    def test_completing_last_shop_repair_restores_saved_status(self, api):
        """PRD §3.2: "When a shop repair completes, the count decrements by
        one, and only when it reaches zero does the car leave the shop —
        restored to whatever `status_before_shop` held (`AVAILABLE` or
        `ON_LEASE`), with `status_before_shop` cleared to null."
        PRD §3.9: "Otherwise, if the cause is `PRE_EXISTING`, the lessee
        bears nothing." (and "(A repair with no linked assignment is treated
        as `FULL_SERVICE`.)")

        Design: Difficulty/non_linear_state_machine/railcar_shop_cycle_restores_prior_status
        """
        car = create_railcar(car_mark="GATX7001", car_type="BOX",
                             built_year=2018)
        repair = create_repair(car["id"], defect_cause="PRE_EXISTING",
                               estimate_cents=80000, requires_shop=True,
                               defect_description="door track")
        approve_repair(repair["id"], 80000)
        get_success_data(api.start_repair_work(repair["id"], MAINT))
        completed = validate_success(
            api.complete_repair(repair["id"], 80000, MAINT)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["lessee_share_cents"] == 0
        after = get_railcar(car["id"])
        assert after["status"] == "AVAILABLE"
        assert after["status_before_shop"] is None
        assert after["open_shop_repair_count"] == 0

    def test_second_shop_repair_keeps_car_in_shop(self, api):
        """PRD §3.2: "Two overlapping shop repairs therefore keep the car
        `IN_SHOP` until both complete."

        Design: Corner/state_machines/repair_complete_second_shop_repair_keeps_car_in_shop
        """
        car = create_railcar(car_mark="GATX1208", car_type="BOX",
                             built_year=2018)
        repair_ids = []
        for desc, cost in (("door", 50000), ("floor", 60000)):
            repair = create_repair(car["id"], defect_cause="PRE_EXISTING",
                                   estimate_cents=cost, requires_shop=True,
                                   defect_description=desc)
            approve_repair(repair["id"], cost)
            get_success_data(api.start_repair_work(repair["id"], MAINT))
            repair_ids.append(repair["id"])
        get_success_data(api.complete_repair(repair_ids[0], 50000, MAINT))
        mid = get_railcar(car["id"])
        assert mid["status"] == "IN_SHOP", "One shop repair is still open"
        assert mid["open_shop_repair_count"] == 1
        get_success_data(api.complete_repair(repair_ids[1], 60000, MAINT))
        after = get_railcar(car["id"])
        assert after["status"] == "AVAILABLE"
        assert after["open_shop_repair_count"] == 0
        assert after["status_before_shop"] is None


class TestPreauthorizationGate:
    def test_approve_over_cap_without_preauth_rejected(self, api):
        """PRD §3.9: "If `lessee_preauth_required` is set, approval is
        blocked until a `LesseeRep` of the owning lessee has pre-authorized
        the repair, which sets `lessee_preauthorized` true; approving without
        it fails with `ERR_REPAIR_PREAUTH_REQUIRED` (422)."

        Design: Corner/validations/approve_repair_over_cap_without_preauth_rejected
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1409", lease_type="NET", repair_cap_cents=50000,
            window_start="2026-08-01", window_end="2026-12-31",
        )
        repair = create_repair(
            scenario["railcar"]["id"],
            assignment_id=scenario["assignment"]["id"],
            defect_cause="WEAR_AND_TEAR", estimate_cents=100000,
            requires_shop=False, defect_description="slope sheet",
        )
        # NET lease: share is the full 100000, above the 50000 cap.
        assert repair["lessee_preauth_required"] is True
        resp = api.approve_repair(repair["id"], 100000, MAINT)
        validate_error(resp, ApiErrorId.ERR_REPAIR_PREAUTH_REQUIRED, 422)

        preauthorize_repair(repair["id"], scenario["lessee"]["id"])
        approved = validate_success(api.approve_repair(repair["id"], 100000, MAINT))
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 100000


class TestSettleRepairGate:
    def test_settle_with_open_repair_returns_open_repair_orders(self, api):
        """PRD §2.7: "Settling an assignment requires the assignment to be
        `RETURNED` (`ERR_ASSIGNMENT_NOT_RETURNED`), no repair authorization
        on the assignment in `UNDER_REVIEW`, `REVISION_REQUESTED`,
        `APPROVED`, or `IN_PROGRESS` (`ERR_OPEN_REPAIR_ORDERS`), and every
        damage assessment on the assignment in `FINALIZED`, `INVOICED`, or
        `PAID` (`ERR_DAMAGE_ASSESSMENT_OPEN`)."

        Design: Corner/errors/settle_with_open_repair_returns_open_repair_orders
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1602", repair_cap_cents=100000,
            window_start="2026-08-01", window_end="2026-08-31",
            deliver=True,
        )
        create_repair(
            scenario["railcar"]["id"],
            assignment_id=scenario["assignment"]["id"],
            defect_cause="WEAR_AND_TEAR", estimate_cents=30000,
            requires_shop=False, defect_description="hatch",
        )
        return_assignment(scenario["assignment"]["id"])
        # Close the cascade-created DRAFT damage assessment (§3.4/§3.6) so the
        # repair gate is the only open settle precondition.
        close_open_damage_assessments(scenario["assignment"]["id"])
        resp = api.settle_assignment(scenario["assignment"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_OPEN_REPAIR_ORDERS, 409)
        after = get_assignment(scenario["assignment"]["id"])
        assert after["status"] == "RETURNED"
