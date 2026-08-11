"""PACA trust exposure, credit exposure set filtering, and the CREDIT hold
branch-and-release (PRD §2.6, §3.6, §3.7)."""
from test_helpers import (
    api_client,
    create_customer,
    create_invoiced_order,
    create_ordered_lot,
    create_pending_order,
    create_disputed_lot,
    confirm_order,
    get_customer,
    get_invoice,
    get_lot,
    get_order,
    get_shipper,
    get_success_data,
    patch_customer,
    post_payment,
    resolve_dispute,
    set_clock,
    setup_accepted_lot,
    setup_credit_hold_scenario,
    setup_market_day,
    validate_success,
)
from test_helpers import BILLING_HEADERS, RECEIVER_HEADERS, SALES_HEADERS


# --- Credit hold branch and release (Difficulty/non_linear_state_machine) -----

def test_trust_claim_holds_confirmed_order_for_credit(api):
    """PRD §3.7: "Second, every `PAST_DUE` invoice whose clock date is more than 30
    days past its `due_date` and whose `balance_cents` is still positive becomes
    `TRUST_CLAIMED`; the trust claim suspends the customer (`status` becomes
    `SUSPENDED`), moves every `CONFIRMED` order belonging to that customer to
    `ON_HOLD` with `hold_reason` set to `CREDIT`, releases those orders' line
    reservations, and recomputes the customer's `credit_exposure_cents`."

    Design: Difficulty/non_linear_state_machine/sales_order_credit_hold_branch_and_release
    """
    env = setup_credit_hold_scenario()
    assert env["close1"]["invoices_marked_past_due"] == 1
    assert env["close2"]["invoices_trust_claimed"] == 1

    invoice1 = get_invoice(env["invoice1"]["id"])
    assert invoice1["status"] == "TRUST_CLAIMED"
    customer = get_customer(env["customer"]["id"])
    assert customer["status"] == "SUSPENDED"
    order2 = get_order(env["order2"]["id"])
    assert order2["status"] == "ON_HOLD"
    assert order2["hold_reason"] == "CREDIT"
    lot = get_lot(env["lot"]["id"])
    # order1 delivered 1 unit (sold); order2's 2-unit reservation was released.
    assert lot["sold_units"] == 1
    assert lot["reserved_units"] == 0


def test_credit_hold_releases_back_to_confirmed_after_settlement(api):
    """PRD §2.9: "voiding an `ISSUED` credit memo restores the lot's `payable_cents`
    to exactly `adjusted_cost_cents` minus the remaining `ISSUED` memos, and a
    `CREDIT` hold on an order can be released back to `CONFIRMED` once the cause is
    cleared."
    PRD §3.6: "The confirm action accepts an order in `PENDING`, or one in `ON_HOLD`
    whose `hold_reason` is `CREDIT` — a `COLD_CHAIN` hold can only be cancelled, never
    confirmed."

    Design: Difficulty/non_linear_state_machine/sales_order_credit_hold_branch_and_release
    """
    env = setup_credit_hold_scenario()
    # Settle the trust-claimed invoice (total 7500; long past the discount window).
    post_payment(env["invoice1"]["id"], 7500)
    assert get_invoice(env["invoice1"]["id"])["status"] == "PAID"
    # Only MarketAdmin can restore a suspended customer (OCC-guarded write).
    customer = get_customer(env["customer"]["id"])
    patch_customer(customer["id"], customer["version"], status="ACTIVE")

    released = get_success_data(api_client.confirm_order(env["order2"]["id"],
                                                         SALES_HEADERS))
    assert released["status"] == "CONFIRMED"
    assert released["hold_reason"] is None
    lot = get_lot(env["lot"]["id"])
    assert lot["reserved_units"] == 2, "the reservation is re-taken on the revert path"


# --- Breadth: credit exposure set filtering ------------------------------------

def test_credit_exposure_filters_order_and_invoice_status_sets(api):
    """PRD §2.6: "A `Customer`'s `credit_exposure_cents` is the sum of `balance_cents`
    over that customer's invoices in `OPEN`, `PAST_DUE`, or `TRUST_CLAIMED`, plus the
    sum of `subtotal_cents` over that customer's orders in `CONFIRMED`, `ON_HOLD`,
    `PICKED`, or `DELIVERED`. Orders in `CANCELLED` or `INVOICED` are excluded."

    Design: Corner/calculations/credit_exposure_filters_order_and_invoice_status_sets
    """
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=1000000, terms_days=10)
    order1 = create_pending_order(customer["id"], base["lot"]["id"], quantity=1,
                                  unit_price=50.00, pallet_count=1)
    confirm_order(order1["id"])
    assert get_customer(customer["id"])["credit_exposure_cents"] == 5000

    get_success_data(api_client.pick_order(order1["id"], RECEIVER_HEADERS))
    get_success_data(api_client.deliver_order(order1["id"], RECEIVER_HEADERS))
    invoice1 = get_success_data(
        api_client.create_invoice({"sales_order_id": order1["id"]}, BILLING_HEADERS))
    # INVOICED order drops out; the OPEN invoice balance 5000 + 2500 deposit counts.
    assert get_customer(customer["id"])["credit_exposure_cents"] == 7500

    # Pay inside the window: discount 150, payment 7350 -> PAID -> exposure 0.
    set_clock("2026-05-02T09:00:00Z")
    post_payment(invoice1["id"], 7350)
    assert get_invoice(invoice1["id"])["status"] == "PAID"
    assert get_customer(customer["id"])["credit_exposure_cents"] == 0

    order2 = create_pending_order(customer["id"], base["lot"]["id"], quantity=2,
                                  unit_price=50.00, delivery_date="2026-05-03")
    confirm_order(order2["id"])
    assert get_customer(customer["id"])["credit_exposure_cents"] == 10000

    get_success_data(api_client.cancel_order(order2["id"], SALES_HEADERS))
    assert get_customer(customer["id"])["credit_exposure_cents"] == 0


def test_shipper_trust_exposure_drops_rejected_lots(api):
    """PRD §2.6: "A `Shipper`'s `trust_exposure_cents` is the sum of `payable_cents`
    over all of that shipper's lots whose `status` is one of `ORDERED`, `RECEIVED`,
    `INSPECTED`, `DISPUTED`, or `ACCEPTED`. Lots in `REJECTED` or `CLOSED` drop out of
    the exposure set entirely."

    Design: Corner/calculations/shipper_trust_exposure_drops_rejected_lots
    """
    base = setup_market_day()
    lot_a = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                               quantity_units=10, shipper_unit_price=10.00)
    lot_b, _ = create_disputed_lot(base["shipper"]["id"], base["commodity"]["id"],
                                   defect_pct=30, quantity_units=10,
                                   shipper_unit_price=10.00)
    # ORDERED lot 10000 + DISPUTED lot 10000: both inside the exposure status set.
    assert get_shipper(base["shipper"]["id"])["trust_exposure_cents"] == 20000

    resolved = resolve_dispute(lot_b["id"], "REJECT_TO_SHIPPER")
    assert resolved["status"] == "REJECTED"
    assert resolved["payable_cents"] == 0
    # Only the still-ORDERED sibling continues to count.
    assert get_shipper(base["shipper"]["id"])["trust_exposure_cents"] == 10000
