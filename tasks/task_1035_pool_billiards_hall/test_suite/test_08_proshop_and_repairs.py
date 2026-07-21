"""Pro-shop inventory (sell / restock) and the repair-order pickup wallet debit."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_product_payload, create_repair_order_payload,
    make_member_headers,
)
from test_helpers import fixtures as fx


class TestProductInventory:
    def test_sell_decrements_stock(self, api):
        """PRD 3.6: "Selling subtracts a supplied qty from stock_qty and, when a member_id
        is supplied, debits unit_price_cents times qty from that member's wallet under the
        zero-floor rule."

        Sell qty 2 from stock 5 -> stock_qty 3.

        Design: Corner/endpoints/product_sell_decrements_stock
        """
        product = validate_success(
            api.create_product(
                create_product_payload(sku="REVO-1", name="Revo Cue", category="CUE",
                                       unit_price_cents=45000, stock_qty=5),
                TEST_USERS["proshop"],
            ),
            expected_status=201,
        )
        sold = validate_success(api.sell_product(product["id"], {"qty": 2}, TEST_USERS["proshop"]))
        assert sold["stock_qty"] == 3

    def test_sell_exceeding_stock_rejected_precondition(self, api):
        """PRD 3.6: "A sale is refused with ERR_PRECONDITION_NOT_MET when qty exceeds the
        available stock_qty".

        Selling qty 5 of a stock-1 product returns ERR_PRECONDITION_NOT_MET and stock is
        unchanged.

        Design: Corner/endpoints/product_sell_exceeds_stock_precondition
        """
        product = validate_success(
            api.create_product(
                create_product_payload(sku="CASE-1", name="2x4 Case", category="CASE",
                                       unit_price_cents=12000, stock_qty=1),
                TEST_USERS["proshop"],
            ),
            expected_status=201,
        )
        resp = api.sell_product(product["id"], {"qty": 5}, TEST_USERS["proshop"])
        validate_error(resp, ApiErrorId.ERR_PRECONDITION_NOT_MET.value)
        after = validate_success(api.get_product(product["id"], TEST_USERS["proshop"]))
        assert after["stock_qty"] == 1

    def test_restock_nonpositive_qty_rejected(self, api):
        """PRD 3.6: "a non-positive qty on a restock or sale, or a sale that would
        otherwise drive stock below zero, is an ERR_STOCK_NEGATIVE (422)".

        Design: Corner/endpoints/product_restock_nonpositive_qty_returns_stock_negative
        """
        product = validate_success(
            api.create_product(
                create_product_payload(sku="CHALK-1", name="Chalk", category="ACCESSORY",
                                       unit_price_cents=500, stock_qty=3),
                TEST_USERS["proshop"],
            ),
            expected_status=201,
        )
        resp = api.restock_product(product["id"], {"qty": 0}, TEST_USERS["proshop"])
        validate_error(resp, ApiErrorId.ERR_STOCK_NEGATIVE.value)


class TestRepairPickup:
    def test_pickup_debits_member_wallet_by_quote(self, api):
        """PRD 3.6: "A FrontDesk operator processes pickup of a READY order (READY ->
        PICKED_UP), which debits the quote_cents from the owning member's wallet under
        the zero-floor rule."

        CUE_RETIP quote 3000 driven to READY; pickup -> PICKED_UP, wallet 10000 - 3000
        = 7000.

        Design: Corner/endpoints/repair_flow_pickup_debits_member_wallet
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_funded_member(plan["id"], 10000)
        order = validate_success(
            api.create_repair_order(
                create_repair_order_payload(member_id=member["id"], service_type="CUE_RETIP",
                                            quote_cents=3000),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_repair(order["id"], TEST_USERS["proshop"]))
        validate_success(api.ready_repair(order["id"], TEST_USERS["proshop"]))
        picked = validate_success(api.pickup_repair(order["id"], TEST_USERS["frontdesk"]))
        assert picked["status"] == "PICKED_UP"
        after = validate_success(api.get_member(member["id"], TEST_USERS["manager"]))
        assert after["wallet_credit_cents"] == 7000
