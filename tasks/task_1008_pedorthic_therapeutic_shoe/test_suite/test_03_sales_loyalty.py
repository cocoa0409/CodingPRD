"""Sales: loyalty accrual (round-per-line-then-sum), provisional-vs-net after a return,
the independent payment/fulfillment axes, and the reserve/release inventory invariant."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]


class TestLoyaltyProvisionalVsNetAfterReturn:
    """Provisional loyalty minted at fulfill (176) diverges from the balance after the
    45.50 line is returned and reversed (130)."""

    def test_provisional_points_minted_at_fulfill(self, api):
        """PRD §3.4: "For each `ACTIVE` line, its `line_total_cents` divided by 100 is
        multiplied by the multiplier and rounded half up to whole points; those per-line
        point values are then summed. The order is contractual: round each line, then sum
        — not sum then round."

        Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_net_after_return
        """
        ctx = fx.setup_two_line_sale(priceA=12950, priceB=4550, fulfill=True)
        # BRONZE x1.00: round(129.50)=130 + round(45.50)=46 = 176
        assert ctx["sale"]["loyalty_points_earned"] == 176

    def test_reversal_lowers_balance_after_return(self, api):
        """PRD §3.5: "reverses loyalty by minting a `REVERSAL` ledger entry whose
        `points_delta` is the negative of the line's earned points — the `line_total_cents`
        divided by 100, multiplied by the multiplier for the sale's `loyalty_tier_at_fulfill`,
        rounded half up."
        PRD §3.2: "Their `loyalty_points_balance` is the sum of `points_delta` across all
        of their ledger entries."

        Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_net_after_return
        """
        ctx = fx.setup_two_line_sale(priceA=12950, priceB=4550, fulfill=True)
        ret = fx.create_and_approve_return(ctx["sale"]["id"], ctx["lineB"]["id"], return_type="RETURN")
        fx.refund_return(ret["id"])
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], SM))
        # 176 - round(45.50 * 1.00) = 176 - 46 = 130
        assert customer["loyalty_points_balance"] == 130


class TestLoyaltyRoundPerLineThenSum:
    """The pinned rounding order (round-per-line then sum) yields 176, not 175."""

    def test_earned_points_use_round_per_line_then_sum(self, api):
        """PRD §3.4: "For each `ACTIVE` line, its `line_total_cents` divided by 100 is
        multiplied by the multiplier and rounded half up to whole points; those per-line
        point values are then summed. The order is contractual: round each line, then sum
        — not sum then round."

        Design: Difficulty/combinatorial_formula/loyalty_round_per_line_then_sum
        """
        ctx = fx.setup_two_line_sale(priceA=12950, priceB=4550, fulfill=True)
        assert ctx["sale"]["loyalty_points_earned"] == 176

    def test_loyalty_tier_snapshotted_at_fulfill(self, api):
        """PRD §3.4: "the customer's current `loyalty_tier` is snapshotted into
        `loyalty_tier_at_fulfill`; and loyalty accrual runs to set `loyalty_points_earned`
        and mint an `EARN` ledger entry carrying those points and the `sale_id`."

        Design: Difficulty/combinatorial_formula/loyalty_round_per_line_then_sum
        """
        ctx = fx.setup_two_line_sale(priceA=12950, priceB=4550, fulfill=True)
        assert ctx["sale"]["loyalty_tier_at_fulfill"] == "BRONZE"


class TestParallelPaymentAndFulfillmentAxes:
    """payment_status and fulfillment_status move independently on the same sale row."""

    def test_pay_advances_payment_axis_only(self, api):
        """PRD §3.4: "paying a sale advances `payment_status` from `UNPAID` to `PAID` and
        requires that the body's `amount_tendered_cents` be at least the sale's
        `subtotal_cents`."
        PRD §3.4: "A sale carries two independent axes. Its `payment_status` evolves
        `UNPAID` → `PAID` → `REFUNDED`; its `fulfillment_status` evolves `PENDING` →
        `FULFILLED`... The two axes move independently."

        Design: Difficulty/non_linear_state_machine/sale_parallel_payment_and_fulfillment_axes
        """
        ctx = fx.setup_one_line_sale(price=8000, fulfill=False)
        paid = validate_success(api.pay_sale(
            ctx["sale"]["id"], {"amount_tendered_cents": 8000}, ctx["fitter_headers"]))
        assert paid["payment_status"] == "PAID"
        assert paid["fulfillment_status"] == "PENDING"

    def test_fulfill_advances_fulfillment_axis_leaving_payment(self, api):
        """PRD §3.4: "Fulfilling a sale advances `fulfillment_status` from `PENDING` to
        `FULFILLED`."
        PRD §3.4: "The two axes move independently."

        Design: Difficulty/non_linear_state_machine/sale_parallel_payment_and_fulfillment_axes
        """
        ctx = fx.setup_one_line_sale(price=8000, fulfill=False)
        fx.api.pay_sale(ctx["sale"]["id"], {"amount_tendered_cents": 8000}, ctx["fitter_headers"])
        fulfilled = validate_success(api.fulfill_sale(ctx["sale"]["id"], ctx["fitter_headers"]))
        assert fulfilled["fulfillment_status"] == "FULFILLED"
        assert fulfilled["payment_status"] == "PAID"


class TestInventoryReserveReleaseInvariant:
    """quantity_available (= on_hand - reserved) is conserved: reserving 2 then cancelling
    the sale releases the reservation with physical on_hand untouched."""

    def test_cancel_releases_reservation_without_touching_on_hand(self, api):
        """PRD §3.4: "Cancelling a sale is permitted only while `fulfillment_status` is
        `PENDING`; it moves the sale to `CANCELLED` and, for each `ACTIVE` line, releases
        the reservation by decreasing the item's `quantity_reserved` while leaving
        `quantity_on_hand` untouched, restoring `quantity_available`."

        Design: Difficulty/compensating_invariant/inventory_availability_conserved_reserve_release
        """
        ctx = fx.setup_one_line_sale(price=6000, on_hand=5, line_qty=2, fulfill=False)
        validate_success(api.cancel_sale(ctx["sale"]["id"], ctx["fitter_headers"]))
        inv = get_success_data(api.get_inventory_item(ctx["inventory"]["id"], SM))
        assert inv["quantity_reserved"] == 0
        assert inv["quantity_on_hand"] == 5

    def test_available_restored_after_cancel(self, api):
        """PRD §2.10: "its `quantity_available` is always `quantity_on_hand` minus
        `quantity_reserved` and is never stored independently. Adding a sale line reserves
        stock; cancelling the sale releases that reservation."

        Design: Difficulty/compensating_invariant/inventory_availability_conserved_reserve_release
        """
        ctx = fx.setup_one_line_sale(price=6000, on_hand=5, line_qty=2, fulfill=False)
        mid = get_success_data(api.get_inventory_item(ctx["inventory"]["id"], SM))
        assert mid["quantity_available"] == 3, "5 on_hand - 2 reserved = 3 while line is ACTIVE"
        validate_success(api.cancel_sale(ctx["sale"]["id"], ctx["fitter_headers"]))
        inv = get_success_data(api.get_inventory_item(ctx["inventory"]["id"], SM))
        assert inv["quantity_available"] == 5


class TestSaleLineZeroAvailabilityBoundary:
    """A one-unit item fully reserved by a prior sale line (available exactly 0) rejects a
    new one-unit line."""

    def _scene(self):
        fx.set_clock()
        prod = fx.create_product(name="Scarce", brand="X", category="REGULAR", base_price_cents=9000)
        inv = fx.create_inventory(prod["id"], lot_number="S1", quantity_on_hand=1)
        cust = fx.create_customer(full_name="Empty", date_of_birth="1972-02-02")
        fitter = fx.create_fitter(full_name="Fm")
        fh = fx.make_fitter_headers(fitter["id"])
        sale1 = fx.open_sale(cust["id"], fitter["id"], fh)
        fx.add_line(sale1["id"], inv["id"], fh)  # reserves the sole unit -> available 0
        sale2 = fx.open_sale(cust["id"], fitter["id"], fh)
        return inv, sale2, fh

    def test_new_line_rejected_when_available_zero(self, api):
        """PRD §3.4: "Finally, the item's `quantity_available` must be at least the
        requested `quantity`, else `ERR_OUT_OF_STOCK`."

        Design: Difficulty/boundary_precision_check/sale_line_zero_availability_boundary
        """
        inv, sale2, fh = self._scene()
        resp = api.add_sale_line(sale2["id"], {"inventory_item_id": inv["id"], "quantity": 1}, fh)
        validate_error(resp, ApiErrorId.ERR_OUT_OF_STOCK.value)

    def test_available_is_zero_after_first_reservation(self, api):
        """PRD §2.10: "its `quantity_available` is always `quantity_on_hand` minus
        `quantity_reserved` and is never stored independently. Adding a sale line reserves
        stock."

        Design: Difficulty/boundary_precision_check/sale_line_zero_availability_boundary
        """
        inv, _sale2, _fh = self._scene()
        fetched = get_success_data(api.get_inventory_item(inv["id"], SM))
        assert fetched["quantity_available"] == 0


def test_inventory_quantity_available_is_computed(api):
    """PRD §3.1: "The item also holds a system `quantity_reserved` (starting at 0), the
    computed `quantity_available`, and a lifecycle `status` that begins `AVAILABLE`."
    PRD §2.10: "its `quantity_available` is always `quantity_on_hand` minus
    `quantity_reserved` and is never stored independently."

    Design: Corner/entities/inventory_quantity_available_is_computed
    """
    prod = fx.create_product(name="Avail", brand="X", category="REGULAR", base_price_cents=5000)
    inv = validate_success(api.create_inventory_item(
        {"product_id": prod["id"], "size": 9.0, "width": "D", "lot_number": "AV",
         "quantity_on_hand": 4}, TEST_USERS["store_manager_headers"]), expected_status=201)
    assert inv["quantity_available"] == 4
    assert inv["quantity_reserved"] == 0
    assert inv["status"] == "AVAILABLE"
