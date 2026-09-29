"""Trial-order construction and the delivery cascade."""
from db import base_record, db, now, touch
from services import calc, entities
from util import add_days


def new_order(customer, model, bundle, channel, retail_partner_id,
              gross_price_cents, exchanged_from_order_id=None,
              exchange_chain_depth=0):
    """Mints a CREATED / NOT_STARTED order and opens its money ledger."""
    percent_off_bps = bundle["percent_off_bps"] if bundle else 0
    discount, paid = calc.order_pricing(gross_price_cents, percent_off_bps)
    record = base_record()
    record.update({
        "customer_id": customer["id"],
        "model_id": model["id"],
        "bundle_id": bundle["id"] if bundle else None,
        "retail_partner_id": retail_partner_id,
        "exchanged_from_order_id": exchanged_from_order_id,
        "channel": channel,
        "gross_price_cents": gross_price_cents,
        "bundle_discount_cents": discount,
        "paid_amount_cents": paid,
        "fulfillment_status": "CREATED",
        "trial_status": "NOT_STARTED",
        "delivered_at": None,
        "break_in_ends_at": None,
        "trial_ends_at": None,
        "nights_slept": None,
        "exchange_chain_depth": exchange_chain_depth,
        "goodwill_credit_cents": 0,
        "price_match_credit_cents": 0,
        "refunded_total_cents": 0,
        "outstanding_refundable_cents": paid,
        "retained_amount_cents": 0,
        "_nights_frozen": False,
    })
    db.trial_orders[record["id"]] = record
    return record


def household_delivered_orders(household_hash):
    ids = {c["id"] for c in entities.household_customers(household_hash)}
    return [o for o in db.trial_orders.values()
            if o["customer_id"] in ids and o["delivered_at"] is not None]


def household_live_orders(household_hash, exclude_customer_id=None):
    ids = {c["id"] for c in entities.household_customers(household_hash)
           if c["id"] != exclude_customer_id}
    return [o for o in db.trial_orders.values()
            if o["customer_id"] in ids
            and o["fulfillment_status"] in entities.LIVE_FULFILLMENT]


def deliver(order, customer, model):
    """Stamps delivery, opens the break-in window, counts the trial and runs the
    two household fraud detectors."""
    clock = now()
    order["fulfillment_status"] = "DELIVERED"
    order["delivered_at"] = clock
    order["break_in_ends_at"] = add_days(clock, model["break_in_nights"])
    order["trial_ends_at"] = add_days(clock, model["trial_nights"])
    order["trial_status"] = "BREAK_IN"
    order["nights_slept"] = 0

    customer["lifetime_trial_count"] = customer["lifetime_trial_count"] + 1

    household = entities.household_customers(customer["household_hash"])
    household_ids = {c["id"] for c in household}
    others_delivered = [
        o for o in db.trial_orders.values()
        if o["id"] != order["id"]
        and o["customer_id"] in household_ids
        and o["delivered_at"] is not None
    ]
    # Two independent detectors; both may fire on the same delivery.
    if any(o["customer_id"] != customer["id"] for o in others_delivered):
        entities.add_signal(customer, "HOUSEHOLD_MATCH")
    if any(o["channel"] != order["channel"] for o in others_delivered):
        entities.add_signal(customer, "MULTI_CHANNEL")

    entities.derive_customer(customer)
    touch(customer)
    touch(order)
    return order


def freeze_nights(order, nights):
    order["nights_slept"] = nights
    order["_nights_frozen"] = True
