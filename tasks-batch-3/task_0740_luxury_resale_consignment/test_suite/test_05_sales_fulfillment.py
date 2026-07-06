"""Sales: the parallel payment/fulfilment axes, the accept-offer cascade chain, and
capture idempotency.
"""
from test_helpers import (
    validate_success, validate_error,
    make_seller_headers, make_buyer_headers,
    # fixtures
    setup_direct_sale, setup_published_listing, create_buyer, make_offer,
    get_offer, get_listing, get_item, get_sale, get_sale_by_listing, capture_payment,
)


# --- non_linear_state_machine: independent payment x fulfillment axes --------
def test_capture_advances_only_payment_axis(api):
    """PRD §3.6: "Every sale carries two independent state axes: a `payment_status` that
    runs `PENDING` → `CAPTURED` → `REFUNDED`, and a `fulfillment_status` that runs
    `AWAITING_SHIPMENT` → `SHIPPED` → `DELIVERED` → `RETURNED`. A new sale begins with
    `payment_status` `PENDING` and `fulfillment_status` `AWAITING_SHIPMENT`."
    PRD §3.6: "A `Buyer` (or `OpsAdmin`) captures payment, moving `payment_status` from
    `PENDING` to `CAPTURED`;"

    Design: Difficulty/non_linear_state_machine/sale_parallel_payment_and_fulfillment_axes
    """
    ctx = setup_direct_sale(list_price_cents=180000, category="HANDBAGS")
    validate_success(api.capture_payment(ctx["sale_id"], make_buyer_headers(ctx["buyer_id"])), 200)
    sale = get_sale(ctx["sale_id"])
    assert sale["payment_status"] == "CAPTURED", sale["payment_status"]
    assert sale["fulfillment_status"] == "AWAITING_SHIPMENT", sale["fulfillment_status"]


def test_capture_then_ship_advances_both_axes(api):
    """PRD §3.6: "A `Seller` (or `OpsAdmin`) marks the sale shipped, moving
    `fulfillment_status` from `AWAITING_SHIPMENT` to `SHIPPED`; this requires the cross-axis
    condition that `payment_status` already be `CAPTURED`,"

    Design: Difficulty/non_linear_state_machine/sale_parallel_payment_and_fulfillment_axes
    """
    ctx = setup_direct_sale(list_price_cents=180000, category="HANDBAGS")
    capture_payment(ctx["sale_id"], ctx["buyer_id"])
    validate_success(api.ship_sale(ctx["sale_id"], make_seller_headers(ctx["seller_id"])), 200)
    sale = get_sale(ctx["sale_id"])
    assert sale["payment_status"] == "CAPTURED", sale["payment_status"]
    assert sale["fulfillment_status"] == "SHIPPED", sale["fulfillment_status"]


# --- transitive_cascade: accept offer chains offer -> sale -> listing -> item -
def test_accept_offer_creates_offer_channel_sale(api):
    """PRD §3.5: "When a `Seller` accepts a `PENDING` offer, it moves to `ACCEPTED` and the
    `agreed_price_cents` is set to the offer's `amount_cents`."
    PRD §3.5: "the listing goes from `ACTIVE` to `SOLD`, a `Sale` is created with
    `sale_channel` `OFFER`, `sale_price_cents` equal to the `agreed_price_cents`, and
    `offer_id` referencing the accepted offer;"

    Design: Difficulty/transitive_cascade/accept_offer_cascade_offer_sale_listing_item
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    buyer_a = create_buyer(display_name="BA", email="ba@x.com")
    buyer_b = create_buyer(display_name="BB", email="bb@x.com")
    offer_a = make_offer(ctx["listing_id"], buyer_a["id"], 180000, ctx["listing_version"])
    make_offer(ctx["listing_id"], buyer_b["id"], 150000, get_listing(ctx["listing_id"])["version"])
    validate_success(api.accept_offer(offer_a["id"], make_seller_headers(ctx["seller_id"])), 200)
    assert get_offer(offer_a["id"])["status"] == "ACCEPTED"
    sale = get_sale_by_listing(ctx["listing_id"])
    assert sale["sale_channel"] == "OFFER", sale["sale_channel"]
    assert sale["sale_price_cents"] == 180000, sale["sale_price_cents"]


def test_accept_offer_cascades_to_listing_item_and_sibling(api):
    """PRD §3.5: "the item goes from `LISTED` to `SOLD`; and every other sibling offer on
    the listing still in `PENDING` or `COUNTERED` is moved to `DECLINED`."

    Design: Difficulty/transitive_cascade/accept_offer_cascade_offer_sale_listing_item
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    buyer_a = create_buyer(display_name="BA", email="ba@x.com")
    buyer_b = create_buyer(display_name="BB", email="bb@x.com")
    offer_a = make_offer(ctx["listing_id"], buyer_a["id"], 180000, ctx["listing_version"])
    offer_b = make_offer(ctx["listing_id"], buyer_b["id"], 150000,
                         get_listing(ctx["listing_id"])["version"])
    validate_success(api.accept_offer(offer_a["id"], make_seller_headers(ctx["seller_id"])), 200)
    assert get_listing(ctx["listing_id"])["status"] == "SOLD"
    assert get_item(ctx["item_id"])["status"] == "SOLD"
    assert get_offer(offer_b["id"])["status"] == "DECLINED"


# --- Corner: capture idempotency ---------------------------------------------
def test_capture_payment_twice_rejected(api):
    """PRD §3.6: "attempting capture on a sale whose `payment_status` is not `PENDING` is
    rejected with `ERR_SALE_PAYMENT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/capture_payment_twice_returns_invalid_state
    """
    ctx = setup_direct_sale(list_price_cents=180000, category="HANDBAGS")
    capture_payment(ctx["sale_id"], ctx["buyer_id"])
    res = api.capture_payment(ctx["sale_id"], make_buyer_headers(ctx["buyer_id"]))
    validate_error(res, "ERR_SALE_PAYMENT_INVALID_STATE", expected_status=409)
