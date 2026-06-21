"""Return settlement math and APPROVED→{REFUNDED,EXCHANGED} fork (PRD §3.8).

Difficulty queue: dual_variant_calc (cash vs store credit), transitive_cascade
(store-credit settle → refund → ledger → balance), non_linear_state_machine
(branch fork refund vs exchange).
Corner queue: calculations (defective waives fee, exchange cheaper → credit delta).
"""
from test_helpers import fixtures as fx


# Open clock dates: deliver 2026-06-05, act at 2026-06-10 (window open for 30d products).
DELIVER_CLOCK = "2026-06-05T00:00:00Z"
ACT_CLOCK = "2026-06-10T00:00:00Z"

P1 = {"unit_price_cents": 2599, "tax_rate_bps": 875, "restocking_fee_bps": 1500,
      "return_window_days": 30, "final_sale": False}
P2 = {"unit_price_cents": 1499, "tax_rate_bps": 875, "return_window_days": 30,
      "final_sale": False}


def test_cash_refund_withholds_restocking_fee(api):
    """PRD §3.8: "For a REFUND, the settlement_cents is the larger of 0 and the base
    refund minus the total restocking fee, and the money is paid back to the original
    payment method."
    PRD §3.8: "when not waived, the line's restocking fee is the returnable subtotal
    multiplied by the product's restocking_fee_bps, divided by 10000, rounded half
    up, and is otherwise 0."
    PRD §3.8: "A base refund — used by the cash and store-credit paths — is the sum
    over the lines of the returnable subtotal plus the allocated tax minus the
    returned promo share; shipping is never refunded."

    Design: Difficulty/dual_variant_calc/refund_cash_vs_store_credit_diverge_on_return
    """
    ctx = fx.setup_delivered_two_line_order(
        P1, P2, qty1=2, qty2=3, promo_flat_cents=0,
        delivered_clock=DELIVER_CLOCK)
    fx.set_clock(ACT_CLOCK)
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "NO_LONGER_WANTED", "REFUND",
                         [{"order_line_id": ctx["line1"]["id"], "return_qty": 1}])
    assert rma["settlement_cents"] == 2437, "base 2827 - fee 390"
    assert rma["restocking_fee_cents"] == 390


def test_store_credit_waives_fee_and_adds_bonus_exceeding_cash(api):
    """PRD §3.8: "For STORE_CREDIT, the restocking fee is always waived and a bonus
    is applied: the settlement_cents is the base refund multiplied by 10500, divided
    by 10000, rounded half up — that is, a 5 percent bonus on top of the base —
    making store credit strictly larger than the equivalent cash refund for identical
    inputs."

    Design: Difficulty/dual_variant_calc/refund_cash_vs_store_credit_diverge_on_return
    """
    ctx = fx.setup_delivered_two_line_order(
        P1, P2, qty1=2, qty2=3, promo_flat_cents=0,
        delivered_clock=DELIVER_CLOCK)
    fx.set_clock(ACT_CLOCK)

    # Settle the cash RMA first (returns 1 of line1's 2 shipped units), then open
    # a STORE_CREDIT RMA for the second unit on the same line.
    cash_rma = fx.open_approve_settle_return(
        ctx["order"]["id"], ctx["customer"]["id"], "NO_LONGER_WANTED", "REFUND",
        [{"order_line_id": ctx["line1"]["id"], "return_qty": 1}])
    assert cash_rma["settlement_cents"] == 2437

    credit_rma = fx.open_return(
        ctx["order"]["id"], ctx["customer"]["id"], "NO_LONGER_WANTED", "STORE_CREDIT",
        [{"order_line_id": ctx["line1"]["id"], "return_qty": 1}])
    assert credit_rma["settlement_cents"] == 2968, "base 2827 * 1.05 → 2968"
    assert credit_rma["restocking_fee_cents"] == 0, "store credit always waives the fee"
    assert credit_rma["settlement_cents"] > cash_rma["settlement_cents"], \
        "store credit strictly exceeds cash on identical lines"


def test_settle_store_credit_cascades_refund_ledger_balance(api):
    """PRD §3.8: "First, it creates a Refund in SETTLED status whose destination is
    ORIGINAL_PAYMENT when the resolution is REFUND and STORE_CREDIT when the
    resolution is STORE_CREDIT, whose amount_cents equals the RMA's settlement_cents".
    PRD §3.8: "Second, when the destination is STORE_CREDIT, the system writes a
    CreditLedgerEntry of kind REFUND_CREDIT whose amount_cents is the positive
    settlement amount and whose refund_id points at the new refund, after which the
    customer's store_credit_cents is recomputed."

    Design: Difficulty/transitive_cascade/settle_store_credit_cascades_refund_to_ledger_to_customer_balance_depth3
    """
    ctx = fx.setup_delivered_two_line_order(
        P1, P2, qty1=2, qty2=3, promo_flat_cents=0,
        delivered_clock=DELIVER_CLOCK)
    fx.set_clock(ACT_CLOCK)
    rma = fx.open_approve_settle_return(
        ctx["order"]["id"], ctx["customer"]["id"], "NO_LONGER_WANTED", "STORE_CREDIT",
        [{"order_line_id": ctx["line1"]["id"], "return_qty": 1}])

    refunds = fx.list_return_refunds(rma["id"])
    assert len(refunds) == 1, "exactly one Refund created"
    refund = refunds[0]
    assert refund["amount_cents"] == 2968, "link1: refund amount == settlement"
    assert refund["destination"] == "STORE_CREDIT"

    entries = fx.list_refund_credit_entries(refund["id"])
    assert len(entries) == 1, "link2: one CreditLedgerEntry issued"
    assert entries[0]["amount_cents"] == 2968

    customer_after = fx.get_customer(ctx["customer"]["id"])
    assert customer_after["store_credit_cents"] == 2968, "link3: balance recomputed"


def test_settle_store_credit_updates_lifetime_refunded(api):
    """PRD §3.8: "each returned order line's returned_qty is recomputed — the units
    now count as returned — and the customer's lifetime_refunded_cents and
    return_risk_score are recomputed."
    PRD §3.9: "The lifetime_refunded_cents figure is the sum of amount_cents over the
    customer's refunds whose status is SETTLED, across all destinations."

    Design: Difficulty/transitive_cascade/settle_store_credit_cascades_refund_to_ledger_to_customer_balance_depth3
    """
    ctx = fx.setup_delivered_two_line_order(
        P1, P2, qty1=2, qty2=3, promo_flat_cents=0,
        delivered_clock=DELIVER_CLOCK)
    fx.set_clock(ACT_CLOCK)
    fx.open_approve_settle_return(
        ctx["order"]["id"], ctx["customer"]["id"], "NO_LONGER_WANTED", "STORE_CREDIT",
        [{"order_line_id": ctx["line1"]["id"], "return_qty": 1}])

    customer_after = fx.get_customer(ctx["customer"]["id"])
    assert customer_after["lifetime_refunded_cents"] == 2968, "settled refund counts"


def test_approved_refund_rma_settles_to_refunded_with_cash_refund(api):
    """PRD §3.8: "Settling a REFUND or STORE_CREDIT return advances the status from
    APPROVED to REFUNDED and runs a three-link cascade. First, it creates a Refund in
    SETTLED status whose destination is ORIGINAL_PAYMENT when the resolution is
    REFUND".

    Design: Difficulty/non_linear_state_machine/return_authorization_branches_approved_into_refunded_vs_exchanged
    """
    p = {"unit_price_cents": 2000, "tax_rate_bps": 0, "restocking_fee_bps": 0,
         "return_window_days": 30, "final_sale": False}
    ctx = fx.setup_delivered_order(product_overrides=p, qty=1, on_hand_qty=50,
                                   delivered_clock=DELIVER_CLOCK)
    fx.set_clock(ACT_CLOCK)
    rma = fx.open_approve_settle_return(
        ctx["order"]["id"], ctx["customer"]["id"], "DEFECTIVE", "REFUND",
        [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])

    assert rma["status"] == "REFUNDED"
    refunds = fx.list_return_refunds(rma["id"])
    assert len(refunds) == 1
    assert refunds[0]["destination"] == "ORIGINAL_PAYMENT", "cash refund"


def test_approved_exchange_rma_settles_to_exchanged_no_cash_refund(api):
    """PRD §3.8: "Settling an EXCHANGE return advances the status from APPROVED to
    EXCHANGED".
    PRD §3.8: "The exchange settlement_cents is a sign-magnitude delta: the sum over
    the lines of the exchange product's unit_price_cents multiplied by the
    return_qty, minus the RMA's refund_subtotal_cents; no restocking fee ever applies
    to an exchange."

    Design: Difficulty/non_linear_state_machine/return_authorization_branches_approved_into_refunded_vs_exchanged
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    p1 = fx.create_product(unit_price_cents=2000, tax_rate_bps=0, restocking_fee_bps=0,
                           return_window_days=30)
    p2 = fx.create_product(unit_price_cents=2000, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(p1["id"], warehouse["id"], 50)
    fx.stock_inventory(p2["id"], warehouse["id"], 50)

    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], p1["id"], 1)
    fx.checkout(order["id"], customer["id"])
    fx.capture(order["id"])
    shipment, _ = fx.create_pending_shipment(order["id"], warehouse["id"], line["id"], 1)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))
    fx.set_clock(DELIVER_CLOCK)
    fx.get_success_data(api.deliver_shipment(shipment["id"], fx.OP))
    fx.set_clock(ACT_CLOCK)

    rma = fx.open_approve_settle_return(
        order["id"], customer["id"], "WRONG_ITEM", "EXCHANGE",
        [{"order_line_id": line["id"], "return_qty": 1, "exchange_product_id": p2["id"]}])
    assert rma["status"] == "EXCHANGED"
    refunds = fx.list_return_refunds(rma["id"])
    cash = [r for r in refunds if r["destination"] == "ORIGINAL_PAYMENT"]
    assert len(cash) == 0, "delta-0 exchange creates no cash refund"


def test_defective_reason_waives_restocking_fee_on_cash_refund(api):
    """PRD §3.8: "The restocking fee is waived for a line when the RMA's reason is
    DEFECTIVE or WRONG_ITEM, or when the resolution is anything other than REFUND".
    PRD §3.8: "A base refund — used by the cash and store-credit paths — is the sum
    over the lines of the returnable subtotal plus the allocated tax minus the
    returned promo share; shipping is never refunded."

    Design: Corner/calculations/defective_reason_waives_restocking_fee_on_cash_refund
    """
    p = {"unit_price_cents": 2599, "tax_rate_bps": 875, "restocking_fee_bps": 1500,
         "return_window_days": 30}
    ctx = fx.setup_delivered_order(product_overrides=p, qty=2, on_hand_qty=100,
                                   delivered_clock=DELIVER_CLOCK)
    fx.set_clock(ACT_CLOCK)
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "DEFECTIVE", "REFUND",
                         [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])
    assert rma["restocking_fee_cents"] == 0, "DEFECTIVE waives the fee"
    assert rma["settlement_cents"] == 2827, "base refund 2599 + alloc_tax 228, no fee"


def test_exchange_cheaper_product_issues_store_credit_delta(api):
    """PRD §3.8: "A negative delta means the store owes the customer, and its
    absolute value is issued as store credit: the system creates a CreditLedgerEntry
    of kind REFUND_CREDIT for that absolute amount together with a Refund whose
    destination is STORE_CREDIT, then recomputes the customer's store_credit_cents."

    Design: Corner/calculations/exchange_cheaper_product_issues_store_credit_delta
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    p1 = fx.create_product(unit_price_cents=2599, tax_rate_bps=0,
                           restocking_fee_bps=1500, return_window_days=30)
    p2 = fx.create_product(unit_price_cents=1999, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(p1["id"], warehouse["id"], 50)
    fx.stock_inventory(p2["id"], warehouse["id"], 50)

    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], p1["id"], 1)
    fx.checkout(order["id"], customer["id"])
    fx.capture(order["id"])
    shipment, _ = fx.create_pending_shipment(order["id"], warehouse["id"], line["id"], 1)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))
    fx.set_clock(DELIVER_CLOCK)
    fx.get_success_data(api.deliver_shipment(shipment["id"], fx.OP))
    fx.set_clock(ACT_CLOCK)

    rma = fx.open_approve_settle_return(
        order["id"], customer["id"], "WRONG_ITEM", "EXCHANGE",
        [{"order_line_id": line["id"], "return_qty": 1, "exchange_product_id": p2["id"]}])
    assert rma["status"] == "EXCHANGED"
    assert rma["settlement_cents"] == -600, "1999 - 2599 (store owes)"

    customer_after = fx.get_customer(customer["id"])
    assert customer_after["store_credit_cents"] == 600
