"""The money ledger: movements, balances, the refund waterfall, gross sales, payout."""

from datetime import timedelta

import config
from db import DB, new_id
from errors import ApiError
from tsutil import lt, ts_canonical, ts_shift

CREDIT_KINDS = ("SHORTFALL_CREDIT", "PREPAY_DEPOSIT", "CREDIT_REDEEM")
COUNTED_ORDER_STATES = ("CONFIRMED", "IN_PRODUCTION", "READY", "FULFILLED")


def baker_of_order(order):
    window = DB.get("offer_windows", order.get("offer_window_id"))
    if window is not None:
        return DB.get("bakers", window.get("baker_id"))
    cust = DB.get("customers", order.get("customer_id"))
    if cust is not None:
        return DB.get("bakers", cust.get("baker_id"))
    return None


def movements():
    return DB.values("money_movements")


def create_movement(now, customer_id, ledger_scope, movement_kind, reason,
                    amount_cents, order_id=None, payment_id=None,
                    subscription_id=None, legs=None):
    """An immutable ledger entry: id and created_at only, no version, no updated_at."""
    stamp = ts_canonical(now.dt)
    rec = {
        "id": new_id(),
        "created_at": stamp,
        "customer_id": customer_id,
        "order_id": order_id,
        "payment_id": payment_id,
        "subscription_id": subscription_id,
        "ledger_scope": ledger_scope,
        "movement_kind": movement_kind,
        "reason": reason,
        "amount_cents": amount_cents,
        "leg_tip_cents": 0,
        "leg_delivery_fee_cents": 0,
        "leg_subtotal_cents": 0,
        "leg_credit_cents": 0,
        # credit-bearing movements expire; refunds carry none
        # derived from created_at, so it renders in created_at's style
        "expires_at": (ts_shift(stamp, timedelta(days=config.CREDIT_EXPIRY_DAYS))
                       if movement_kind in CREDIT_KINDS else None),
    }
    if legs:
        rec["leg_tip_cents"] = legs[0]
        rec["leg_delivery_fee_cents"] = legs[1]
        rec["leg_subtotal_cents"] = legs[2]
        rec["leg_credit_cents"] = legs[3]
    DB.coll("money_movements")[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# balances
# ---------------------------------------------------------------------------

def credit_balance(customer_id, now):
    total = 0
    for m in DB.coll("money_movements").values():
        if m.get("customer_id") != customer_id:
            continue
        if m.get("ledger_scope") != "CUSTOMER_CREDIT":
            continue
        if m.get("movement_kind") not in CREDIT_KINDS:
            continue
        exp = m.get("expires_at")
        if exp is not None and not lt(now, exp):
            continue
        total += m.get("amount_cents") or 0
    return total


def refresh_credit_balance(customer, now):
    customer["credit_balance_cents"] = credit_balance(customer["id"], now)
    return customer["credit_balance_cents"]


def prepaid_balance(subscription_id):
    total = 0
    for m in DB.coll("money_movements").values():
        if m.get("subscription_id") != subscription_id:
            continue
        if m.get("ledger_scope") != "SUBSCRIPTION_PREPAID":
            continue
        total += m.get("amount_cents") or 0
    return total


def refresh_prepaid_balance(subscription):
    subscription["prepaid_balance_cents"] = prepaid_balance(subscription["id"])
    return subscription["prepaid_balance_cents"]


# ---------------------------------------------------------------------------
# refund waterfall (calculations.refund_waterfall)
# ---------------------------------------------------------------------------

def prior_refund_legs(order_id):
    tip = fee = sub = cred = 0
    for m in DB.coll("money_movements").values():
        if m.get("order_id") != order_id or m.get("movement_kind") != "REFUND":
            continue
        tip += m.get("leg_tip_cents") or 0
        fee += m.get("leg_delivery_fee_cents") or 0
        sub += m.get("leg_subtotal_cents") or 0
        cred += m.get("leg_credit_cents") or 0
    return tip, fee, sub, cred


def waterfall(order, amount_cents):
    """The four legs, in the order fixed by REFUND_WATERFALL_ORDER."""
    ptip, pfee, psub, pcred = prior_refund_legs(order["id"])
    available = [
        (order.get("tip_cents") or 0) - ptip,
        (order.get("delivery_fee_cents") or 0) - pfee,
        (order.get("subtotal_cents") or 0) + (order.get("tax_total_cents") or 0) - psub,
        (order.get("credit_applied_cents") or 0) - pcred,
    ]
    remaining = amount_cents
    legs = [0, 0, 0, 0]
    for i in range(4):
        avail = available[i] if available[i] > 0 else 0
        take = remaining if remaining < avail else avail
        if take < 0:
            take = 0
        legs[i] = take
        remaining -= take
    if remaining > 0:
        raise ApiError("ERR_REFUND_EXCEEDS_CAPTURED",
                       "The waterfall legs cannot absorb the requested amount.")
    return legs


def refundable_remainder(payment):
    return (payment.get("captured_cents") or 0) - (payment.get("refunded_cents") or 0)


# ---------------------------------------------------------------------------
# statutory / settlement aggregates
# ---------------------------------------------------------------------------

def counted_orders(baker):
    out = []
    cap_year = baker.get("cap_year")
    for order in DB.coll("orders").values():
        if order.get("order_status") not in COUNTED_ORDER_STATES:
            continue
        owner = baker_of_order(order)
        if owner is None or owner["id"] != baker["id"]:
            continue
        placed = order.get("placed_at")
        if placed is None or placed.dt.year != cap_year:
            continue
        out.append(order)
    return out


def annual_gross_sales(baker):
    """calculations.annual_gross_sales_to_date -- tips are NEVER counted."""
    orders = counted_orders(baker)
    ids = {o["id"] for o in orders}
    gross = 0
    for o in orders:
        gross += ((o.get("subtotal_cents") or 0)
                  + (o.get("tax_total_cents") or 0)
                  + (o.get("delivery_fee_cents") or 0))
    refunded = 0
    for m in DB.coll("money_movements").values():
        if m.get("movement_kind") != "REFUND":
            continue
        if m.get("order_id") not in ids:
            continue
        refunded += ((m.get("leg_subtotal_cents") or 0)
                     + (m.get("leg_delivery_fee_cents") or 0))
    return gross - refunded


def refresh_gross_sales(baker):
    baker["annual_gross_sales_cents"] = annual_gross_sales(baker)
    return baker["annual_gross_sales_cents"]


def _in_payout_period(baker, ts):
    start = baker.get("payout_period_start")
    if start is None or ts is None:
        return False
    end = ts_shift(start, timedelta(days=config.PAYOUT_PERIOD_DAYS))
    # left-inclusive, right-exclusive
    return (not lt(ts, start)) and lt(ts, end)


def payout_period_net(baker):
    """calculations.payout_period_net over the half-open fortnight."""
    order_ids = set()
    for order in DB.coll("orders").values():
        owner = baker_of_order(order)
        if owner is not None and owner["id"] == baker["id"]:
            order_ids.add(order["id"])
    captured = 0
    for pay in DB.coll("payments").values():
        if pay.get("order_id") not in order_ids:
            continue
        if pay.get("payment_state") not in ("CAPTURED", "SETTLED"):
            continue
        if not _in_payout_period(baker, pay.get("created_at")):
            continue
        captured += pay.get("captured_cents") or 0
    refunded = 0
    for m in DB.coll("money_movements").values():
        if m.get("movement_kind") != "REFUND":
            continue
        if m.get("order_id") not in order_ids:
            continue
        if not _in_payout_period(baker, m.get("created_at")):
            continue
        refunded += m.get("amount_cents") or 0
    return captured - refunded


def refresh_payout_net(baker):
    baker["payout_net_cents"] = payout_period_net(baker)
    return baker["payout_net_cents"]
