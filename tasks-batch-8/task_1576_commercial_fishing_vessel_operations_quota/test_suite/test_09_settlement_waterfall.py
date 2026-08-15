"""Trip settlement: provisional vs final variants, pinned waterfall order,
crew pool floor-then-remainder split, state gates, OCC recalculation, and
segregation of duties (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    add_crew_contract,
    add_expense,
    api_client,
    assert_crew_payouts_sum_to_pool,
    assert_settlement_books_balance,
    create_settlement_payload,
    get_settlement,
    get_trip,
    make_crew_member_headers,
    make_observer_headers,
    make_vessel_owner_headers,
    payout_for,
    setup_executed_trip,
    setup_landing_finalized_trip,
    setup_settlement_calculated,
    setup_settlement_draft,
    setup_trip_with_confirmed_observer,
    validate_error,
    validate_success,
    advance_clock,
    declare_and_submit,
    verify_and_finalize,
    make_captain_headers,
)

REG = TEST_USERS["regulator_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestDualVariantSettlement:
    def test_settlement_provisional_variant_counts_pending_expenses(self):
        """PRD §3.8: "The settlement starts in `DRAFT`, and a **provisional**
        variant of the settlement math runs immediately, counting both `PENDING`
        and `VERIFIED` expenses, populating `provisional_total_expenses_cents`,
        `provisional_processing_fee_cents`, `provisional_vessel_share_cents`, and
        `provisional_crew_pool_cents` so stakeholders see an early estimate before
        adjudication finishes."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
        """
        ctx = setup_settlement_draft(
            gross_revenue_cents=1000000,
            expenses=(("FUEL", 120000, "2026-08-11T00:00:00Z"),
                      ("BAIT", 30000, "2026-08-11T01:00:00Z"),
                      ("OTHER", 20000, "2026-08-11T02:00:00Z")),
            verify_expenses=(0, 1),   # OTHER stays PENDING at creation
            gear_loss_units=2,
            crew=(("Alice", 2, "2026-01-15T00:00:00Z"),
                  ("Bob", 1, "2026-02-01T00:00:00Z")),
        )
        settlement = ctx["settlement"]
        assert settlement["status"] == "DRAFT"
        # Provisional: expenses 120000+30000+20000 = 170000; gear 50000;
        # nbf 780000; fee round_half_up(0.015*780000)=11700; net 768300;
        # vessel round_half_up(0.6*768300)=460980; pool 307320.
        assert settlement["provisional_total_expenses_cents"] == 170000
        assert settlement["provisional_processing_fee_cents"] == 11700
        assert settlement["provisional_vessel_share_cents"] == 460980
        assert settlement["provisional_crew_pool_cents"] == 307320

    def test_settlement_final_variant_counts_verified_only(self):
        """PRD §3.8: "The final variant counts `VERIFIED` expenses only; the
        provisional variant counts `PENDING` and `VERIFIED`." With the PENDING
        expense REJECTED before calculate, the final pool diverges from the
        provisional pool computed on identical trip data.

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
        """
        ctx = setup_settlement_draft(
            gross_revenue_cents=1000000,
            expenses=(("FUEL", 120000, "2026-08-11T00:00:00Z"),
                      ("BAIT", 30000, "2026-08-11T01:00:00Z"),
                      ("OTHER", 20000, "2026-08-11T02:00:00Z")),
            verify_expenses=(0, 1),
            reject_expenses=(),   # rejected after creation, below
            gear_loss_units=2,
            crew=(("Alice", 2, "2026-01-15T00:00:00Z"),
                  ("Bob", 1, "2026-02-01T00:00:00Z")),
        )
        settlement_id = ctx["settlement"]["id"]
        # Adjudicate the last expense AFTER the provisional snapshot.
        validate_success(api_client.reject_expense(ctx["expenses"][2]["id"], CLERK), 200)
        calculated = validate_success(
            api_client.calculate_settlement(settlement_id, CLERK), 200)
        # Final: expenses 150000; gear 50000; nbf 800000; fee 12000;
        # net 788000; vessel 472800; pool 315200.
        assert calculated["total_expenses_cents"] == 150000
        assert calculated["crew_pool_cents"] == 315200
        refreshed = get_settlement(settlement_id)
        assert refreshed["provisional_crew_pool_cents"] == 307320
        assert (refreshed["crew_pool_cents"]
                - refreshed["provisional_crew_pool_cents"]) == 7880, (
            "identical trip data, two variants, different results")


class TestCrewPoolSplit:
    def test_crew_payouts_floor_then_remainder_cent(self):
        """PRD §3.8: "Contracts are then processed in a pinned order —
        `share_points` descending, then `joined_at` ascending, then `created_at`
        ascending — and each contract's raw payout, the crew pool multiplied by
        its points and divided by the total points, is floored to whole cents.
        The remainder — the pool minus the sum of the floored payouts — is
        distributed one cent at a time to contracts in that same order until
        nothing remains."

        Design: Difficulty/combinatorial_formula/crew_pool_split_floors_then_remainder
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            expenses=(("FUEL", 120000, "2026-08-11T00:00:00Z"),
                      ("BAIT", 30000, "2026-08-11T01:00:00Z")),
            verify_expenses=(0, 1),
            gear_loss_units=2,
            crew=(("Alice", 2, "2026-01-15T00:00:00Z"),
                  ("Bob", 1, "2026-02-01T00:00:00Z")),
        )
        settlement = ctx["settlement"]
        assert settlement["crew_pool_cents"] == 315200
        alice, bob = ctx["contracts"]
        # floor(315200*2/3)=210133, floor(315200/3)=105066, remainder 1 -> Alice.
        assert payout_for(settlement, alice["id"]) == 210134
        assert payout_for(settlement, bob["id"]) == 105066
        assert_crew_payouts_sum_to_pool(settlement)

    def test_crew_payouts_remainder_order_by_joined_at(self):
        """PRD §3.8: "The remainder — the pool minus the sum of the floored
        payouts — is distributed one cent at a time to contracts in that same
        order until nothing remains. Each `crew_payouts` entry records the
        `crew_contract_id`, the `crew_name`, and the `payout_cents`, and the
        payouts always sum exactly to `crew_pool_cents`; any sum-then-round
        shortcut yields different per-member cents and is non-conformant."

        Design: Difficulty/combinatorial_formula/crew_pool_split_floors_then_remainder
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),
                  ("Bob", 1, "2026-02-01T00:00:00Z"),
                  ("Carol", 1, "2026-03-01T00:00:00Z")),
        )
        settlement = ctx["settlement"]
        # nbf 1000000; fee 15000; net 985000; vessel 591000; pool 394000.
        assert settlement["crew_pool_cents"] == 394000
        alice, bob, carol = ctx["contracts"]
        # floor(394000/3)=131333 each; remainder 1 -> earliest joined_at.
        assert payout_for(settlement, alice["id"]) == 131334
        assert payout_for(settlement, bob["id"]) == 131333
        assert payout_for(settlement, carol["id"]) == 131333
        assert_crew_payouts_sum_to_pool(settlement)


class TestWaterfallOrder:
    def test_processing_fee_computed_on_net_before_fee(self):
        """PRD §3.8 pins the evaluation order: "5. **Processing fee** — 1.5 percent
        of the net before fee, rounded half-up to whole cents. 6. **Net** — the
        net before fee minus the processing fee. 7. **Vessel share** — 60 percent
        of the net, rounded half-up to whole cents. 8. **Crew pool** — the net
        minus the vessel share."

        Design: Difficulty/combinatorial_formula/settlement_fee_breaks_circular_dependency
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            expenses=(("FUEL", 120000, "2026-08-11T00:00:00Z"),
                      ("BAIT", 30000, "2026-08-11T01:00:00Z")),
            verify_expenses=(0, 1),
            gear_loss_units=2,
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
        )
        settlement = ctx["settlement"]
        # nbf = 1000000 - 150000 - 0 - 50000 = 800000.
        assert settlement["observer_fee_cents"] == 0
        assert settlement["gear_loss_charge_cents"] == 50000
        assert settlement["processing_fee_cents"] == 12000, (
            "fee is 1.5% of net_before_fee (800000), not of net (788000)")
        assert settlement["net_cents"] == 788000
        assert settlement["vessel_share_cents"] == 472800
        assert settlement["crew_pool_cents"] == 315200
        assert_settlement_books_balance(settlement)

    def test_processing_fee_rounds_half_up(self):
        """PRD §2.8: "Percentage-derived money is rounded half-up to whole cents at
        exactly the steps named in §3 — the settlement processing fee, the vessel
        share, each transfer-fee tier component, and the landing discrepancy
        tolerance — and nowhere else."

        Design: Difficulty/combinatorial_formula/settlement_fee_breaks_circular_dependency
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=100100,
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
        )
        settlement = ctx["settlement"]
        # 1.5% of 100100 = 1501.5 -> 1502 (half-up; a floor would give 1501).
        assert settlement["processing_fee_cents"] == 1502
        assert settlement["net_cents"] == 98598
        assert settlement["vessel_share_cents"] == 59159
        assert settlement["crew_pool_cents"] == 39439
        assert_settlement_books_balance(settlement)


class TestMoneyConservation:
    def test_settlement_books_balance_exactly(self):
        """PRD §3.8: "The books balance exactly: gross revenue equals the sum of
        total expenses, observer fee, gear loss charge, processing fee, vessel
        share, and crew pool." and "the payouts always sum exactly to
        `crew_pool_cents`".

        Design: Difficulty/compensating_invariant/settlement_money_decomposition_conserved
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            expenses=(("FUEL", 120000, "2026-08-11T00:00:00Z"),
                      ("BAIT", 30000, "2026-08-11T01:00:00Z")),
            verify_expenses=(0, 1),
            gear_loss_units=2,
            crew=(("Alice", 2, "2026-01-15T00:00:00Z"),
                  ("Bob", 1, "2026-02-01T00:00:00Z")),
        )
        settlement = ctx["settlement"]
        assert_settlement_books_balance(settlement)
        assert_crew_payouts_sum_to_pool(settlement)
        assert settlement["crew_pool_cents"] == 315200

    def test_recalculate_after_dispute_reproduces_figures(self):
        """PRD §3.8: "A clerk then recalculates from `DISPUTED` —
        `ERR_SETTLEMENT_NOT_DISPUTED` otherwise — carrying
        `expected_settlement_version` under §2.6 and re-running the same
        expense-resolution and underwater gates against current data, returning
        the settlement to `CALCULATED`." With unchanged inputs the recomputation
        reproduces the figures with no drift.

        Design: Difficulty/compensating_invariant/settlement_money_decomposition_conserved
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            expenses=(("FUEL", 120000, "2026-08-11T00:00:00Z"),
                      ("BAIT", 30000, "2026-08-11T01:00:00Z")),
            verify_expenses=(0, 1),
            gear_loss_units=2,
            crew=(("Alice", 2, "2026-01-15T00:00:00Z"),
                  ("Bob", 1, "2026-02-01T00:00:00Z")),
        )
        settlement_id = ctx["settlement"]["id"]
        alice = ctx["contracts"][0]
        disputed = validate_success(api_client.dispute_settlement(
            settlement_id, make_crew_member_headers(alice["id"])), 200)
        assert disputed["status"] == "DISPUTED"
        recalculated = validate_success(api_client.recalculate_settlement(
            settlement_id,
            {"expected_settlement_version": disputed["version"]},
            CLERK), 200)
        assert recalculated["status"] == "CALCULATED"
        assert recalculated["crew_pool_cents"] == 315200
        assert recalculated["vessel_share_cents"] == 472800
        assert_crew_payouts_sum_to_pool(recalculated)
        assert_settlement_books_balance(recalculated)


class TestObserverFee:
    def test_observer_fee_ceil_days(self):
        """PRD §3.8: "2. **Observer fee** — for each of the trip's assignments in
        `DEPLOYED` or `DEBRIEFED`, the coverage window length in hours (fractional
        hours allowed) is divided by 24 and rounded up to a whole day count, and
        that day count is multiplied by 45,000 cents; the results are summed."

        Design: Corner/calculations/observer_fee_ceil_days
        """
        ctx = setup_trip_with_confirmed_observer(
            coverage_from="2026-08-10T00:00:00Z",
            coverage_to="2026-08-12T02:00:00Z")  # 50 hours
        vessel_id = ctx["vessel"]["id"]
        captain = make_captain_headers(vessel_id)
        advance_clock("2026-08-10T06:00:00Z")
        validate_success(api_client.depart_trip(ctx["trip"]["id"], captain), 200)
        api_client.create_catch_report(
            ctx["trip"]["id"],
            {"fishery_code": "HALIBUT", "report_type": "HARVEST",
             "reported_lbs": 4000, "reported_at": "2026-08-11T06:00:00Z"},
            captain)
        advance_clock("2026-08-12T06:00:00Z")
        validate_success(api_client.return_trip(ctx["trip"]["id"], captain), 200)
        declaration = declare_and_submit(ctx["trip"]["id"], vessel_id,
                                         declared_lbs=4000)
        # The observer debriefs their own assignment (ownership: X-User-ID is
        # the Observer id).
        validate_success(api_client.debrief_observer_assignment(
            ctx["assignment"]["id"],
            make_observer_headers(ctx["observer"]["id"])), 200)
        verify_and_finalize(declaration["id"])
        add_crew_contract(vessel_id, crew_name="Alice", share_points=1)
        settlement = validate_success(api_client.create_trip_settlement(
            ctx["trip"]["id"], create_settlement_payload(), CLERK), 201)
        calculated = validate_success(
            api_client.calculate_settlement(settlement["id"], CLERK), 200)
        # ceil(50/24) = 3 days x 45000 = 135000.
        assert calculated["observer_fee_cents"] == 135000
        assert calculated["net_cents"] == 852025
        assert calculated["vessel_share_cents"] == 511215
        assert calculated["crew_pool_cents"] == 340810
        assert_settlement_books_balance(calculated)


class TestSettlementGates:
    def test_expenses_unresolved_blocks_calculate(self):
        """PRD §3.8: "Three gates guard it: every expense of the trip must be
        terminal, `VERIFIED` or `REJECTED` (`ERR_EXPENSES_UNRESOLVED`)".

        Design: Corner/validations/expenses_unresolved_blocks_calculate
        """
        ctx = setup_settlement_draft(
            gross_revenue_cents=1000000,
            expenses=(("FUEL", 120000, "2026-08-11T00:00:00Z"),),
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
        )
        resp = api_client.calculate_settlement(ctx["settlement"]["id"], CLERK)
        validate_error(resp, "ERR_EXPENSES_UNRESOLVED", 409)
        assert get_settlement(ctx["settlement"]["id"])["status"] == "DRAFT"

    def test_settlement_underwater_rejected(self):
        """PRD §3.8 step 4: "4. **Net before fee** — `gross_revenue_cents` minus
        total expenses, minus the observer fee, minus the gear loss charge. This
        figure must be zero or positive; a negative result is rejected with
        `ERR_SETTLEMENT_UNDERWATER` (HTTP 422)."

        Design: Corner/validations/settlement_underwater_rejected
        """
        ctx = setup_settlement_draft(
            gross_revenue_cents=40000,
            expenses=(("FUEL", 50000, "2026-08-11T00:00:00Z"),),
            verify_expenses=(0,),
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
        )
        resp = api_client.calculate_settlement(ctx["settlement"]["id"], CLERK)
        validate_error(resp, "ERR_SETTLEMENT_UNDERWATER", 422)
        assert get_settlement(ctx["settlement"]["id"])["status"] == "DRAFT"

    def test_no_active_crew_blocks_calculate(self):
        """PRD §3.8: "at least one crew share contract on the vessel must be
        `ACTIVE` (`ERR_NO_ACTIVE_CREW`, HTTP 422)".

        Design: Corner/state_machines/no_active_crew_blocks_calculate
        """
        ctx = setup_settlement_draft(gross_revenue_cents=1000000, crew=())
        resp = api_client.calculate_settlement(ctx["settlement"]["id"], CLERK)
        validate_error(resp, "ERR_NO_ACTIVE_CREW", 422)

    def test_pay_calculated_settlement_rejected(self):
        """PRD §3.8: "Finally, a clerk pays an `APPROVED` settlement
        (`ERR_SETTLEMENT_NOT_APPROVED` otherwise), moving it to `PAID`".

        Design: Corner/state_machines/pay_calculated_settlement_rejected
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
        )
        resp = api_client.pay_settlement(ctx["settlement"]["id"], CLERK)
        validate_error(resp, "ERR_SETTLEMENT_NOT_APPROVED", 409)
        assert get_settlement(ctx["settlement"]["id"])["status"] == "CALCULATED"
        assert get_trip(ctx["trip"]["id"])["status"] == "LANDING_FINALIZED"

    def test_expense_verify_twice_rejected(self):
        """PRD §3.8: "A settlement clerk adjudicates expenses individually:
        verifying moves `PENDING` → `VERIFIED`, rejecting moves `PENDING` →
        `REJECTED`, and either action on an already-terminal expense is
        `ERR_EXPENSE_NOT_PENDING`."

        Design: Corner/state_machines/expense_verify_twice_rejected
        """
        ctx = setup_landing_finalized_trip()
        expense = add_expense(ctx["trip"]["id"], ctx["vessel"]["id"])
        validate_success(api_client.verify_expense(expense["id"], CLERK), 200)
        resp = api_client.verify_expense(expense["id"], CLERK)
        validate_error(resp, "ERR_EXPENSE_NOT_PENDING", 409)

    def test_settlement_before_finalization_rejected(self):
        """PRD §3.8: "Once the trip's landing is finalized — the trip must be in
        `LANDING_FINALIZED`, otherwise `ERR_TRIP_NOT_LANDING_FINALIZED` — a clerk
        creates the trip's settlement".

        Design: Corner/state_machines/settlement_before_finalization_rejected
        """
        # Build a trip whose declaration is VERIFIED but not yet FINALIZED.
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=10000)
        declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                         declared_lbs=4000)
        validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert get_trip(ctx["trip"]["id"])["status"] == "RETURNED"
        resp = api_client.create_trip_settlement(
            ctx["trip"]["id"], create_settlement_payload(), CLERK)
        validate_error(resp, "ERR_TRIP_NOT_LANDING_FINALIZED", 409)

    def test_occ_settlement_recalculate_stale_version(self):
        """PRD §2.6: "Recalculating a settlement requires
        `expected_settlement_version`, matching the settlement's current
        `version`; the recalculation basis (expense set, dispute round) must be
        current." and a mismatch "is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_settlement_recalculate_stale_version
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
        )
        settlement_id = ctx["settlement"]["id"]
        pre_dispute_version = ctx["settlement"]["version"]
        alice = ctx["contracts"][0]
        disputed = validate_success(api_client.dispute_settlement(
            settlement_id, make_crew_member_headers(alice["id"])), 200)
        resp = api_client.recalculate_settlement(
            settlement_id,
            {"expected_settlement_version": pre_dispute_version},
            CLERK)
        validate_error(resp, "ERR_STALE_VERSION", 412)
        recalculated = validate_success(api_client.recalculate_settlement(
            settlement_id,
            {"expected_settlement_version": disputed["version"]},
            CLERK), 200)
        assert recalculated["status"] == "CALCULATED"

    def test_rbac_clerk_cannot_approve_settlement(self):
        """PRD §4: POST /trip-settlements/{id}/approve lists only VesselOwner;
        PRD §2.1: "a role that is not listed for the endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)".

        Design: Corner/rbac/rbac_clerk_cannot_approve_settlement
        """
        ctx = setup_settlement_calculated(
            gross_revenue_cents=1000000,
            crew=(("Alice", 1, "2026-01-15T00:00:00Z"),),
        )
        resp = api_client.approve_settlement(ctx["settlement"]["id"], CLERK)
        validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)
        assert get_settlement(ctx["settlement"]["id"])["status"] == "CALCULATED"

    def test_trip_bubble_up_on_finalize_and_pay(self):
        """PRD §3.5: "a regulator finalizes a `VERIFIED` declaration —
        `ERR_DECLARATION_NOT_VERIFIED` from any other status — moving it to
        `FINALIZED`, and the trip bubbles up from `RETURNED` to
        `LANDING_FINALIZED`." PRD §3.8: "payment bubbles the trip from
        `LANDING_FINALIZED` to `SETTLED`, its terminal state."

        Design: Corner/state_machines/trip_bubble_up_on_finalize_and_pay
        """
        ctx = setup_landing_finalized_trip(catch_lbs=4000, holding_pounds=10000)
        assert get_trip(ctx["trip"]["id"])["status"] == "LANDING_FINALIZED"
        vessel_id = ctx["vessel"]["id"]
        add_crew_contract(vessel_id, crew_name="Alice", share_points=1)
        settlement = validate_success(api_client.create_trip_settlement(
            ctx["trip"]["id"], create_settlement_payload(), CLERK), 201)
        validate_success(api_client.calculate_settlement(settlement["id"], CLERK), 200)
        validate_success(api_client.approve_settlement(
            settlement["id"], make_vessel_owner_headers(vessel_id)), 200)
        paid = validate_success(api_client.pay_settlement(settlement["id"], CLERK), 200)
        assert paid["status"] == "PAID"
        assert get_trip(ctx["trip"]["id"])["status"] == "SETTLED"
