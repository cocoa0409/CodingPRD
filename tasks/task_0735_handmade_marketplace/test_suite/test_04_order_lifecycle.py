"""Order payment/fulfillment axes, listing-active gating, and order-create/pay validations."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    make_seller_headers, make_buyer_headers,
    setup_active_listing, setup_unpaid_mto_order_no_material,
    create_shop, create_shipping_profile, create_listing, publish_listing, place_order,
)

BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Difficulty / non_linear_state_machine / order_parallel_payment_and_fulfillment_axes
# ==========================================================================
def test_pay_advances_payment_and_fulfillment_axes(api):
    """PRD §3.5: "The buyer who owns an order pays for it, advancing `payment_status` from
    `UNPAID` to `PAID`."
    PRD §3.5: "A made-to-order order moves its `fulfillment_status` to `IN_PRODUCTION` on
    payment; a ready-to-ship order stays at `NOT_STARTED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    shop, listing, order = setup_unpaid_mto_order_no_material()
    paid = validate_success(api.pay_order(order["id"], BUYER))
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "IN_PRODUCTION"


def test_ship_advances_fulfillment_axis_only(api):
    """PRD §3.5: "From there the order advances along its fulfillment axis, independently
    of its payment axis. The seller ships it, moving `fulfillment_status` to `SHIPPED` —
    allowed from either `NOT_STARTED` or `IN_PRODUCTION`, and only once `payment_status`
    is `PAID` — which stamps `shipped_at` and is treated as purchasing a shipping label."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    shop, listing, order = setup_unpaid_mto_order_no_material()
    validate_success(api.pay_order(order["id"], BUYER))
    shipped = validate_success(api.ship_order(order["id"], make_seller_headers(shop["id"])))
    assert shipped["payment_status"] == "PAID", "payment axis stays PAID across a ship"
    assert shipped["fulfillment_status"] == "SHIPPED"


# ==========================================================================
# Difficulty / cross_entity_state_dependency / order_create_requires_listing_active
# ==========================================================================
def test_order_create_on_draft_listing_rejected(api):
    """PRD §3.4: "Then the listing must be purchasable — its `status` must be `ACTIVE` —
    otherwise `ERR_LISTING_NOT_PURCHASABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_listing_active
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    listing = create_listing(shop["id"], sp["id"], title="Draft Mug", price_cents=2000, quantity=5)
    resp = api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1}, BUYER)
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_PURCHASABLE)


def test_order_create_succeeds_after_listing_published(api):
    """PRD §3.3: "Publishing it advances `DRAFT` to `ACTIVE` — the point at which it
    becomes purchasable".
    PRD §3.4: "A freshly placed order starts with `payment_status` `UNPAID` and
    `fulfillment_status` `NOT_STARTED`; its `payout_id` is null until a payout later
    claims it."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_listing_active
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    listing = create_listing(shop["id"], sp["id"], title="Draft Mug", price_cents=2000, quantity=5)
    publish_listing(shop["id"], listing["id"])
    order = validate_success(api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1}, BUYER), 201)
    assert order["payment_status"] == "UNPAID"


# ==========================================================================
# Corner / state_machines / order_ship_before_pay_returns_invalid_state
# ==========================================================================
def test_ship_unpaid_order_returns_invalid_state(api):
    """PRD §3.5: "The seller ships it, moving `fulfillment_status` to `SHIPPED` — allowed
    from either `NOT_STARTED` or `IN_PRODUCTION`, and only once `payment_status` is
    `PAID`".
    PRD §3.5: "Any of these fulfillment steps requested from the wrong state is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/order_ship_before_pay_returns_invalid_state
    """
    shop, sp, listing = setup_active_listing(
        listing_overrides={"price_cents": 2000, "quantity": 5, "title": "Mug"})
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    resp = api.ship_order(order["id"], make_seller_headers(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Corner / validations / personalization_required_missing_returns_error
# ==========================================================================
def test_order_missing_required_personalization_note_rejected(api):
    """PRD §3.4: "Finally, if the listing has `personalization_required` set, the order's
    `personalization_note` must be present and non-empty, else
    `ERR_PERSONALIZATION_REQUIRED` (HTTP 422)."

    Design: Corner/validations/personalization_required_missing_returns_error
    """
    shop, sp, listing = setup_active_listing(
        listing_overrides={"fulfillment_type": "MADE_TO_ORDER", "processing_time_days": 3,
                            "price_cents": 3000, "title": "Engraved",
                            "personalization_enabled": True, "personalization_required": True,
                            "personalization_char_limit": 20})
    resp = api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1}, BUYER)
    validate_error(resp, ApiErrorId.ERR_PERSONALIZATION_REQUIRED)


# ==========================================================================
# Corner / validations / personalization_too_long_returns_error
# ==========================================================================
def test_order_personalization_note_too_long_rejected(api):
    """PRD §3.4: "Next, if a `personalization_note` is present, its length must not exceed
    the listing's `personalization_char_limit`, else `ERR_PERSONALIZATION_TOO_LONG`
    (HTTP 400)."

    Design: Corner/validations/personalization_too_long_returns_error
    """
    shop, sp, listing = setup_active_listing(
        listing_overrides={"fulfillment_type": "MADE_TO_ORDER", "processing_time_days": 3,
                            "price_cents": 3000, "title": "Engraved",
                            "personalization_enabled": True, "personalization_char_limit": 20})
    resp = api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1,
         "personalization_note": "This message is definitely far too long to fit"}, BUYER)
    validate_error(resp, ApiErrorId.ERR_PERSONALIZATION_TOO_LONG)


# ==========================================================================
# Corner / validations / insufficient_inventory_on_pay_returns_error
# ==========================================================================
def test_pay_with_insufficient_inventory_rejected(api):
    """PRD §3.5: "for a ready-to-ship order the listing's `quantity` (or the chosen
    variation's `stock_qty`) must be at least the ordered `quantity`, and for a
    made-to-order order the primary material's `stock_qty` must be at least
    `material_qty_per_unit` multiplied by the ordered `quantity`; a shortfall is rejected
    with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409)."

    Design: Corner/validations/insufficient_inventory_on_pay_returns_error
    """
    shop, sp, listing = setup_active_listing(
        listing_overrides={"price_cents": 2000, "quantity": 1, "title": "Rare Mug"})
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=2)
    resp = api.pay_order(order["id"], BUYER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


# ==========================================================================
# Corner / errors / order_get_not_found
# ==========================================================================
def test_get_missing_order_returns_not_found(api, admin_headers):
    """PRD §2.5: "a missing order `ERR_ORDER_NOT_FOUND`".

    Design: Corner/errors/order_get_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)
