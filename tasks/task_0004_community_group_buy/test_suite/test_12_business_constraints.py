"""Business-rule constraints: duplicate participation, customer status, after-sales window."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_community, create_supplier, create_customer, create_active_leader,
    create_group_buy_campaign, join_campaign, pay_order, close_campaign,
    setup_picked_up_order, setup_flash_scenario,
    file_after_sales, start_review, advance_clock,
    create_join_payload,
    create_after_sales_payload,
    create_flash_purchase_payload,
    ADMIN, make_customer_headers,
)


class TestDuplicateParticipation:

    def test_second_join_same_campaign_rejected(self, api):
        """PRD §3.4: "A customer may have at most one order in PENDING_PAY,
        PAID, SETTLED, or PARTIALLY_REFUNDED per campaign; a second join
        attempt is rejected with ERR_DUPLICATE_PARTICIPATION."

        Claim: a second join from the same customer to the same campaign
        while the first order is still in PENDING_PAY fails with
        ERR_DUPLICATE_PARTICIPATION.
        """
        community = create_community(name="C-DP", region_code="RC1")
        cust = create_customer(community["id"], display_name="C")
        supplier = create_supplier(name="S")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=100)
        join_campaign(campaign["id"], cust["id"],
                      line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        res = api.join_group_buy(
            campaign["id"],
            create_join_payload(cust["id"], sku="SKUA", unit_price_cents=100, quantity=1),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, "ERR_DUPLICATE_PARTICIPATION")


class TestCampaignNotOpen:

    def test_join_after_campaign_succeeded_rejected(self, api):
        """PRD §3.4: "Two further checks guard joining. The campaign must be
        in FORMING or EXTENDED ... otherwise the join is rejected with
        ERR_CAMPAIGN_NOT_OPEN."

        Claim: a join attempt after the campaign is no longer FORMING or
        EXTENDED (here: SUCCEEDED after close) returns ERR_CAMPAIGN_NOT_OPEN.
        """
        community = create_community(name="C-CN", region_code="RC1")
        cust1 = create_customer(community["id"], display_name="C1")
        cust2 = create_customer(community["id"], display_name="C2")
        supplier = create_supplier(name="S")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=100)
        order = join_campaign(campaign["id"], cust1["id"],
                              line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        pay_order(order["id"], cust1["id"])
        close_campaign(campaign["id"], leader["id"])  # SUCCEEDED
        res = api.join_group_buy(
            campaign["id"],
            create_join_payload(cust2["id"], sku="SKUA", unit_price_cents=100, quantity=1),
            make_customer_headers(cust2["id"]),
        )
        validate_error(res, "ERR_CAMPAIGN_NOT_OPEN")


class TestFlashStockDepleted:

    def test_request_more_than_remaining_units_rejected(self, api):
        """PRD §3.5: "Only after that state check does the anti-oversell
        check apply: if remaining_units is below requested_units, the
        request fails with ERR_FLASH_STOCK_DEPLETED."

        Claim: a flash purchase requesting more units than remain is
        rejected with ERR_FLASH_STOCK_DEPLETED.
        """
        sc = setup_flash_scenario(total_stock=2, tier_caps=[{"tier": 0, "max_units": 5}])
        res = api.flash_purchase(
            sc["flash_campaign"]["id"],
            create_flash_purchase_payload(requested_units=3),
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, "ERR_FLASH_STOCK_DEPLETED")


class TestAfterSalesWindow:

    def test_file_within_window_succeeds(self, api):
        """PRD §3.8: "the case may be filed only within seven periods after
        the parent order's fulfillment_status reaches PICKED_UP".

        Claim: filing a case immediately after PICKED_UP (within window)
        succeeds with HTTP 201.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        res = api.file_after_sales(
            sc["order"]["id"],
            create_after_sales_payload("REFUND_ONLY", 100),
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_success(res, 201)

    def test_file_after_window_expired_rejected(self, api):
        """PRD §3.8: "a later filing is rejected with ERR_AFTER_SALES_WINDOW_EXPIRED".

        Claim: filing a case after seven periods elapse from PICKED_UP is
        rejected with ERR_AFTER_SALES_WINDOW_EXPIRED.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        # Advance well past the 7-period window
        advance_clock(10)
        res = api.file_after_sales(
            sc["order"]["id"],
            create_after_sales_payload("REFUND_ONLY", 100),
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, "ERR_AFTER_SALES_WINDOW_EXPIRED")

    def test_amount_exceeds_remaining_rejected(self, api):
        """PRD §3.8: "The requested amount must be a positive integer and
        must not exceed the order's settled_total_cents minus its
        refunded_amount_cents; otherwise the rejection is
        ERR_AFTER_SALES_AMOUNT_EXCEEDS_REMAINING."

        Claim: filing a case with requested_amount_cents larger than the
        refundable remainder is rejected with
        ERR_AFTER_SALES_AMOUNT_EXCEEDS_REMAINING.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        # settled_total_cents=100, refunded=0 → max requestable = 100
        res = api.file_after_sales(
            sc["order"]["id"],
            create_after_sales_payload("REFUND_ONLY", 200),
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, "ERR_AFTER_SALES_AMOUNT_EXCEEDS_REMAINING")
