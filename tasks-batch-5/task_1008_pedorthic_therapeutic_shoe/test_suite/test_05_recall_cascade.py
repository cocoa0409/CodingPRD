"""Recall issuance: the depth-4 quarantine/cancel/deposit-refund cascade, plus the
quarantine safety checks it enables on fulfill and special-order placement."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]


class TestRecallIssueCascade:
    """Issuing a recall quarantines stock, which cancels a matching ORDERED special order,
    which mints an ADJUST deposit-refund, which moves the customer's loyalty balance."""

    def test_quarantines_inventory_and_cancels_special_order(self, api):
        """PRD §3.1: "Issuing it advances `DRAFT` to `ISSUED` and fires a four-link
        cascade in order: first, every `AVAILABLE` inventory item matching the recalled
        product (and matching lot, if the recall is lot-scoped) transitions to
        `QUARANTINED`; second, as a consequence, every special order for that product
        currently in `ORDERED` or `RECEIVED` is cancelled, moving it to `CANCELLED`."

        Design: Difficulty/transitive_cascade/recall_issue_quarantine_cancel_deposit_chain
        """
        ctx = fx.setup_placed_special_order(deposit=5000)
        fx.create_and_issue_recall(ctx["product"]["id"])
        inv = get_success_data(api.get_inventory_item(ctx["inventory"]["id"], SM))
        so = get_success_data(api.get_special_order(ctx["special_order"]["id"], SM))
        assert inv["status"] == "QUARANTINED"
        assert so["status"] == "CANCELLED"

    def test_deposit_refund_credits_customer_balance(self, api):
        """PRD §3.1: "third, each such cancelled special order whose `deposit_cents` is
        greater than zero mints a loyalty ledger entry (reason `ADJUST`) whose point value
        is the deposit in cents divided by 100 and rounded down to a whole number; and
        fourth, each affected customer's `loyalty_points_balance` recomputes to include
        those credits."

        Design: Difficulty/transitive_cascade/recall_issue_quarantine_cancel_deposit_chain
        """
        ctx = fx.setup_placed_special_order(deposit=5000)
        fx.create_and_issue_recall(ctx["product"]["id"])
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], SM))
        assert customer["loyalty_points_balance"] == 50, "floor(5000 / 100)"


def test_fulfill_quarantined_item_rejected(api):
    """PRD §3.4: "Fulfilling a sale advances `fulfillment_status` from `PENDING` to
    `FULFILLED`. It requires that the sale be `PENDING`, that it have at least one
    `ACTIVE` line, and that every `ACTIVE` line's inventory item be `AVAILABLE` — a
    `QUARANTINED` item blocks fulfillment with `ERR_ITEM_QUARANTINED`."

    Design: Corner/state_machines/fulfill_quarantined_item_returns_item_quarantined
    """
    fx.set_clock()
    prod = fx.create_product(name="Q Shoe", brand="X", category="THERAPEUTIC", base_price_cents=8000)
    inv = fx.create_inventory(prod["id"], lot_number="QQ", quantity_on_hand=3)
    cust = fx.create_customer(full_name="Q Cust", date_of_birth="1974-04-04")
    fitter = fx.create_fitter(full_name="Q Fit")
    fh = fx.make_fitter_headers(fitter["id"])
    sale = fx.open_sale(cust["id"], fitter["id"], fh)
    fx.add_line(sale["id"], inv["id"], fh)
    fx.create_and_issue_recall(prod["id"], reason="sole separation")  # item -> QUARANTINED
    resp = api.fulfill_sale(sale["id"], fh)
    validate_error(resp, ApiErrorId.ERR_ITEM_QUARANTINED.value)


def test_place_special_order_for_recalled_product_rejected(api):
    """PRD §3.7: "A `StoreManager` places it, advancing `DRAFT` to `ORDERED`, provided the
    product is not recalled — a recalled product blocks placement with
    `ERR_ITEM_QUARANTINED`."

    Design: Corner/state_machines/special_order_place_recalled_product_returns_item_quarantined
    """
    fx.set_clock()
    prod = fx.create_product(name="RC Shoe", brand="X", category="REGULAR", base_price_cents=6000)
    cust = fx.create_customer(full_name="RC Cust", date_of_birth="1985-05-05")
    so = get_success_data(api.create_special_order(
        {"customer_id": cust["id"], "product_id": prod["id"], "requested_size": 9.0,
         "requested_width": "D", "deposit_cents": 1000}, SM))
    fx.create_and_issue_recall(prod["id"])
    resp = api.place_special_order(so["id"], SM)
    validate_error(resp, ApiErrorId.ERR_ITEM_QUARANTINED.value)
