"""Credit-claim creation gates, tier computation, and adjudication forks."""
from test_helpers import (
    ADMIN,
    ADJUSTER,
    ApiErrorId,
    create_claim,
    create_order,
    get_credit_claim,
    get_operator,
    get_order,
    set_logical_clock,
    settle_order_with_event,
    setup_selling_location,
    submit_order,
    confirm_order,
    deliver_order,
    walk_order_to_delivered,
    find_claim_line,
    validate_error,
    validate_success,
)

CLAIM_CLOCK = "2026-08-10T00:00:00Z"


class TestTieredClaimComputation:
    def _tiered_world(self, api):
        """Delivered 2-case order (20 units, pinned 1000/case); clock advanced
        to 2026-08-10 so one claim can exercise three expiry tiers."""
        world = setup_selling_location(
            products_spec=[{"sku": "YOG-04", "name": "Yogurt case",
                            "category": "CHILLED", "shelf_life_days": 21,
                            "perishability_class": "CHILLED"}],
            slots_spec=[{"slot_code": "C1", "product_index": 0,
                         "par_level_units": 20, "vend_price_cents": 180}],
            route_code="R-CR",
            operator_name="Op Credit",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 2}],
        )
        set_logical_clock(CLAIM_CLOCK)
        return world, order

    def test_claim_three_tier_total(self, api):
        """PRD §3.7: "From 0 through 7 days to expiry inclusive, the line
        credits 75 percent; from 8 through 14 days inclusive, 50 percent" and
        "an expired line credits 100 percent of its wholesale value."
        PRD §3.7: "At creation the claim copies `operator_id` from its order,
        computes each line's `line_credit_cents` and pins it, sums the lines
        into `requested_credit_cents` — immutable thereafter"

        Design: Difficulty/combinatorial_formula/short_date_credit_tiered_branching
        """
        world, order = self._tiered_world(api)
        pr = world["products"][0]["id"]
        # At clock 2026-08-10: 08-12 -> 2 days (75%), 08-20 -> 10 days (50%),
        # 08-05 -> expired 5 days, inside the 30-day window (100%).
        claim = create_claim(
            world, order["id"],
            [
                {"product_id": pr, "quantity_units": 10,
                 "expiration_date": "2026-08-12"},
                {"product_id": pr, "quantity_units": 5,
                 "expiration_date": "2026-08-20"},
                {"product_id": pr, "quantity_units": 4,
                 "expiration_date": "2026-08-05"},
            ],
        )
        assert claim["status"] == "SUBMITTED"
        # 750 + 250 + 400
        assert claim["requested_credit_cents"] == 1400

    def test_claim_line_credits_pinned(self, api):
        """PRD §3.7: "A line's credit amount is its order line's pinned
        `unit_price_cents` times `quantity_units` times the tier percentage,
        divided by the product's `case_pack_qty`, rounded half up per line."

        Design: Difficulty/combinatorial_formula/short_date_credit_tiered_branching
        """
        world, order = self._tiered_world(api)
        pr = world["products"][0]["id"]
        claim = create_claim(
            world, order["id"],
            [
                {"product_id": pr, "quantity_units": 10,
                 "expiration_date": "2026-08-12"},
                {"product_id": pr, "quantity_units": 5,
                 "expiration_date": "2026-08-20"},
                {"product_id": pr, "quantity_units": 4,
                 "expiration_date": "2026-08-05"},
            ],
        )
        # round_half_up(1000*10*0.75/10)=750; round_half_up(1000*5*0.50/10)=250;
        # round_half_up(1000*4*1.00/10)=400.
        assert find_claim_line(claim, "2026-08-12")["line_credit_cents"] == 750
        assert find_claim_line(claim, "2026-08-20")["line_credit_cents"] == 250
        assert find_claim_line(claim, "2026-08-05")["line_credit_cents"] == 400


class TestClaimCreationGates:
    def _delivered_one_case(self, api, sku, route_code, perishable=True):
        spec = {"sku": sku, "name": sku, "shelf_life_days": 21}
        if perishable:
            spec["category"] = "CHILLED"
            spec["perishability_class"] = "CHILLED"
        world = setup_selling_location(
            products_spec=[spec],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 20, "vend_price_cents": 180}],
            route_code=route_code,
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        return world, order

    def test_claim_window_expired_beats_qty_exceeded(self, api):
        """PRD §2.8: "This ordering is observable behavior. ... a claim line
        both past its claim window and over-delivered surfaces
        `ERR_CLAIM_WINDOW_EXPIRED` from tier 9 rather than the quantity gate
        from tier 11."
        PRD §3.7: "the line is creditable only if it expired no more than 30
        days ago — the whole claim is rejected with `ERR_CLAIM_WINDOW_EXPIRED`
        beyond that"

        Design: Difficulty/priority_pair_validation_conflict/claim_window_expired_beats_qty_exceeded
        """
        world, order = self._delivered_one_case(api, "PR2-1", "R-PR2")
        set_logical_clock(CLAIM_CLOCK)
        # 2026-07-01 is 40 days before the claim date (window blown) AND
        # 50 units exceed the 10 delivered — temporal tier 9 must win.
        err = api.create_credit_claim(
            {
                "order_id": order["id"],
                "lines": [{"product_id": world["products"][0]["id"],
                           "quantity_units": 50,
                           "expiration_date": "2026-07-01"}],
            },
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)

    def test_qty_gate_fires_when_window_ok(self, api):
        """PRD §3.7: "Violations reject with `ERR_CLAIM_EXCEEDS_DELIVERED_QTY`."
        — once the temporal tier is satisfied, the tier-11 quantity gate is the
        first failing tier for the same oversized quantity.

        Design: Difficulty/priority_pair_validation_conflict/claim_window_expired_beats_qty_exceeded
        """
        world, order = self._delivered_one_case(api, "PR2-1", "R-PR2")
        set_logical_clock(CLAIM_CLOCK)
        # 2026-07-30 is 11 days before the claim date — inside the 30-day
        # window — so the over-delivery gate is what fails.
        err = api.create_credit_claim(
            {
                "order_id": order["id"],
                "lines": [{"product_id": world["products"][0]["id"],
                           "quantity_units": 50,
                           "expiration_date": "2026-07-30"}],
            },
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_CLAIM_EXCEEDS_DELIVERED_QTY)

    def test_claim_line_not_creditable_rejected(self, api):
        """PRD §3.7: "a line with strictly more than 14 days to expiry earns
        nothing, and the whole claim is rejected with
        `ERR_LINE_NOT_CREDITABLE`."

        Design: Corner/errors/claim_line_not_creditable_rejected
        """
        world, order = self._delivered_one_case(api, "NCR-1", "R-NCR")
        # Clock is the default 2026-08-01; 2026-08-20 is 19 days out (> 14).
        err = api.create_credit_claim(
            {
                "order_id": order["id"],
                "lines": [{"product_id": world["products"][0]["id"],
                           "quantity_units": 2,
                           "expiration_date": "2026-08-20"}],
            },
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_LINE_NOT_CREDITABLE)

    def test_claim_qty_exceeds_delivered_rejected(self, api):
        """PRD §3.7: "For each claim line, the `quantity_units` of the new
        claim plus the `quantity_units` of every non-terminal claim — those in
        `SUBMITTED`, `APPROVED`, or `SETTLED` status — for the same order and
        product must not exceed the delivered units, defined as the order
        line's `quantity_cases` times the product's `case_pack_qty`."

        Design: Corner/errors/claim_qty_exceeds_delivered_rejected
        """
        world, order = self._delivered_one_case(api, "OVR-1", "R-OVR")
        # 1 case x pack 10 delivers 10 units; claiming 11 exceeds it.
        err = api.create_credit_claim(
            {
                "order_id": order["id"],
                "lines": [{"product_id": world["products"][0]["id"],
                           "quantity_units": 11,
                           "expiration_date": "2026-07-30"}],
            },
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_CLAIM_EXCEEDS_DELIVERED_QTY)


class TestAdjudicationFork:
    def _fork_world(self, api):
        """Two delivered 1-case orders (due 1000 each); claims filed at the
        advanced clock for 5 units expired 3 days earlier (credit 500 each)."""
        world = setup_selling_location(
            products_spec=[{"sku": "FRK-1", "name": "Fork item",
                            "shelf_life_days": 60}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 20, "vend_price_cents": 150}],
            route_code="R-FRK",
            operator_name="Op Fork",
        )
        pr = world["products"][0]["id"]
        order1 = walk_order_to_delivered(
            world, [{"product_id": pr, "quantity_cases": 1}],
        )
        order2 = walk_order_to_delivered(
            world, [{"product_id": pr, "quantity_cases": 1}],
        )
        set_logical_clock(CLAIM_CLOCK)
        claim1 = create_claim(
            world, order1["id"],
            [{"product_id": pr, "quantity_units": 5,
              "expiration_date": "2026-08-07"}],
        )
        claim2 = create_claim(
            world, order2["id"],
            [{"product_id": pr, "quantity_units": 5,
              "expiration_date": "2026-08-07"}],
        )
        return world, order1, order2, claim1, claim2

    def test_approve_branch_auto_applies(self, api):
        """PRD §3.7: "Link two, triggered by that balance increase: the credit
        auto-applies to the operator's oldest order whose `settlement_status`
        is `OPEN`, oldest by `created_at`" and "And when the claim's
        `applied_cents` reaches its `requested_credit_cents` — the whole credit
        absorbed by open orders — the claim itself moves automatically from
        `APPROVED` to `SETTLED`."

        Design: Difficulty/non_linear_state_machine/credit_claim_approve_reject_fork
        """
        world, order1, order2, claim1, claim2 = self._fork_world(api)
        approved = validate_success(
            api.approve_credit_claim(claim1["id"], ADJUSTER), 200,
        )
        # 500 issued then fully auto-applied to the oldest OPEN order (order1).
        assert approved["status"] == "SETTLED"
        assert approved["applied_cents"] == 500

        reread1 = get_order(order1["id"])
        assert reread1["credit_applied_cents"] == 500
        assert reread1["amount_due_cents"] == 500
        assert reread1["settlement_status"] == "OPEN"
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 0

    def test_reject_branch_issues_nothing(self, api):
        """PRD §3.7: "Rejection by a `CreditAdjuster` moves `SUBMITTED` →
        `REJECTED`; no credit is issued and the operator's
        `credit_balance_cents` is unchanged."

        Design: Difficulty/non_linear_state_machine/credit_claim_approve_reject_fork
        """
        world, order1, order2, claim1, claim2 = self._fork_world(api)
        rejected = validate_success(
            api.reject_credit_claim(claim2["id"], ADJUSTER), 200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["applied_cents"] == 0

        reread2 = get_order(order2["id"])
        assert reread2["credit_applied_cents"] == 0
        assert reread2["amount_due_cents"] == 1000
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 0


class TestTerminalLockdowns:
    def test_claim_rejected_terminal_lockdown(self, api):
        """PRD §3.7: "Approval by a `CreditAdjuster` — from any other state the
        attempt rejects with `ERR_CLAIM_NOT_SUBMITTED`" and "`REJECTED`,
        `VOIDED`, and `SETTLED` are all terminal for a claim."

        Design: Corner/state_machines/claim_rejected_terminal_lockdown
        """
        world = setup_selling_location(
            products_spec=[{"sku": "CLK-1", "name": "Clock item",
                            "category": "CHILLED", "shelf_life_days": 21,
                            "perishability_class": "CHILLED"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 180}],
            route_code="R-CLK",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        claim = create_claim(
            world, order["id"],
            [{"product_id": world["products"][0]["id"], "quantity_units": 1,
              "expiration_date": "2026-07-30"}],
        )
        validate_success(api.reject_credit_claim(claim["id"], ADJUSTER), 200)

        err = api.approve_credit_claim(claim["id"], ADJUSTER)
        validate_error(err, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)
        assert get_credit_claim(claim["id"])["status"] == "REJECTED"
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 0

    def test_claim_approve_twice_rejected(self, api):
        """PRD §3.7: "Approval by a `CreditAdjuster` — from any other state the
        attempt rejects with `ERR_CLAIM_NOT_SUBMITTED` — moves the claim to
        `APPROVED` and fires a three-link cascade. Link one: the operator's
        `credit_balance_cents` increases by `requested_credit_cents`."

        Design: Corner/state_machines/claim_approve_twice_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "A2X-1", "name": "A2x item",
                            "category": "CHILLED", "shelf_life_days": 21,
                            "perishability_class": "CHILLED"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 180}],
            route_code="R-A2X",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        # Settle the order so approval finds no OPEN order to auto-apply to.
        settle_order_with_event(world, order, tender="CASH")
        claim = create_claim(
            world, order["id"],
            [{"product_id": world["products"][0]["id"], "quantity_units": 10,
              "expiration_date": "2026-07-30"}],
        )
        approved = validate_success(
            api.approve_credit_claim(claim["id"], ADJUSTER), 200,
        )
        assert approved["status"] == "APPROVED"

        err = api.approve_credit_claim(claim["id"], ADJUSTER)
        validate_error(err, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)

        reread = get_credit_claim(claim["id"])
        assert reread["status"] == "APPROVED"
        assert reread["applied_cents"] == 0
        # Credit was issued exactly once.
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 1000


class TestVoidGate:
    def test_claim_void_after_application_rejected(self, api):
        """PRD §3.7: "A `CreditAdjuster` may void a claim that is `APPROVED`
        with `applied_cents` still equal to 0, provided the operator's
        `credit_balance_cents` still holds at least the claim's
        `requested_credit_cents`; a claim failing either condition rejects with
        `ERR_CLAIM_NOT_VOIDABLE`."

        Design: Corner/errors/claim_void_after_application_rejected
        """
        world = setup_selling_location(
            products_spec=[
                {"sku": "VD-1", "name": "Void small", "base_price_cents": 500,
                 "cost_cents": 300, "shelf_life_days": 60},
                {"sku": "VD-2", "name": "Void big", "category": "CHILLED",
                 "shelf_life_days": 21, "perishability_class": "CHILLED"},
            ],
            slots_spec=[
                {"slot_code": "A1", "product_index": 0, "par_level_units": 10,
                 "vend_price_cents": 100},
                {"slot_code": "A2", "product_index": 1, "par_level_units": 20,
                 "vend_price_cents": 180},
            ],
            route_code="R-VOID",
            operator_name="Op Void",
        )
        pr1, pr2 = (p["id"] for p in world["products"])
        # O1 (oldest OPEN): 1 case at 500 -> due 500.
        order1 = walk_order_to_delivered(
            world, [{"product_id": pr1, "quantity_cases": 1}],
        )
        # O2: 2 cases at 1000 -> due 2000.
        order2 = walk_order_to_delivered(
            world, [{"product_id": pr2, "quantity_cases": 2}],
        )
        # Claim against O2: 20 expired units -> credit 2000.
        claim = create_claim(
            world, order2["id"],
            [{"product_id": pr2, "quantity_units": 20,
              "expiration_date": "2026-07-30"}],
        )
        approved = validate_success(
            api.approve_credit_claim(claim["id"], ADJUSTER), 200,
        )
        # min(balance 2000, O1 due 500) auto-applies to the oldest OPEN order.
        assert approved["status"] == "APPROVED"
        assert approved["applied_cents"] == 500
        assert get_order(order1["id"])["settlement_status"] == "SETTLED"

        err = api.void_credit_claim(claim["id"], ADJUSTER)
        validate_error(err, ApiErrorId.ERR_CLAIM_NOT_VOIDABLE)

        reread = get_credit_claim(claim["id"])
        assert reread["status"] == "APPROVED"
        assert reread["applied_cents"] == 500
        # 2000 issued minus 500 applied; the failed void must not move it.
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 1500
