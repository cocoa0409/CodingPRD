"""Calculation corner tests: rush surcharge & turnaround, trade-in haircut/floor,
deposit floor, partial-payment status, build-fee base band, open-recall count,
layaway forfeit floor (PRD §3.3, §3.5, §3.6, §3.7, §3.8, §3.9, §3.11).

Queue B — corner section: calculations.
"""
from test_helpers import (
    api_client, validate_success,
    create_customer, create_sku, create_tier, create_ticket,
    create_appraised_trade_in, accept_trade_in, create_special_order,
    create_order, add_order_line, pay_order, get_sku,
    open_layaway_with_deposit, create_assembling_build,
    create_delivered_purchase, publish_recall, set_clock,
    create_special_order_payload,
    TEST_USERS,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


def test_rush_ticket_labor_subtotal_and_turnaround():
    """PRD §3.3: "If the ticket is rush, the effective base is `base_labor_cents`
    multiplied by the quantity (ten thousand plus the tier's `rush_multiplier_bps`)
    divided by ten thousand, with that product rounded half up to a whole cent —
    so a default rush multiplier of 5000 basis points yields one and a half times
    the base labor."
    PRD §3.3: "for a rush ticket it is `turnaround_hours` divided by two and
    rounded up to the next whole hour, so a five-hour tier rushed becomes three
    hours, not two. The `promised_ready_at` is the server's current UTC time plus
    that many hours."

    Rush BASIC tier (base 8000, +50%, 5h) from clock 2026-06-14T00:00:00Z gives
    labor_subtotal_cents=12000 and promised_ready_at = +ceil(5/2)=3h.

    Design: Corner/calculations/ticket_quote_rush_surcharge_and_turnaround
    """
    set_clock("2026-06-14T00:00:00Z")
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(cust["id"], tier["id"], is_rush=True)
    quoted = validate_success(api_client.quote_service_ticket(ticket["id"], ADV), 200)
    assert quoted["labor_subtotal_cents"] == 12000
    assert quoted["customer_owes_cents"] == 12000
    assert quoted["promised_ready_at"] == "2026-06-14T03:00:00.000Z"


def test_tradein_offer_grade_b_with_handling():
    """PRD §3.11: "The haircut rate is 8500 basis points for grade `A`, 7000
    basis points for grade `B`, and 5000 basis points for grade `C`. The value
    after haircut is `appraised_value_cents` multiplied by that rate divided by
    ten thousand, rounded half up to a whole cent. The `offer_cents` is then that
    after-haircut value minus a flat handling deduction of 1500 cents".
    PRD §3.11: "On acceptance, if `apply_to` is `STORE_CREDIT`, the `offer_cents`
    is credited to the customer's `store_credit_cents`".

    Grade-B appraised 100000: 70000 - 1500 = 68500, credited to store credit.

    Design: Corner/calculations/tradein_offer_grade_b_with_handling
    """
    cust = create_customer()
    ti = create_appraised_trade_in(cust["id"], "B", 100000, apply_to="STORE_CREDIT")
    accepted = accept_trade_in(ti["id"])
    assert accepted["offer_cents"] == 68500
    refreshed = validate_success(api_client.get_customer(cust["id"], MGR), 200)
    assert refreshed["store_credit_cents"] == 68500


def test_tradein_offer_floor_at_zero():
    """PRD §3.11: "The `offer_cents` is then that after-haircut value minus a flat
    handling deduction of 1500 cents, but never below zero."
    PRD §3.11: "a `CASH` payout makes no store-credit movement."

    Grade-C appraised 1000: after_haircut 500 - 1500 = -1000, floored to
    offer_cents=0; CASH apply makes no store-credit movement.

    Design: Corner/calculations/tradein_offer_floor_at_zero
    """
    cust = create_customer()
    ti = create_appraised_trade_in(cust["id"], "C", 1000, apply_to="CASH")
    accepted = accept_trade_in(ti["id"])
    assert accepted["offer_cents"] == 0
    refreshed = validate_success(api_client.get_customer(cust["id"], MGR), 200)
    assert refreshed["store_credit_cents"] == 0


def test_special_order_deposit_min_floor_applies():
    """PRD §3.8: "The required deposit is then the smaller of the line value
    itself and the larger of a flat minimum of 5000 cents and that percentage
    term".

    Sku 10000 qty 1: 30% = 3000 is below the 5000 minimum, so the floor pins
    deposit_required_cents=5000.

    Design: Corner/calculations/special_order_deposit_min_floor_applies
    """
    cust = create_customer()
    sku = create_sku(name="Mid Part", category="PART", list_price_cents=10000, on_hand=0)
    so = validate_success(api_client.create_special_order(
        create_special_order_payload(cust["id"], sku["id"], 1), SA), 201)
    assert so["deposit_required_cents"] == 5000


def test_order_total_partial_then_full_payment_status():
    """PRD §3.5: "The order is `PAID` when `amount_paid_cents` is greater than 0
    and at least `total_due_cents`, `PARTIALLY_PAID` when `amount_paid_cents` is
    greater than 0 but below `total_due_cents`, and `UNPAID` otherwise."

    Subtotal 30000 paid 10000 -> PARTIALLY_PAID; a further 20000 (cumulative
    30000) flips to PAID with amount_paid_cents=30000.

    Design: Corner/calculations/order_total_partial_payment_status
    """
    cust = create_customer()
    sku = create_sku(name="Wheelset", category="PART", list_price_cents=30000, on_hand=4)
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 1)
    pay_order(order["id"], 10000)
    mid = validate_success(api_client.get_sales_order(order["id"], SA), 200)
    assert mid["payment_status"] == "PARTIALLY_PAID"
    pay_order(order["id"], 20000)
    final = validate_success(api_client.get_sales_order(order["id"], SA), 200)
    assert final["amount_paid_cents"] == 30000
    assert final["payment_status"] == "PAID"


def test_build_fee_base_band_one_part():
    """PRD §3.9: "It begins with a flat base of 5000 cents. The first up to five
    parts are charged at 1200 cents each".

    required_part_count=1: 5000 + 1*1200 = 6200 (single tier-1 part).

    Design: Corner/calculations/build_fee_base_band_one_part
    """
    cust = create_customer()
    frame = create_sku(name="Small Frame", category="BIKE", list_price_cents=40000, on_hand=2)
    part = create_sku(name="One Part Sku", category="PART", list_price_cents=1000, on_hand=5)
    build = create_assembling_build(cust["id"], frame["id"], part["id"], 1)
    assert build["build_fee_cents"] == 6200


def test_customer_open_recall_count_derived():
    """PRD §3.1: "It is the number of distinct recall notices that match a
    stock-keeping unit the customer has actually taken delivery of and that the
    customer has not yet acknowledged."

    A customer with a DELIVERED purchase of a Sku that then receives a recall
    notice has open_recall_count==1.

    Design: Corner/calculations/customer_open_recall_count_derived
    """
    cust = create_customer()
    sku = create_sku(name="Recalled Part", category="PART", list_price_cents=5000, on_hand=3)
    create_delivered_purchase(sku["id"], qty=1, customer_id=cust["id"])
    publish_recall(sku["id"], "ADVISORY")
    refreshed = validate_success(api_client.get_customer(cust["id"], MGR), 200)
    assert refreshed["open_recall_count"] == 1


def test_layaway_forfeit_floor_dominates():
    """PRD §3.7: "The fee in the forfeit case is the larger of a flat floor of
    2000 cents and fifteen percent of `price_cents` ... but never more than the
    accrued `deposit_cents` ... The `refund_cents` is then `deposit_cents` minus
    `forfeit_fee_cents`".

    Price 10000, deposit 8000: 15% = 1500 < floor 2000, so forfeit_fee_cents=2000
    and refund_cents=6000.

    Design: Corner/calculations/layaway_forfeit_floor_dominates
    """
    cust = create_customer()
    sku = create_sku(name="Cheap Bike", category="BIKE", list_price_cents=10000, on_hand=3)
    plan = open_layaway_with_deposit(cust["id"], sku["id"], 8000)
    forfeited = validate_success(api_client.forfeit_layaway_plan(plan["id"], MGR), 200)
    assert forfeited["forfeit_fee_cents"] == 2000
    assert forfeited["refund_cents"] == 6000
    refreshed = validate_success(api_client.get_customer(cust["id"], MGR), 200)
    assert refreshed["store_credit_cents"] == 6000
