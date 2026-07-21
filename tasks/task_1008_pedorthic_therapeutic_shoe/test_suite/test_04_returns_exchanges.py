"""Returns and exchanges: the refund restock/bubble/reversal cascade, the fulfilled-sale
precondition, restocking-fee arithmetic, the exchange swap, and type-mismatch guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]


class TestReturnRefundCascade:
    """A refund on one line of a two-line fulfilled sale restocks inventory, bubbles the
    sale to PARTIALLY_RETURNED, and reverses loyalty."""

    def test_refund_flips_line_and_restocks_inventory(self, api):
        """PRD §3.5: "The refund also flips the sale line from `ACTIVE` to `RETURNED`,
        restocks the item by increasing its `quantity_on_hand` by the line quantity, and
        reverses loyalty by minting a `REVERSAL` ledger entry whose `points_delta` is the
        negative of the line's earned points."

        Design: Difficulty/transitive_cascade/return_refund_restock_bubble_reversal_chain
        """
        ctx = fx.setup_two_line_sale(priceA=10000, priceB=4000, invA_on_hand=5,
                                     invB_on_hand=5, dob="1958-08-08", fulfill=True)
        ret = fx.create_and_approve_return(ctx["sale"]["id"], ctx["lineA"]["id"], return_type="RETURN")
        fx.refund_return(ret["id"])
        line_a = get_success_data(api.get_sale_line(ctx["lineA"]["id"], SM))
        inv_a = get_success_data(api.get_inventory_item(ctx["invA"]["id"], SM))
        assert line_a["status"] == "RETURNED"
        assert inv_a["quantity_on_hand"] == 5, "fulfil 5->4 then refund restock 4->5"

    def test_refund_bubbles_sale_status_and_reverses_loyalty(self, api):
        """PRD §3.5: "The sale's `fulfillment_status` then recomputes by bubble-up: it
        becomes `PARTIALLY_RETURNED` while at least one `ACTIVE` line remains, and
        `RETURNED` once the last `ACTIVE` line has flipped."
        PRD §3.2: "Their `loyalty_points_balance` is the sum of `points_delta` across all
        of their ledger entries."

        Design: Difficulty/transitive_cascade/return_refund_restock_bubble_reversal_chain
        """
        ctx = fx.setup_two_line_sale(priceA=10000, priceB=4000, invA_on_hand=5,
                                     invB_on_hand=5, dob="1958-08-08", fulfill=True)
        ret = fx.create_and_approve_return(ctx["sale"]["id"], ctx["lineA"]["id"], return_type="RETURN")
        fx.refund_return(ret["id"])
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], SM))
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], SM))
        assert sale["fulfillment_status"] == "PARTIALLY_RETURNED"
        # earned 140 (100 + 40); reversal of line A = -100 -> balance 40
        assert customer["loyalty_points_balance"] == 40


class TestReturnApproveRequiresFulfilledSale:
    """Approving a return is blocked while the underlying sale is still PENDING."""

    def test_approve_blocked_on_pending_sale(self, api):
        """PRD §3.5: "Approval advances `REQUESTED` to `APPROVED` and requires that the
        underlying sale's `fulfillment_status` be either `FULFILLED` or
        `PARTIALLY_RETURNED` (else `ERR_SALE_NOT_FULFILLED`)."

        Design: Difficulty/cross_entity_state_dependency/return_approve_requires_sale_fulfilled
        """
        ctx = fx.setup_one_line_sale(price=7000, fulfill=False, dob="1968-06-06")
        ret = get_success_data(api.create_return(
            {"sale_id": ctx["sale"]["id"], "sale_line_id": ctx["line"]["id"],
             "return_type": "RETURN"}, SM))
        resp = api.approve_return(ret["id"], SM)
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_FULFILLED.value)

    def test_approve_succeeds_once_sale_fulfilled(self, api):
        """PRD §3.5: "Approval advances `REQUESTED` to `APPROVED` and requires that the
        underlying sale's `fulfillment_status` be either `FULFILLED` or
        `PARTIALLY_RETURNED` (else `ERR_SALE_NOT_FULFILLED`)."

        Design: Difficulty/cross_entity_state_dependency/return_approve_requires_sale_fulfilled
        """
        ctx = fx.setup_one_line_sale(price=7000, fulfill=True, dob="1968-06-06")
        ret = get_success_data(api.create_return(
            {"sale_id": ctx["sale"]["id"], "sale_line_id": ctx["line"]["id"],
             "return_type": "RETURN"}, SM))
        approved = validate_success(api.approve_return(ret["id"], SM))
        assert approved["status"] == "APPROVED"


def test_restocking_fee_applied_outside_return_window(api):
    """PRD §3.5: "the restocking fee is zero if the sale is within the 30-day return
    window and otherwise the `line_total_cents` times 0.15 rounded half up, where the
    sale's age is the whole number of days between the sale's creation date and the
    current clock date; the `refund_amount_cents` is then `line_total_cents` minus that
    `restocking_fee_cents`."

    Design: Corner/calculations/return_restocking_fee_outside_window
    """
    ctx = fx.setup_one_line_sale(price=10000, fulfill=True, dob="1970-10-10",
                                 clock="2026-07-01T00:00:00Z")
    ret = fx.create_and_approve_return(ctx["sale"]["id"], ctx["line"]["id"], return_type="RETURN")
    fx.set_clock("2026-08-10T00:00:00Z")  # 40 days after sale creation
    refunded = validate_success(api.refund_return(ret["id"], SM))
    assert refunded["restocking_fee_cents"] == 1500, "round(10000 * 0.15)"
    assert refunded["refund_amount_cents"] == 8500


def test_no_restocking_fee_within_return_window(api):
    """PRD §3.5: "the restocking fee is zero if the sale is within the 30-day return
    window and otherwise the `line_total_cents` times 0.15 rounded half up... the
    `refund_amount_cents` is then `line_total_cents` minus that `restocking_fee_cents`."

    Design: Corner/calculations/return_no_restocking_fee_within_window
    """
    ctx = fx.setup_one_line_sale(price=10000, fulfill=True, dob="1971-11-11",
                                 clock="2026-07-01T00:00:00Z")
    ret = fx.create_and_approve_return(ctx["sale"]["id"], ctx["line"]["id"], return_type="RETURN")
    refunded = validate_success(api.refund_return(ret["id"], SM))
    assert refunded["restocking_fee_cents"] == 0
    assert refunded["refund_amount_cents"] == 10000


def test_refund_on_exchange_return_rejected(api):
    """PRD §3.5: "A refund is valid only when `return_type` is `RETURN`; attempting it on
    an exchange yields `ERR_EXCHANGE_TYPE_MISMATCH`."

    Design: Corner/state_machines/refund_on_exchange_type_returns_mismatch
    """
    ctx = fx.setup_one_line_sale(price=9000, fulfill=True, dob="1979-09-09")
    ret = fx.create_and_approve_return(ctx["sale"]["id"], ctx["line"]["id"], return_type="EXCHANGE")
    resp = api.refund_return(ret["id"], SM)
    validate_error(resp, ApiErrorId.ERR_EXCHANGE_TYPE_MISMATCH.value)


def test_exchange_swaps_inventory_and_sets_price_difference(api):
    """PRD §3.5: "It advances `APPROVED` to `EXCHANGED`, sets `price_difference_cents` to
    the replacement product's `base_price_cents` minus the original line's
    `unit_price_cents` (which may be negative), flips the sale line from `ACTIVE` to
    `EXCHANGED`, restocks the original item by its quantity, and decrements the
    replacement item's `quantity_on_hand` by that quantity."

    Design: Corner/state_machines/exchange_swaps_inventory_and_computes_price_difference
    """
    fx.set_clock()
    prod_o = fx.create_product(name="Orig 9000", brand="X", category="REGULAR", base_price_cents=9000)
    prod_r = fx.create_product(name="Repl 11000", brand="X", category="REGULAR", base_price_cents=11000)
    inv_o = fx.create_inventory(prod_o["id"], size=9.0, width="D", lot_number="O1", quantity_on_hand=3)
    inv_r = fx.create_inventory(prod_r["id"], size=9.5, width="E", lot_number="R1", quantity_on_hand=2)
    cust = fx.create_customer(full_name="Sw Cust", date_of_birth="1977-07-07")
    fitter = fx.create_fitter(full_name="Sw Fit")
    fh = fx.make_fitter_headers(fitter["id"])
    sale = fx.open_sale(cust["id"], fitter["id"], fh)
    line = fx.add_line(sale["id"], inv_o["id"], fh)
    fx.fulfill_sale(sale["id"], fh)
    ret = fx.create_and_approve_return(sale["id"], line["id"], return_type="EXCHANGE")
    exchanged = validate_success(api.exchange_return(
        ret["id"], {"replacement_inventory_item_id": inv_r["id"]}, SM))
    assert exchanged["price_difference_cents"] == 2000, "11000 - 9000"
    line_after = get_success_data(api.get_sale_line(line["id"], SM))
    inv_r_after = get_success_data(api.get_inventory_item(inv_r["id"], SM))
    assert line_after["status"] == "EXCHANGED"
    assert inv_r_after["quantity_on_hand"] == 1, "replacement 2 -> 1"
