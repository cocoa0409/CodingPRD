"""Operator credit ledger: claim-approve cascades, void compensation, and
explicit credit application to open receivables."""
from test_helpers import (
    ADMIN,
    ADJUSTER,
    ApiErrorId,
    create_claim,
    create_order,
    get_operator,
    get_order,
    get_credit_claim,
    set_logical_clock,
    settle_order_with_event,
    setup_selling_location,
    submit_order,
    confirm_order,
    deliver_order,
    walk_order_to_delivered,
    validate_error,
    validate_success,
)


class TestApproveCascadeDepth3:
    def _cascade_world(self, api):
        """One delivered 2-case order (due 2000) and a full-coverage expired
        claim (20 units -> credit exactly 2000)."""
        world = setup_selling_location(
            products_spec=[{"sku": "CAS-1", "name": "Cascade item",
                            "shelf_life_days": 60}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 20, "vend_price_cents": 150}],
            route_code="R-CAS",
            operator_name="Op Cascade",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 2}],
        )
        # Expired 2 days before the default logical date: 100% tier, so
        # round_half_up(1000 * 20 * 1.00 / 10) == 2000.
        claim = create_claim(
            world, order["id"],
            [{"product_id": world["products"][0]["id"], "quantity_units": 20,
              "expiration_date": "2026-07-30"}],
        )
        return world, order, claim

    def test_cascade_claim_side(self, api):
        """PRD §3.7: "Link one: the operator's `credit_balance_cents` increases
        by `requested_credit_cents`." and "And when the claim's `applied_cents`
        reaches its `requested_credit_cents` — the whole credit absorbed by
        open orders — the claim itself moves automatically from `APPROVED` to
        `SETTLED`."

        Design: Difficulty/transitive_cascade/claim_approve_credit_cascade_depth3
        """
        world, order, claim = self._cascade_world(api)
        assert claim["requested_credit_cents"] == 2000
        approved = validate_success(
            api.approve_credit_claim(claim["id"], ADJUSTER), 200,
        )
        assert approved["applied_cents"] == 2000
        assert approved["status"] == "SETTLED", (
            "fully absorbed by the auto-application"
        )

    def test_cascade_order_and_balance_side(self, api):
        """PRD §3.7: "The applied amount is the smaller of the current
        `credit_balance_cents` and that order's `amount_due_cents`, and it
        debits `credit_balance_cents`, grows the claim's `applied_cents`, grows
        the order's `credit_applied_cents`, and shrinks the order's
        `amount_due_cents` by that same amount. Link three, triggered by that
        order mutation: an order whose `amount_due_cents` reaches zero
        auto-settles to `SETTLED`, again with no tender recorded, so
        `settled_tender` remains null."

        Design: Difficulty/transitive_cascade/claim_approve_credit_cascade_depth3
        """
        world, order, claim = self._cascade_world(api)
        validate_success(api.approve_credit_claim(claim["id"], ADJUSTER), 200)

        reread = get_order(order["id"])
        assert reread["credit_applied_cents"] == 2000
        assert reread["amount_due_cents"] == 0
        assert reread["settlement_status"] == "SETTLED"
        assert reread["settled_tender"] is None, (
            "auto-settlement by credit records no tender"
        )
        # +2000 issued (link 1) then -2000 applied (link 2).
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 0


class TestApproveVoidConservation:
    def _conservation_world(self, api):
        """Delivered order settled first (no OPEN order exists), then a
        10-unit expired claim (credit 1000)."""
        world = setup_selling_location(
            products_spec=[{"sku": "INV-2", "name": "Inv2 item",
                            "category": "CHILLED", "shelf_life_days": 21,
                            "perishability_class": "CHILLED"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 180}],
            route_code="R-INV2",
            operator_name="Op Inv2",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        settle_order_with_event(world, order, tender="CASH",
                                recorded_at="2026-08-04T09:00:00Z")
        claim = create_claim(
            world, order["id"],
            [{"product_id": world["products"][0]["id"], "quantity_units": 10,
              "expiration_date": "2026-07-30"}],
        )
        return world, claim

    def test_approve_without_open_order_holds_balance(self, api):
        """PRD §3.7: "Link two, triggered by that balance increase: the credit
        auto-applies to the operator's oldest order whose `settlement_status`
        is `OPEN`, oldest by `created_at`; if no such order exists, the credit
        simply stays on the balance."

        Design: Difficulty/compensating_invariant/approve_void_credit_balance_conservation
        """
        world, claim = self._conservation_world(api)
        approved = validate_success(
            api.approve_credit_claim(claim["id"], ADJUSTER), 200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["applied_cents"] == 0
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 1000

    def test_void_restores_credit_balance(self, api):
        """PRD §3.7: "Voiding debits `credit_balance_cents` by
        `requested_credit_cents`, so an approve-then-void pair leaves the
        operator's credit balance exactly as it was before approval."

        Design: Difficulty/compensating_invariant/approve_void_credit_balance_conservation
        """
        world, claim = self._conservation_world(api)
        validate_success(api.approve_credit_claim(claim["id"], ADJUSTER), 200)
        voided = validate_success(api.void_credit_claim(claim["id"], ADJUSTER), 200)
        assert voided["status"] == "VOIDED"
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 0, (
            "approve + void conserves the credit balance with no drift"
        )


class TestExplicitCreditApplication:
    def test_apply_credit_partial_reconciliation(self, api):
        """PRD §3.6: "The request may carry an explicit `amount_cents`; the
        applied amount is the smaller of the requested amount — or the
        operator's full `credit_balance_cents` when none is supplied — and the
        order's `amount_due_cents`." and "Application debits
        `credit_balance_cents`, grows the order's `credit_applied_cents`, and
        reduces `amount_due_cents` by the applied amount; when
        `amount_due_cents` reaches zero the order auto-settles to `SETTLED`"

        Design: Corner/endpoints/apply_credit_partial_reconciliation
        """
        world = setup_selling_location(
            products_spec=[{"sku": "AC-1", "name": "AC item",
                            "category": "CHILLED", "shelf_life_days": 21,
                            "perishability_class": "CHILLED"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 30, "vend_price_cents": 180}],
            route_code="R-AC",
            operator_name="Op AC",
        )
        pr = world["products"][0]["id"]
        # O1: delivered then SETTLED, so the approved claim cannot auto-apply.
        order1 = walk_order_to_delivered(
            world, [{"product_id": pr, "quantity_cases": 1}],
        )
        settle_order_with_event(world, order1, tender="CASH")
        claim = create_claim(
            world, order1["id"],
            [{"product_id": pr, "quantity_units": 10,
              "expiration_date": "2026-07-30"}],
        )
        validate_success(api.approve_credit_claim(claim["id"], ADJUSTER), 200)
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 1000

        # O2: 2 cases -> due 2000, settlement OPEN.
        order2 = walk_order_to_delivered(
            world, [{"product_id": pr, "quantity_cases": 2}],
            delivery_date="2026-08-10",
        )

        applied = validate_success(
            api.apply_credit_to_order(order2["id"], {"amount_cents": 400},
                                      world["om_headers"]),
            200,
        )
        assert applied["credit_applied_cents"] == 400
        assert applied["amount_due_cents"] == 1600
        assert applied["settlement_status"] == "OPEN", (
            "partial application does not settle"
        )
        assert get_operator(world["operator"]["id"])["credit_balance_cents"] == 600

    def test_apply_credit_insufficient_balance_rejected(self, api):
        """PRD §3.6: "A zero balance, or an `amount_cents` exceeding the
        balance, rejects with `ERR_INSUFFICIENT_CREDIT_BALANCE`."

        Design: Corner/endpoints/apply_credit_insufficient_balance_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "INS-1", "name": "Ins item"}],
            route_code="R-INS",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        # Balance is 0; the explicit amount also exceeds it.
        err = api.apply_credit_to_order(order["id"], {"amount_cents": 1500},
                                        world["om_headers"])
        validate_error(err, ApiErrorId.ERR_INSUFFICIENT_CREDIT_BALANCE)

        reread = get_order(order["id"])
        assert reread["amount_due_cents"] == 1000
        assert reread["credit_applied_cents"] == 0
