"""Incentive prizes: threshold qualification, stock-bounded awarding, the
QUEUED promotion queue, forfeiture cascades, and fulfillment."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_ordering_at_window_end,
    create_and_submit_order,
    create_group,
    create_prize,
    create_prize_payload,
    create_seller,
    create_submitted_paid_order,
    drive_campaign_to_sorted,
    get_group_ledger,
    get_success_data,
    list_seller_awards,
    record_and_clear_payment,
    reset_clock,
    setup_campaign_group_product,
    setup_open_campaign_with_seller,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]


class TestThresholdBoundary:
    def test_prize_threshold_exactly_met_qualifies(self, api):
        """PRD §3.8: "the seller qualifies when the metric is at least the
        prize's `threshold_value`, the boundary inclusive."
        PRD §3.1: "a strictly positive `threshold_value` the seller's metric
        must reach (the boundary is inclusive — a metric exactly equal to the
        threshold qualifies)".

        Design: Corner/calculations/prize_threshold_exactly_met_qualifies
        """
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        create_prize(campaign["id"], tier_type="REVENUE_CENTS",
                     threshold_value=2000, prize_cost_cents=0,
                     stock_quantity=5)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        order = create_and_submit_order(seller["id"], product["id"], 2)
        record_and_clear_payment(order["id"], 1999, method="CASH")
        awards = list_seller_awards(seller["id"])
        assert awards == [], (
            "revenue 1999 is below the 2000 threshold: no award")

        record_and_clear_payment(order["id"], 1, method="CASH")
        awards = list_seller_awards(seller["id"])
        assert len(awards) == 1
        assert awards[0]["status"] == "AWARDED"
        assert awards[0]["qualifying_metric_value"] == 2000, (
            "revenue exactly 2000 qualifies — the boundary is inclusive")

    def test_one_below_threshold_never_qualifies(self, api):
        """PRD §3.8: "the seller qualifies when the metric is at least the
        prize's `threshold_value`, the boundary inclusive."

        Design: Corner/calculations/prize_threshold_exactly_met_qualifies
        """
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        create_prize(campaign["id"], tier_type="UNITS_SOLD",
                     threshold_value=3, prize_cost_cents=0, stock_quantity=5)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_and_submit_order(seller["id"], product["id"], 2)
        assert list_seller_awards(seller["id"]) == []
        create_and_submit_order(seller["id"], product["id"], 1,
                                family_contact_name="Fam2")
        awards = list_seller_awards(seller["id"])
        assert len(awards) == 1 and awards[0]["status"] == "AWARDED", (
            "units 2 then 3: the third unit crosses the inclusive threshold")


class TestStockConservation:
    def test_award_then_forfeit_conserves_prize_stock(self, api):
        """PRD §3.1: "The prize's computed `remaining_quantity` is its
        `stock_quantity` minus the count of its awards in `AWARDED` or
        `FULFILLED`."
        PRD §3.8: "`AWARDED` forfeiture posts a `PRIZE_COST_REVERSAL`
        crediting the `prize_cost_cents` back to the seller's group, restores
        the stock".

        Design: Difficulty/compensating_invariant/award_then_forfeit_conserves_prize_stock
        """
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        prize = create_prize(campaign["id"], tier_type="UNITS_SOLD",
                             threshold_value=2, prize_cost_cents=25,
                             stock_quantity=1)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))

        before = get_success_data(api.get_prize(prize["id"], ADMIN))
        assert before["remaining_quantity"] == 1

        order = create_and_submit_order(seller["id"], product["id"], 2)
        awards = list_seller_awards(seller["id"])
        assert len(awards) == 1 and awards[0]["status"] == "AWARDED"
        mid = get_success_data(api.get_prize(prize["id"], ADMIN))
        assert mid["remaining_quantity"] == 0, "1 - 1 AWARDED"

        get_success_data(api.cancel_order(order["id"], COORD))
        award_after = get_success_data(
            api.get_prize_award(awards[0]["id"], ADMIN))
        assert award_after["status"] == "FORFEITED", (
            "the cancel drops units_sold to 0, below the threshold")
        final = get_success_data(api.get_prize(prize["id"], ADMIN))
        assert final["remaining_quantity"] == 1, (
            "stock is restored — conservation holds at every checkpoint")

    def test_award_forfeit_ledger_returns_to_zero(self, api):
        """PRD §3.8: "if the prize's `remaining_quantity` is greater than
        zero, the award is created directly in `AWARDED`, a `PRIZE_COST_DEBIT`
        of the prize's `prize_cost_cents` is posted to the seller's group".
        PRD §3.8: "`AWARDED` forfeiture posts a `PRIZE_COST_REVERSAL`
        crediting the `prize_cost_cents` back to the seller's group".

        Design: Difficulty/compensating_invariant/award_then_forfeit_conserves_prize_stock
        """
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        create_prize(campaign["id"], tier_type="UNITS_SOLD", threshold_value=2,
                     prize_cost_cents=25, stock_quantity=1)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        order = create_and_submit_order(seller["id"], product["id"], 2)
        get_success_data(api.cancel_order(order["id"], COORD))
        ledger = get_group_ledger(group["id"])
        types = [e["entry_type"] for e in ledger]
        assert types == ["PROVISIONAL_CREDIT", "PRIZE_COST_DEBIT",
                         "SALE_REVERSAL_DEBIT", "PRIZE_COST_REVERSAL"]
        assert [e["amount_cents"] for e in ledger] == [400, -25, -400, 25]
        group_view = get_success_data(api.get_group(group["id"], TREAS))
        assert group_view["proceeds_balance_cents"] == 0


class TestBounceForfeitPromotionCascade:
    def test_payment_bounce_cascade_to_prize_forfeit_and_promotion(self, api):
        """PRD §3.8: "When a recompute finds a seller no longer qualifying —
        metric fallen below the threshold after a bounce, refund, cancel,
        return, or claim — an award in `QUEUED` or `AWARDED` moves to
        `FORFEITED`: `QUEUED` forfeiture is silent, while `AWARDED` forfeiture
        posts a `PRIZE_COST_REVERSAL` crediting the `prize_cost_cents` back to
        the seller's group, restores the stock, and then promotes the head of
        that prize's `QUEUED` queue — provided the head still qualifies —
        moving it to `AWARDED` and posting its own `PRIZE_COST_DEBIT` to the
        promoted seller's group."

        Design: Difficulty/transitive_cascade/payment_bounce_cascade_to_prize_forfeit_and_promotion
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign({
            "name": "Fall Sale", "school_name": "Lincoln",
            "order_window_start": "2026-08-01T00:00:00Z",
            "order_window_end": "2026-08-20T00:00:00Z",
            "expected_delivery_date": "2026-09-05T00:00:00Z",
            "default_profit_share_bps": 5000,
        }, ADMIN))
        group_a = create_group(campaign["id"], name="Group A")
        group_b = create_group(campaign["id"], name="Group B")
        from test_helpers import create_product
        product = create_product(campaign["id"])
        prize = create_prize(campaign["id"], name="iPad",
                             tier_type="REVENUE_CENTS", threshold_value=2000,
                             prize_cost_cents=100, stock_quantity=1)
        seller_a = create_seller(group_a["id"], display_name="Alice")
        seller_b = create_seller(group_b["id"], display_name="Bobby")
        get_success_data(api.open_campaign(campaign["id"], ADMIN))

        # Seller A qualifies first and takes the only stock via a CHECK.
        order_a = create_and_submit_order(seller_a["id"], product["id"], 2)
        pay_a = record_and_clear_payment(order_a["id"], 2000, method="CHECK")
        awards_a = list_seller_awards(seller_a["id"])
        assert len(awards_a) == 1 and awards_a[0]["status"] == "AWARDED"

        # Seller B qualifies into the empty-stock queue.
        order_b = create_and_submit_order(seller_b["id"], product["id"], 2)
        record_and_clear_payment(order_b["id"], 2000, method="CASH")
        awards_b = list_seller_awards(seller_b["id"])
        assert len(awards_b) == 1 and awards_b[0]["status"] == "QUEUED"

        # The bounce: A's revenue collapses to 0, forfeiting the prize.
        get_success_data(api.bounce_payment(pay_a["id"], TREAS))
        award_a_after = get_success_data(
            api.get_prize_award(awards_a[0]["id"], ADMIN))
        assert award_a_after["status"] == "FORFEITED"
        award_b_after = get_success_data(
            api.get_prize_award(awards_b[0]["id"], ADMIN))
        assert award_b_after["status"] == "AWARDED", (
            "the freed stock promotes the queued head")
        order_a_view = get_success_data(api.get_order(order_a["id"], TREAS))
        assert order_a_view["payment_status"] == "UNPAID"
        prize_view = get_success_data(api.get_prize(prize["id"], ADMIN))
        assert prize_view["remaining_quantity"] == 0, (
            "the single unit moved from seller A to seller B")

    def test_bounce_cascade_posts_reversal_and_promotion_debit(self, api):
        """PRD §3.8: "`AWARDED` forfeiture posts a `PRIZE_COST_REVERSAL`
        crediting the `prize_cost_cents` back to the seller's group, restores
        the stock, and then promotes the head of that prize's `QUEUED` queue —
        provided the head still qualifies — moving it to `AWARDED` and posting
        its own `PRIZE_COST_DEBIT` to the promoted seller's group."
        PRD §3.2: "a `BOUNCE_FEE_DEBIT` entry for the fixed bounce fee is
        posted to the order's group".

        Design: Difficulty/transitive_cascade/payment_bounce_cascade_to_prize_forfeit_and_promotion
        """
        reset_clock()
        campaign = get_success_data(api.create_campaign({
            "name": "Fall Sale", "school_name": "Lincoln",
            "order_window_start": "2026-08-01T00:00:00Z",
            "order_window_end": "2026-08-20T00:00:00Z",
            "expected_delivery_date": "2026-09-05T00:00:00Z",
            "default_profit_share_bps": 5000,
        }, ADMIN))
        group_a = create_group(campaign["id"], name="Group A")
        group_b = create_group(campaign["id"], name="Group B")
        from test_helpers import create_product
        product = create_product(campaign["id"])
        create_prize(campaign["id"], name="iPad", tier_type="REVENUE_CENTS",
                     threshold_value=2000, prize_cost_cents=100,
                     stock_quantity=1)
        seller_a = create_seller(group_a["id"], display_name="Alice")
        seller_b = create_seller(group_b["id"], display_name="Bobby")
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        order_a = create_and_submit_order(seller_a["id"], product["id"], 2)
        pay_a = record_and_clear_payment(order_a["id"], 2000, method="CHECK")
        order_b = create_and_submit_order(seller_b["id"], product["id"], 2)
        record_and_clear_payment(order_b["id"], 2000, method="CASH")
        get_success_data(api.bounce_payment(pay_a["id"], TREAS))

        ledger_a = get_group_ledger(group_a["id"])
        types_a = [e["entry_type"] for e in ledger_a]
        assert types_a == ["PROVISIONAL_CREDIT", "PRIZE_COST_DEBIT",
                           "BOUNCE_FEE_DEBIT", "PRIZE_COST_REVERSAL"], (
            f"group A ledger order: {types_a}")
        amounts_a = [e["amount_cents"] for e in ledger_a]
        assert amounts_a[0] == 400 and amounts_a[1] == -100
        assert amounts_a[2] < 0, "the bounce fee debit is negative"
        assert amounts_a[3] == 100, "reversal credits the prize cost back"

        ledger_b = get_group_ledger(group_b["id"])
        types_b = [e["entry_type"] for e in ledger_b]
        assert types_b == ["PROVISIONAL_CREDIT", "PRIZE_COST_DEBIT"]
        group_b_view = get_success_data(api.get_group(group_b["id"], TREAS))
        # +400 provisional, -100 promoted prize cost.
        assert group_b_view["proceeds_balance_cents"] == 300


class TestReturnReceiveForfeitCascade:
    def test_return_receive_cascade_to_fulfillment_and_forfeit(self, api):
        """PRD §3.8: "When a recompute finds a seller no longer qualifying —
        metric fallen below the threshold after a bounce, refund, cancel,
        return, or claim — an award in `QUEUED` or `AWARDED` moves to
        `FORFEITED`".
        PRD §3.6: "Either receipt recomputes the order's fulfillment status,
        recomputes seller metrics, and re-runs prize evaluation — with
        possible forfeiture and queue promotion."

        Design: Difficulty/transitive_cascade/return_receive_cascade_to_fulfillment_and_forfeit
        """
        from test_helpers import (
            create_received_return, get_order_line_id,
            drive_campaign_to_distribution_complete)
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        create_prize(campaign["id"], name="Badge", tier_type="UNITS_SOLD",
                     threshold_value=3, prize_cost_cents=50, stock_quantity=1)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        order = create_submitted_paid_order(seller["id"], product["id"], 3)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_distribution_complete(
            campaign["id"], product["id"], 12)
        awards = list_seller_awards(seller["id"])
        assert len(awards) == 1 and awards[0]["status"] == "AWARDED", (
            "the distribution sweep grants the prize at exactly 3 units")

        reset_clock("2026-09-11T12:00:00Z")
        line_id = get_order_line_id(order["id"])
        create_received_return(seller["id"], order["id"], line_id, 1,
                               "DEFECTIVE", "RESTOCKABLE")
        award_after = get_success_data(
            api.get_prize_award(awards[0]["id"], ADMIN))
        assert award_after["status"] == "FORFEITED"
        order_view = get_success_data(api.get_order(order["id"], TREAS))
        assert order_view["fulfillment_status"] == "PARTIALLY_RETURNED"
        seller_view = get_success_data(api.get_seller(seller["id"], COORD))
        assert seller_view["units_sold"] == 2, "3 - 1 returned"

    def test_return_receive_forfeit_ledger_arithmetic(self, api):
        """PRD §3.6: "posts a `RETURN_DEBIT` to the seller's group equal to
        the quantity times the difference between the line's snapshotted
        `unit_price_cents` and `unit_cost_cents`, multiplied by the product's
        `profit_share_bps` and divided by 10000, rounded half up to whole
        cents."
        PRD §3.8: "`AWARDED` forfeiture posts a `PRIZE_COST_REVERSAL`
        crediting the `prize_cost_cents` back to the seller's group".

        Design: Difficulty/transitive_cascade/return_receive_cascade_to_fulfillment_and_forfeit
        """
        from test_helpers import (
            create_received_return, get_order_line_id,
            drive_campaign_to_distribution_complete)
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        create_prize(campaign["id"], name="Badge", tier_type="UNITS_SOLD",
                     threshold_value=3, prize_cost_cents=50, stock_quantity=1)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        order = create_submitted_paid_order(seller["id"], product["id"], 3)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_distribution_complete(
            campaign["id"], product["id"], 12)
        reset_clock("2026-09-11T12:00:00Z")
        line_id = get_order_line_id(order["id"])
        create_received_return(seller["id"], order["id"], line_id, 1,
                               "DEFECTIVE", "RESTOCKABLE")
        group_view = get_success_data(api.get_group(group["id"], TREAS))
        # +600 provisional, -50 prize, +50 reversal,
        # -200 return debit (round_half_up(1 * 400 * 5000/10000)).
        assert group_view["proceeds_balance_cents"] == 400
        ledger = get_group_ledger(group["id"])
        types = [e["entry_type"] for e in ledger]
        assert "RETURN_DEBIT" in types and "PRIZE_COST_REVERSAL" in types


class TestAwardFulfillment:
    def test_prize_fulfill_happy_path_and_queued_rejected(self, api):
        """PRD §3.8: "Awards in `AWARDED` are handed over physically when a
        coordinator fulfills them — admitted while the campaign is `SORTED`,
        `DISTRIBUTION_COMPLETE`, `RECONCILED`, or `CLOSED` (else
        `ERR_INVALID_STATE`) — moving the award to `FULFILLED`."
        PRD §2.10: "Seventh, state-machine admission: the target entity — or,
        for creates, the related entity whose lifecycle gates creation — must
        be in a permitting state, else `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/prize_fulfill_happy_path_and_queued_rejected
        """
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        create_prize(campaign["id"], name="Badge", tier_type="UNITS_SOLD",
                     threshold_value=1, prize_cost_cents=25, stock_quantity=1)
        seller_a = create_seller(group["id"], display_name="Alice")
        seller_b = create_seller(group["id"], display_name="Bobby")
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_and_submit_order(seller_a["id"], product["id"], 1)
        create_and_submit_order(seller_b["id"], product["id"], 1)
        award_a = list_seller_awards(seller_a["id"])[0]
        award_b = list_seller_awards(seller_b["id"])[0]
        assert award_b["status"] == "QUEUED", (
            "stock held by Alice; Bobby queues")

        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"], 12)
        fulfilled = get_success_data(
            api.fulfill_prize_award(award_a["id"], COORD))
        assert fulfilled["status"] == "FULFILLED"
        blocked = api.fulfill_prize_award(award_b["id"], COORD)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)


class TestWithdrawalCascade:
    def test_withdraw_cascades_order_cancel_and_award_forfeit(self, api):
        """PRD §3.1: "Withdrawal cascades: the seller's DRAFT and SUBMITTED
        orders are cancelled (SUBMITTED ones posting their reversal per §3.3),
        and the seller's prize awards in `QUEUED` or `AWARDED` move to
        `FORFEITED`, restoring stock, posting `PRIZE_COST_REVERSAL` for
        `AWARDED` ones, and running queue promotion per §3.8."

        Design: Corner/state_machines/withdraw_cascades_order_cancel_and_award_forfeit
        """
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        prize = create_prize(campaign["id"], name="Badge",
                             tier_type="UNITS_SOLD", threshold_value=1,
                             prize_cost_cents=25, stock_quantity=1)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        order = create_and_submit_order(seller["id"], product["id"], 1)
        award = list_seller_awards(seller["id"])[0]
        assert award["status"] == "AWARDED"

        get_success_data(api.withdraw_seller(seller["id"], COORD))
        order_after = get_success_data(api.get_order(order["id"], COORD))
        assert order_after["status"] == "CANCELLED"
        award_after = get_success_data(api.get_prize_award(award["id"], ADMIN))
        assert award_after["status"] == "FORFEITED"
        prize_view = get_success_data(api.get_prize(prize["id"], ADMIN))
        assert prize_view["remaining_quantity"] == 1, "stock restored"
        group_view = get_success_data(api.get_group(group["id"], TREAS))
        # +200 provisional, -25 prize, -200 sale reversal, +25 prize reversal.
        assert group_view["proceeds_balance_cents"] == 0
