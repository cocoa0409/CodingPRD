"""Commission settlement: PROVISIONAL vs FINAL dual variant, per-event
rounding order, statement uniqueness, finalize/recompute lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_order,
    assert_instant_equal,
    create_active_contract,
    create_catering_order,
    create_department,
    create_hall,
    create_statement,
    drive_period_to_closed,
    drive_period_to_reconciled,
    fulfill_order,
    get_statement,
    invoice_order,
    menu_line,
    pay_order,
    schedule_order,
    setup_hall_cycle_recipe,
    submit_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["dining_admin_headers"]
CONTRACT_MANAGER = TEST_USERS["contract_manager_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]


class TestStatementLifecycle:
    def test_duplicate_statement_for_same_month_rejected(self, api):
        """PRD §3.9: "A `DiningAdmin` generates a statement for a contract by
        naming the `period_month` in `YYYY-MM` form; the statement is bound to
        the contract through its `vendor_contract_id`, the contract must be
        `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`), and at most one statement may
        exist per contract and month (else `ERR_DUPLICATE_STATEMENT`)."

        Design: Corner/calculations/commission_duplicate_statement_rejected
        """
        hall = create_hall(name="Hall C4", service_model="RETAIL")
        contract = create_active_contract(hall["id"], vendor_name="V3")
        create_statement(contract["id"], "2026-08")

        resp = api.create_commission_statement(
            contract["id"], {"period_month": "2026-08"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATEMENT)

        other = validate_success(api.create_commission_statement(
            contract["id"], {"period_month": "2026-09"}, ADMIN),
            expected_status=201)
        assert other["period_month"] == "2026-09"

    def test_finalize_twice_rejected(self, api):
        """PRD §3.9: "Finalization (`PROVISIONAL` → `FINALIZED`) is a
        `ContractManager` act that again requires the contract to be `ACTIVE`
        (else `ERR_CONTRACT_NOT_ACTIVE`); it recomputes every monetary field
        under the final variant — stricter period inclusion, paid-only catering
        on final totals, and the guarantee top-up — and stamps `finalized_at`
        with the logical clock."
        PRD §2.7: "4. **State** — the target entity sits in one of the
        transition's from-states (`ERR_INVALID_STATE`), and the cross-entity
        state gates live at this same tier: `ERR_HALL_SUSPENDED` when an
        operation requires an `ACTIVE` hall, `ERR_CONTRACT_NOT_ACTIVE` when a
        statement operation requires an `ACTIVE` contract,
        `ERR_FORECAST_LOCKED_PERIOD` when a forecast operation requires a
        `SCHEDULED` period, `ERR_PENDING_WASTE_LOGS` when a period close finds
        unposted waste, and `ERR_INSPECTION_INCOMPLETE` when a report close
        finds unverified actions."

        Design: Corner/state_machines/commission_finalize_twice_rejected
        """
        hall = create_hall(name="Hall SM5", service_model="RETAIL")
        contract = create_active_contract(hall["id"], vendor_name="V2")
        statement = create_statement(contract["id"], "2026-08")
        finalized = validate_success(api.finalize_commission_statement(
            statement["id"], CONTRACT_MANAGER))
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_at"] is not None

        resp = api.finalize_commission_statement(statement["id"],
                                                 CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_statement(statement["id"])
        assert after["status"] == "FINALIZED"
        assert after["finalized_at"] == finalized["finalized_at"], (
            "the rejected second finalize must not re-stamp finalized_at")


class TestDisputeRecomputeCycle:
    def _setup_zero_statement(self, api):
        hall = create_hall(name="Hall CS", service_model="RETAIL")
        contract = create_active_contract(hall["id"], vendor_name="CycleVendor",
                                          guarantee=0)
        return create_statement(contract["id"], "2026-08")

    def test_finalize_dispute_recompute_status_cycle(self, api):
        """PRD §3.9: "A `DiningAdmin` may dispute a `FINALIZED` statement
        (`FINALIZED` → `DISPUTED`), optionally supplying a `reason`. Dispute
        resolution is regeneration: a `DiningAdmin` recomputes a `DISPUTED`
        statement, returning it to `PROVISIONAL`, recomputing all monetary
        fields under the provisional variant, clearing `finalized_at` to null,
        and — as always — leaving `provisional_total_due_cents` untouched."

        Design: Difficulty/non_linear_state_machine/commission_dispute_recompute_cycle
        """
        statement = self._setup_zero_statement(api)
        statuses = [statement["status"]]
        finalized = validate_success(api.finalize_commission_statement(
            statement["id"], CONTRACT_MANAGER))
        statuses.append(finalized["status"])
        assert finalized["finalized_at"] is not None
        disputed = validate_success(api.dispute_commission_statement(
            statement["id"], ADMIN, {"reason": "vendor disputes retail count"}))
        statuses.append(disputed["status"])
        recomputed = validate_success(api.recompute_commission_statement(
            statement["id"], ADMIN))
        statuses.append(recomputed["status"])
        assert statuses == ["PROVISIONAL", "FINALIZED", "DISPUTED",
                            "PROVISIONAL"]
        assert recomputed["finalized_at"] is None

    def test_provisional_total_pinned_across_cycle(self, api):
        """PRD §3.9: "The statement is born `PROVISIONAL`, all of its monetary
        fields are computed under the provisional variant described below, and
        the resulting total is pinned as `provisional_total_due_cents` — a
        figure that is immutable thereafter, surviving finalization, dispute,
        and recompute unchanged."

        Design: Difficulty/non_linear_state_machine/commission_dispute_recompute_cycle
        """
        statement = self._setup_zero_statement(api)
        assert statement["provisional_total_due_cents"] == 0
        validate_success(api.finalize_commission_statement(statement["id"],
                                                           CONTRACT_MANAGER))
        validate_success(api.dispute_commission_statement(statement["id"], ADMIN))
        recomputed = validate_success(api.recompute_commission_statement(
            statement["id"], ADMIN))
        assert recomputed["provisional_total_due_cents"] == 0, (
            "pinned at creation and unchanged across the whole cycle")
        assert recomputed["total_due_to_university_cents"] == 0


class TestProvisionalVsFinalSettlement:
    def _setup_august_activity(self, api):
        """Hall + ACTIVE contract (board 500, retail 1000 bps, catering 800 bps,
        guarantee 50000); P1 (2026-08-03) CLOSED with 200 board + 100x3000
        retail; P2 (2026-08-04) RECONCILED with 100 board + 50x1000 retail;
        catering order A (2026-08-20) PAID with final 110000; order B
        (2026-08-21) SCHEDULED at the 50000 floor."""
        hall, recipe, cycle = setup_hall_cycle_recipe(
            hall_name="South Hall", service_model="HYBRID",
            dining_capacity=1000, unit_cost_cents=800,
            dietary_flags=["VEGETARIAN"])
        contract = create_active_contract(
            hall["id"], vendor_name="CampusEats LLC", board_rate=500,
            retail_bps=1000, catering_bps=800, guarantee=50000,
            start="2026-08-01", end="2026-12-01")
        drive_period_to_closed(
            hall["id"], cycle["id"], recipe["id"], "2026-08-03",
            events=[("BOARD_SWIPE", 0, 200), ("RETAIL_SALE", 3000, 100)])
        drive_period_to_reconciled(
            hall["id"], cycle["id"], recipe["id"], "2026-08-04",
            events=[("BOARD_SWIPE", 0, 100), ("RETAIL_SALE", 1000, 50)])

        dept = create_department(name="Engineering", code="ENG",
                                 budget=10000000)
        order_a = create_catering_order(
            hall["id"], dept["id"], "2026-08-20", "DINNER", 100,
            [menu_line(recipe["id"], 90)])
        assert order_a["quoted_total_cents"] == 100000
        submit_order(order_a["id"], dept["id"])
        approve_order(order_a["id"], dept["id"])
        schedule_order(order_a["id"])
        fulfill_order(order_a["id"])
        invoice_order(order_a["id"], 110000)
        pay_order(order_a["id"])

        order_b = create_catering_order(
            hall["id"], dept["id"], "2026-08-21", "LUNCH", 10,
            [menu_line(recipe["id"], 5)])
        assert order_b["quoted_total_cents"] == 50000, "minimum floor"
        submit_order(order_b["id"], dept["id"])
        approve_order(order_b["id"], dept["id"])
        schedule_order(order_b["id"])
        return contract

    def test_provisional_variant_inclusion_set(self, api):
        """PRD §3.9: "**Board revenue**: the included meal periods are those at
        the contract's hall whose `service_date` falls inside the period month —
        under the provisional variant, periods in `RECONCILED` or `CLOSED`
        status; under the final variant, `CLOSED` periods only." And: "**Catering
        commission**: the included orders are those at the hall whose
        `event_date` falls inside the period month — under the provisional
        variant, orders with `fulfillment_status` `SCHEDULED`, `FULFILLED`,
        `INVOICED`, or `PAID`, each contributing on its `quoted_total_cents`
        base; under the final variant, `PAID` orders only, each on its
        `final_total_cents` base." And: "The **guarantee top-up** is the
        provisional/final split's sharpest edge: `guarantee_top_up_cents` is
        always 0 in the provisional variant, and in the final variant it is the
        contract's `minimum_monthly_guarantee_cents` minus the sum of the retail
        and catering commissions, floored at zero."

        Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_settlement
        """
        contract = self._setup_august_activity(api)
        statement = create_statement(contract["id"], "2026-08")
        assert statement["status"] == "PROVISIONAL"
        # P1 (CLOSED) + P2 (RECONCILED) both included:
        # board = 200*500 + 100*500 = 150000
        assert statement["board_revenue_cents"] == 150000
        # retail = 100*round_half_up(3000*1000/10000) + 50*round_half_up(1000*1000/10000)
        #        = 100*300 + 50*100 = 35000
        assert statement["retail_commission_cents"] == 35000
        # catering on quoted bases: round_half_up(100000*0.08) + round_half_up(50000*0.08)
        # = 8000 + 4000 = 12000
        assert statement["catering_commission_cents"] == 12000
        assert statement["guarantee_top_up_cents"] == 0
        assert statement["total_due_to_university_cents"] == 47000
        assert statement["provisional_total_due_cents"] == 47000

    def test_final_variant_inclusion_set_and_top_up(self, api):
        """PRD §3.9: "Finalization (`PROVISIONAL` → `FINALIZED`) is a
        `ContractManager` act that again requires the contract to be `ACTIVE`
        (else `ERR_CONTRACT_NOT_ACTIVE`); it recomputes every monetary field
        under the final variant — stricter period inclusion, paid-only catering
        on final totals, and the guarantee top-up — and stamps `finalized_at`
        with the logical clock."
        PRD §3.9: "The `total_due_to_university_cents` is the retail commission
        plus the catering commission plus the guarantee top-up."

        Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_settlement
        """
        contract = self._setup_august_activity(api)
        statement = create_statement(contract["id"], "2026-08")
        finalized = validate_success(api.finalize_commission_statement(
            statement["id"], CONTRACT_MANAGER))
        assert finalized["status"] == "FINALIZED"
        # FINAL includes CLOSED periods only: P2 (RECONCILED) drops out.
        assert finalized["board_revenue_cents"] == 100000
        assert finalized["retail_commission_cents"] == 30000
        # PAID order A only, on final_total: round_half_up(110000 * 0.08) = 8800
        assert finalized["catering_commission_cents"] == 8800
        # top-up = max(0, 50000 - (30000 + 8800)) = 11200
        assert finalized["guarantee_top_up_cents"] == 11200
        assert finalized["total_due_to_university_cents"] == 50000
        assert finalized["provisional_total_due_cents"] == 47000, (
            "the pinned provisional total survives finalization unchanged")
        assert_instant_equal(finalized["finalized_at"], "2026-08-01T00:00:00Z")


class TestPerEventRoundingOrder:
    def _setup_three_retail_sales(self, api):
        """One CLOSED period holding exactly three 335-cent RETAIL_SALE events;
        contract at 1500 bps retail, 0 bps catering, 0 guarantee."""
        hall, recipe, cycle = setup_hall_cycle_recipe(
            hall_name="Hall R", service_model="RETAIL", dining_capacity=800,
            unit_cost_cents=400, station="DELI")
        contract = create_active_contract(
            hall["id"], vendor_name="RoundTest", board_rate=500,
            retail_bps=1500, catering_bps=0, guarantee=0,
            start="2026-08-01", end="2026-12-01")
        drive_period_to_closed(
            hall["id"], cycle["id"], recipe["id"], "2026-08-05",
            events=[("RETAIL_SALE", 335, 3)])
        return contract

    def test_rounding_is_per_event_then_sum(self, api):
        """PRD §3.9: "**Retail commission**: every `RETAIL_SALE` swipe event of
        every included period contributes its `amount_cents` times
        `retail_commission_bps` divided by 10,000, rounded half-up to whole
        cents *per event*, and `retail_commission_cents` is the sum of those
        per-event rounded values — the rounding order is pinned: round each
        event first, then sum; summing first and rounding once is a different,
        forbidden result."

        Design: Difficulty/combinatorial_formula/commission_per_event_rounding_order
        """
        contract = self._setup_three_retail_sales(api)
        statement = create_statement(contract["id"], "2026-08")
        # 3 x round_half_up(335 * 1500 / 10000) = 3 x round_half_up(50.25) = 150
        assert statement["retail_commission_cents"] == 150, (
            "sum-then-round would give round_half_up(1005 * 0.15) = 151 — the "
            "pinned order is per-event then sum")

    def test_other_lines_zero_and_total_matches(self, api):
        """PRD §3.9: "The `total_due_to_university_cents` is the retail
        commission plus the catering commission plus the guarantee top-up."
        PRD §3.9: "The **guarantee top-up** is the provisional/final split's
        sharpest edge: `guarantee_top_up_cents` is always 0 in the provisional
        variant, and in the final variant it is the contract's
        `minimum_monthly_guarantee_cents` minus the sum of the retail and
        catering commissions, floored at zero."

        Design: Difficulty/combinatorial_formula/commission_per_event_rounding_order
        """
        contract = self._setup_three_retail_sales(api)
        statement = create_statement(contract["id"], "2026-08")
        assert statement["board_revenue_cents"] == 0
        assert statement["catering_commission_cents"] == 0
        assert statement["guarantee_top_up_cents"] == 0
        assert statement["total_due_to_university_cents"] == 150
