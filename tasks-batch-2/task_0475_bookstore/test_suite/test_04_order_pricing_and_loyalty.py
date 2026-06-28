"""Order-pricing and loyalty-points calculations: GOLD discount, net_paid,
and the provisional-vs-final loyalty variants."""
from test_helpers import (
    validate_success,
    TEST_USERS, make_member_headers,
    create_sales_order_payload, create_order_line_payload,
    make_member, make_title, receive_stock,
    setup_paid_order,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]


def test_loyalty_provisional_stored_only_at_pay(api):
    """PRD §3.5: "At payment, the *provisional* variant estimates points from the
    order's `net_paid_cents` as it stands at pay time; the result is stored in
    `points_provisional` and is an estimate only — it is never added to the
    member's `loyalty_points`."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_stored_only_vs_final_credited
    """
    member = make_member(tier="REGULAR")
    title = make_title(list_price_cents=2500)
    receive_stock(title["id"], 2)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 2), mh)
    paid = validate_success(api.pay_order(order["id"], mh))
    # subtotal 5000, REGULAR -> net 5000, floor(5000/100)*1 = 50 provisional.
    assert paid["points_provisional"] == 50
    member_now = validate_success(api.get_member(member["id"], mh))
    assert member_now["loyalty_points"] == 0, \
        "provisional points must NOT be credited to the member at pay"


def test_loyalty_final_credited_at_fulfill(api):
    """PRD §3.5: "At fulfillment, the *final* variant recomputes points from the
    order's `net_paid_cents` as it stands at fulfill time; the result is stored in
    `points_final` and is the awarded value that is added to the member's
    `loyalty_points`."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_stored_only_vs_final_credited
    """
    member = make_member(tier="REGULAR")
    title = make_title(list_price_cents=2500)
    receive_stock(title["id"], 2)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 2), mh)
    paid = validate_success(api.pay_order(order["id"], mh))
    reserved = validate_success(
        api.reserve_order(order["id"],
                          {"expected_sales_order_version": paid["version"]},
                          BOOKSELLER)
    )
    fulfilled = validate_success(api.fulfill_order(order["id"], BOOKSELLER))
    assert fulfilled["points_final"] == 50
    member_now = validate_success(api.get_member(member["id"], mh))
    assert member_now["loyalty_points"] == 50, \
        "final points must be credited to the member at fulfill"


def test_gold_member_discount_and_provisional_points(api):
    """PRD §3.4: "for a `GOLD` member this is five percent of the subtotal,
    rounded half-up to whole cents". And: "It then sets `net_paid_cents` to the
    subtotal minus the member discount minus `credit_redeemed_cents`, floored at
    zero".
    PRD §3.5: "multiply by a tier multiplier of two for a `GOLD` member or one for
    a `REGULAR` member".

    Design: Corner/calculations/gold_member_discount_and_points_on_pay
    """
    member = make_member(tier="GOLD")
    title = make_title(list_price_cents=1000)
    receive_stock(title["id"], 2)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 2), mh)
    paid = validate_success(api.pay_order(order["id"], mh))
    # subtotal 2000, discount round(2000*0.05)=100, net 1900, points floor(1900/100)*2=38.
    assert paid["member_discount_cents"] == 100
    assert paid["net_paid_cents"] == 1900
    assert paid["points_provisional"] == 38
