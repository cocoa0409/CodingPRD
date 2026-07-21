"""Food & beverage tabs: per-line-then-sum tax computation, wallet debit, and void."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_fnb_order_payload,
)
from test_helpers import fixtures as fx


class TestFnbTotals:
    def _open_tab(self, api, member_id):
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        session = fx.open_walkin_session(table["id"], member_id=member_id)
        resp = api.create_fnb_order(
            create_fnb_order_payload(
                session_id=session["id"], member_id=member_id,
                line_items=[{"name": "Cola", "unit_price_cents": 60, "qty": 1},
                            {"name": "Water", "unit_price_cents": 60, "qty": 1}],
            ),
            TEST_USERS["frontdesk"],
        )
        return validate_success(resp, expected_status=201)

    def test_tax_rounded_per_line_then_summed(self, api):
        """PRD 3.4: "The subtotal_cents is the sum over the line items of unit_price_cents
        times qty. Tax is computed per line and then summed: for each line item, multiply
        unit_price_cents by qty by the food-and-beverage tax rate of 8.75 percent (0.0875)
        and round that line's tax half up to a whole cent; tax_cents is the sum of those
        per-line rounded amounts." "The total_cents is subtotal_cents plus tax_cents."

        Two 60-cent lines: round(60*0.0875)=round(5.25)=5 each -> tax 10; total 130.

        Design: Difficulty/combinatorial_formula/fnb_total_round_per_line_then_sum_mode_b
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_funded_member(plan["id"], 100_000)
        order = self._open_tab(api, member["id"])
        submitted = validate_success(api.submit_fnb_order(order["id"], TEST_USERS["frontdesk"]))
        assert submitted["subtotal_cents"] == 120
        assert submitted["tax_cents"] == 10
        assert submitted["total_cents"] == 130

    def test_submit_debits_member_wallet_by_total(self, api):
        """PRD 3.4: "When the tab has a member_id, submission debits total_cents from
        that member's wallet, subject to the zero-floor rule."

        Design: Difficulty/combinatorial_formula/fnb_total_round_per_line_then_sum_mode_b
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_funded_member(plan["id"], 100_000)
        order = self._open_tab(api, member["id"])
        validate_success(api.submit_fnb_order(order["id"], TEST_USERS["frontdesk"]))
        after = validate_success(api.get_member(member["id"], TEST_USERS["manager"]))
        assert after["wallet_credit_cents"] == 100_000 - 130


class TestFnbVoid:
    def test_void_open_tab_succeeds(self, api):
        """PRD 3.4: "A FrontDesk operator may instead void an OPEN tab (OPEN -> VOIDED),
        which charges nothing."

        Design: Corner/endpoints/fnb_void_from_open_succeeds
        """
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        session = fx.open_walkin_session(table["id"])
        order = validate_success(
            api.create_fnb_order(
                create_fnb_order_payload(
                    session_id=session["id"],
                    line_items=[{"name": "Chips", "unit_price_cents": 300, "qty": 1}],
                ),
                TEST_USERS["frontdesk"],
            ),
            expected_status=201,
        )
        voided = validate_success(api.void_fnb_order(order["id"], TEST_USERS["frontdesk"]))
        assert voided["status"] == "VOIDED"
