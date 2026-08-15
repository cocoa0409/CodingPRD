"""Order lifecycle, payment lifecycle, payment_status derivation, money
guards, and idempotent creation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_ordering_at_window_end,
    create_and_submit_order,
    create_order,
    create_payment_payload,
    create_submitted_paid_order,
    get_group_ledger,
    get_success_data,
    make_treasurer_headers,
    record_and_clear_payment,
    reset_clock,
    setup_open_campaign_with_seller,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]
TREAS2 = make_treasurer_headers("treas-2")


class TestOrderCreationGates:
    def test_order_create_when_campaign_not_open_rejected(self, api):
        """PRD §3.2: "Creation requires the campaign to be `OPEN` — attempting
        to create against a non-open campaign is rejected with
        `ERR_CAMPAIGN_NOT_OPEN`".

        Design: Corner/validations/order_create_when_campaign_not_open_rejected
        """
        reset_clock()
        from test_helpers import setup_campaign_group_product, create_seller
        campaign, group, product = setup_campaign_group_product()
        seller = create_seller(group["id"])
        resp = api.create_order({
            "seller_id": seller["id"], "family_contact_name": "Fam1",
            "lines": [{"product_id": product["id"], "quantity": 1}],
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)

    def test_order_submit_outside_window_rejected(self, api):
        """PRD §3.2: "the logical clock must lie at or after
        `order_window_start` and at or before `order_window_end` (else
        `ERR_OUTSIDE_ORDER_WINDOW`)".

        Design: Corner/validations/order_submit_outside_window_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_order(seller["id"], product["id"], 1)
        reset_clock("2026-08-21T00:00:00Z")
        resp = api.submit_order(order["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_ORDER_WINDOW)
        after = get_success_data(api.get_order(order["id"], COORD))
        assert after["status"] == "DRAFT"

    def test_order_submit_with_discontinued_product_rejected(self, api):
        """PRD §3.1: "any later order submit naming that product fails with
        `ERR_PRODUCT_NOT_ORDERABLE`."

        Design: Corner/validations/order_submit_with_discontinued_product_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_order(seller["id"], product["id"], 1)
        get_success_data(api.discontinue_product(product["id"], ADMIN))
        resp = api.submit_order(order["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ORDERABLE)
        after = get_success_data(api.get_order(order["id"], COORD))
        assert after["status"] == "DRAFT"

    def test_per_seller_limit_exact_and_exceeded(self, api):
        """PRD §3.2: "per line, the cumulative quantity of that product across
        the seller's non-cancelled orders — including the submitting order —
        must not exceed the product's `per_seller_limit` when one is set (else
        `ERR_PER_SELLER_LIMIT_EXCEEDED`)".

        Design: Corner/validations/per_seller_limit_exact_and_exceeded
        """
        reset_clock()
        from test_helpers import (
            setup_campaign_group_product, create_product, create_seller)
        campaign, group, _p = setup_campaign_group_product()
        product = create_product(campaign["id"], name="Limit Bar",
                                 sku="LIMIT-01", per_seller_limit=5)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_and_submit_order(seller["id"], product["id"], 3)
        # Cumulative 3 + 2 == 5 hits the limit exactly: allowed.
        order2 = create_and_submit_order(seller["id"], product["id"], 2)
        assert order2["status"] == "SUBMITTED"
        # One more unit would reach 6: rejected.
        order3 = create_order(seller["id"], product["id"], 1,
                              family_contact_name="Fam3")
        resp = api.submit_order(order3["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_PER_SELLER_LIMIT_EXCEEDED)


class TestPaymentStatusDerivation:
    def test_payment_exact_total_reaches_paid(self, api):
        """PRD §3.2: "`cleared_cents` is the sum over the order's payments in
        `CLEARED` status — and only those; `RECORDED`, `BOUNCED`, `VOIDED`,
        and `REFUNDED` payments contribute nothing".
        PRD §3.2: "The order is `UNPAID` when `cleared_cents` is zero, `PAID`
        when `cleared_cents` equals `total_cents` (with `total_cents`
        positive), and `PARTIALLY_PAID` when `cleared_cents` lies strictly
        between."

        Design: Difficulty/boundary_precision_check/payment_exact_total_reaches_paid
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"], amount_cents=1000,
                                   method="CASH"),
            TREAS)
        payment = validate_success(resp, 201)
        assert payment["status"] == "RECORDED"
        recorded_view = get_success_data(api.get_order(order["id"], TREAS))
        assert recorded_view["payment_status"] == "UNPAID"
        assert recorded_view["cleared_cents"] == 0, (
            "RECORDED payments are excluded from the cleared input set")

        get_success_data(api.clear_payment(payment["id"], TREAS))
        cleared_view = get_success_data(api.get_order(order["id"], TREAS))
        assert cleared_view["payment_status"] == "PAID", (
            "cleared == total exactly must flip to PAID (inclusive boundary)")
        assert cleared_view["cleared_cents"] == 1000

    def test_recorded_payment_excluded_from_partial_derivation(self, api):
        """PRD §3.2: "The order is `UNPAID` when `cleared_cents` is zero,
        `PAID` when `cleared_cents` equals `total_cents` (with `total_cents`
        positive), and `PARTIALLY_PAID` when `cleared_cents` lies strictly
        between."

        Design: Difficulty/boundary_precision_check/payment_exact_total_reaches_paid
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        record_and_clear_payment(order["id"], 600, method="CASH")
        partial = get_success_data(api.get_order(order["id"], TREAS))
        assert partial["payment_status"] == "PARTIALLY_PAID"
        assert partial["cleared_cents"] == 600

    def test_order_payment_dimension_cycle_paid_partial_paid(self, api):
        """PRD §3.2: "The lifecycle begins at `UNPAID` and moves among the
        three values as the derivation dictates — `UNPAID` → `PARTIALLY_PAID`
        or `PAID` as value clears, and regressions `PAID` → `PARTIALLY_PAID`
        or `UNPAID`, and `PARTIALLY_PAID` → `UNPAID`, when bounces or refunds
        drain cleared value."
        PRD §3.2: "a `BOUNCE_FEE_DEBIT` entry for the fixed bounce fee is
        posted to the order's group".

        Design: Difficulty/non_linear_state_machine/order_payment_dimension_cycle_paid_partial_paid
        """
        reset_clock()
        _campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        record_and_clear_payment(order["id"], 600, method="CASH")
        pay_b = record_and_clear_payment(order["id"], 400, method="CHECK")

        full = get_success_data(api.get_order(order["id"], TREAS))
        assert full["payment_status"] == "PAID"
        assert full["fulfillment_status"] == "PENDING", (
            "the payment cycle must not touch the fulfillment dimension")

        bounced = get_success_data(api.bounce_payment(pay_b["id"], TREAS))
        assert bounced["status"] == "BOUNCED"
        after_bounce = get_success_data(api.get_order(order["id"], TREAS))
        assert after_bounce["payment_status"] == "PARTIALLY_PAID", (
            "bouncing the 400 check leaves cleared 600 of 1000")
        assert after_bounce["cleared_cents"] == 600
        assert after_bounce["fulfillment_status"] == "PENDING"

        ledger = get_group_ledger(group["id"])
        bounce_entries = [e for e in ledger
                          if e["entry_type"] == "BOUNCE_FEE_DEBIT"]
        assert len(bounce_entries) == 1, "bounce must post a BOUNCE_FEE_DEBIT"
        assert bounce_entries[0]["amount_cents"] < 0, (
            "debits are negative per the ledger's signed-amount rule")

        record_and_clear_payment(order["id"], 400, method="CASH")
        final = get_success_data(api.get_order(order["id"], TREAS))
        assert final["payment_status"] == "PAID"
        assert final["cleared_cents"] == 1000

    def test_payment_cycle_fulfillment_stays_pending_throughout(self, api):
        """PRD §2.11: "Every lifecycle-bearing resource exposes its current
        state in a `status` field — supplemented on orders by the derived
        `payment_status` and the fulfillment-side `fulfillment_status`".

        Design: Difficulty/non_linear_state_machine/order_payment_dimension_cycle_paid_partial_paid
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        pay = record_and_clear_payment(order["id"], 1000, method="CHECK")
        get_success_data(api.bounce_payment(pay["id"], TREAS))
        drained = get_success_data(api.get_order(order["id"], TREAS))
        assert drained["payment_status"] == "UNPAID"
        assert drained["fulfillment_status"] == "PENDING"


class TestPaymentGuardsAndTransitions:
    def test_overpayment_rejected(self, api):
        """PRD §3.2: "the new payment must not push the order's
        recorded-plus-cleared coverage above its `total_cents` — overpayment
        is rejected with `ERR_OVERPAYMENT`."

        Design: Corner/validations/overpayment_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        record_and_clear_payment(order["id"], 600, method="CASH")
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"], amount_cents=401,
                                   method="CASH"),
            TREAS)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)
        # Exactly the remaining 400 is admitted.
        ok = api.create_payment(
            create_payment_payload(order_id=order["id"], amount_cents=400,
                                   method="CASH"),
            TREAS)
        payment = validate_success(ok, 201)
        assert payment["status"] == "RECORDED"

    def test_payment_on_cancelled_order_state_beats_fiscal_rejected(self, api):
        """PRD §2.10: "Seventh, state-machine admission: the target entity —
        or, for creates, the related entity whose lifecycle gates creation —
        must be in a permitting state, else `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.10: "Twelfth and last, money guards: overpayment
        (`ERR_OVERPAYMENT`) and refunds exceeding remaining cleared value
        (`ERR_REFUND_EXCEEDS_CLEARED`)."

        Design: Difficulty/priority_pair_validation_conflict/payment_on_cancelled_order_state_beats_fiscal_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_order(seller["id"], product["id"], 1)
        get_success_data(api.cancel_order(order["id"], COORD))
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"], amount_cents=999999,
                                   method="CASH"),
            TREAS)
        # State admission (priority 7) masks the overpayment guard (priority 12).
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        payments, _meta = validate_paginated(
            api.list_order_payments(order["id"], TREAS))
        assert payments == [], "no payment row may persist after rejection"

    def test_payment_on_cancelled_order_never_overpayment(self, api):
        """PRD §3.2: "The order must be in `SUBMITTED`, `LOCKED`, or
        `COMPLETED` (else `ERR_INVALID_STATE`)".
        PRD §2.10: "checks run in a fixed priority order so that earlier
        failures mask later ones deterministically."

        Design: Difficulty/priority_pair_validation_conflict/payment_on_cancelled_order_state_beats_fiscal_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        get_success_data(api.cancel_order(order["id"], COORD))
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"], amount_cents=100,
                                   method="CASH"),
            TREAS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_bounce_recorded_payment_returns_invalid_state(self, api):
        """PRD §3.2: "A `CLEARED` check that bounces moves `CLEARED` →
        `BOUNCED`."
        PRD §2.10: "Seventh, state-machine admission: the target entity — or,
        for creates, the related entity whose lifecycle gates creation — must
        be in a permitting state, else `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/bounce_recorded_payment_returns_invalid_state
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        resp = api.create_payment(
            create_payment_payload(order_id=order["id"], amount_cents=1000,
                                   method="CHECK"),
            TREAS)
        payment = validate_success(resp, 201)
        assert payment["status"] == "RECORDED"
        bounce_resp = api.bounce_payment(payment["id"], TREAS)
        validate_error(bounce_resp, ApiErrorId.ERR_INVALID_STATE)

    def test_bounce_cash_payment_rejected(self, api):
        """PRD §3.2: "Bouncing is admitted only for payments whose `method` is
        `CHECK` (a bounce attempt on `CASH` or `CARD` is rejected with
        `ERR_PAYMENT_METHOD_NOT_BOUNCEABLE`)".

        Design: Corner/state_machines/bounce_cash_payment_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        payment = record_and_clear_payment(order["id"], 1000, method="CASH")
        resp = api.bounce_payment(payment["id"], TREAS)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_METHOD_NOT_BOUNCEABLE)
        after = get_success_data(api.list_order_payments(order["id"], TREAS))
        assert after[0]["status"] == "CLEARED"

    def test_refund_partial_then_exceeds_cleared_rejected(self, api):
        """PRD §3.2: "The refund supplies an `amount_cents` that must not
        exceed the payment's remaining un-refunded value — its `amount_cents`
        minus its `refunded_amount_cents` — else `ERR_REFUND_EXCEEDS_CLEARED`".
        PRD §3.2: "The refunded amount accumulates into
        `refunded_amount_cents`; when that accumulation reaches the payment's
        full `amount_cents` the payment moves to `REFUNDED`, otherwise it
        remains `CLEARED`."

        Design: Corner/validations/refund_partial_then_exceeds_cleared_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        payment = record_and_clear_payment(order["id"], 1000, method="CHECK")

        resp = api.refund_payment(payment["id"], {"amount_cents": 400}, TREAS2)
        refunded = validate_success(resp, 200)
        assert refunded["status"] == "CLEARED", (
            "a partial refund leaves the payment CLEARED")
        assert refunded["refunded_amount_cents"] == 400
        order_view = get_success_data(api.get_order(order["id"], TREAS))
        assert order_view["payment_status"] == "PARTIALLY_PAID"
        assert order_view["cleared_cents"] == 600

        over = api.refund_payment(payment["id"], {"amount_cents": 601}, TREAS2)
        validate_error(over, ApiErrorId.ERR_REFUND_EXCEEDS_CLEARED)

    def test_order_cancel_with_cleared_payment_rejected(self, api):
        """PRD §3.2: "Cancelling a `SUBMITTED` order is admitted only while
        the campaign is `OPEN` or `ORDERING_CLOSED` and only when the order's
        `cleared_cents` is zero (else `ERR_ORDER_HAS_CLEARED_PAYMENTS`)".

        Design: Corner/state_machines/order_cancel_with_cleared_payment_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        record_and_clear_payment(order["id"], 1000, method="CASH")
        resp = api.cancel_order(order["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_CLEARED_PAYMENTS)
        after = get_success_data(api.get_order(order["id"], COORD))
        assert after["status"] == "SUBMITTED"


class TestOrderCancellationCompensation:
    def test_submit_then_cancel_leaves_group_proceeds_unchanged(self, api):
        """PRD §3.2: "it posts the seller's group a single `PROVISIONAL_CREDIT`
        ledger entry referenced to the order".
        PRD §3.2: "it posts a `SALE_REVERSAL_DEBIT` to the seller's group equal
        to the order's `provisional_credit_cents`".

        Design: Difficulty/compensating_invariant/submit_then_cancel_leaves_group_proceeds_unchanged
        """
        reset_clock()
        _campaign, group, product, seller = setup_open_campaign_with_seller()
        before = get_success_data(api.get_group(group["id"], TREAS))
        assert before["proceeds_balance_cents"] == 0

        order = create_and_submit_order(seller["id"], product["id"], 3)
        mid = get_success_data(api.get_group(group["id"], TREAS))
        # round_half_up(3 * (1000-600) * 5000/10000) == 600
        assert mid["proceeds_balance_cents"] == 600
        assert mid["provisional_proceeds_cents"] == 600

        get_success_data(api.cancel_order(order["id"], COORD))
        after = get_success_data(api.get_group(group["id"], TREAS))
        assert after["proceeds_balance_cents"] == 0, (
            "submit then cancel must conserve the group proceeds balance")
        assert after["provisional_proceeds_cents"] == 0

    def test_submit_cancel_ledger_entry_pair(self, api):
        """PRD §3.2: "per line, the line's share is the line total minus the
        line's `quantity` times its snapshotted `unit_cost_cents`, multiplied
        by the product's `profit_share_bps` and divided by 10000, rounded half
        up to whole cents *per line*; the order's `provisional_credit_cents`
        is the sum of those rounded line shares, and that sum is the entry's
        `amount_cents`."
        PRD §2.7: "Entries for a group are replayed in `created_at` ascending
        order with `seq` ascending as the tie-break".

        Design: Difficulty/compensating_invariant/submit_then_cancel_leaves_group_proceeds_unchanged
        """
        reset_clock()
        _campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 3)
        get_success_data(api.cancel_order(order["id"], COORD))
        ledger = get_group_ledger(group["id"])
        assert [e["entry_type"] for e in ledger] == [
            "PROVISIONAL_CREDIT", "SALE_REVERSAL_DEBIT"]
        assert ledger[0]["amount_cents"] == 600
        assert ledger[0]["balance_after_cents"] == 600
        assert ledger[1]["amount_cents"] == -600
        assert ledger[1]["balance_after_cents"] == 0
        assert ledger[1]["reference_id"] == order["id"]


class TestIdempotency:
    def test_idempotency_replay_returns_same_order(self, api):
        """PRD §3.2: "an optional `idempotency_key` scoped to the endpoint and
        seller protects against duplicate submissions, and its replay rules
        follow §2.10."
        PRD §2.10: "Fourth, idempotency replay: an `idempotency_key`
        resubmitted to the same endpoint for the same seller (on order
        creation) or the same order (on payment recording) with a *different*
        payload than the original request is rejected with
        `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

        Design: Corner/complexity_layers/idempotency_replay_returns_same_order
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        payload = {
            "seller_id": seller["id"], "family_contact_name": "Fam1",
            "lines": [{"product_id": product["id"], "quantity": 1}],
            "idempotency_key": "K-1",
        }
        first = validate_success(api.create_order(payload, COORD), 201)
        second = validate_success(api.create_order(payload, COORD), 201)
        assert second["id"] == first["id"], (
            "an identical replay must return the original order")
        orders, meta = validate_paginated(
            api.list_orders(COORD, params={"seller_id": seller["id"]}))
        assert len(orders) == 1 and meta["total_count"] == 1, (
            "the replay must not create a second order")

    def test_idempotency_conflict_rejected(self, api):
        """PRD §2.10: "Fourth, idempotency replay: an `idempotency_key`
        resubmitted to the same endpoint for the same seller (on order
        creation) or the same order (on payment recording) with a *different*
        payload than the original request is rejected with
        `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

        Design: Corner/complexity_layers/idempotency_conflict_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        base = {
            "seller_id": seller["id"], "family_contact_name": "Fam1",
            "lines": [{"product_id": product["id"], "quantity": 1}],
            "idempotency_key": "K-1",
        }
        validate_success(api.create_order(base, COORD), 201)
        conflict = dict(base)
        conflict["lines"] = [{"product_id": product["id"], "quantity": 2}]
        resp = api.create_order(conflict, COORD)
        validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.2: "The order's `total_cents` is the sum of its lines'
        `line_total_cents`."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_order(seller["id"], product["id"], 2)
        resp = api.submit_order(order["id"], COORD)
        submitted = validate_success(resp, 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_cents"] == 2000, (
            "the submit response itself carries the computed total")
        # round_half_up(2 * 400 * 5000/10000) == 400
        assert submitted["provisional_credit_cents"] == 400
