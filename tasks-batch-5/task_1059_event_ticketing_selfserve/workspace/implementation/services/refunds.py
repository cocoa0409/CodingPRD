"""refund_amount (PRD §3.8) — the two policy variants under both fee modes."""
from decimal import Decimal

import db
from services.money import cents


def compute(order, item_refunds, policy, fee_mode):
    refunded_face = 0
    refunded_fee = 0
    for entry in item_refunds:
        item = db.store.order_items.get(entry["order_item_id"])
        if item is None:
            continue
        quantity = entry["quantity"]
        refunded_face += item["unit_price_cents"] * quantity
        refunded_fee += item["per_ticket_fee_cents"] * quantity

    subtotal = order["subtotal_cents"]
    if subtotal == 0:
        prorated_discount = 0
    else:
        prorated_discount = cents(
            Decimal(order["discount_cents"]) * Decimal(refunded_face) / Decimal(subtotal)
        )

    net_face = refunded_face - prorated_discount

    if fee_mode == "ABSORB":
        # The buyer never paid the fee, so the buyer-facing amount is identical
        # under both policies; the policies differ in the other two figures.
        refund_amount = net_face
        if policy == "FEE_RETAINED":
            platform_retained = refunded_fee
            organizer_charged = net_face
        else:
            platform_retained = 0
            organizer_charged = net_face - refunded_fee
    else:
        if policy == "FEE_RETAINED":
            refund_amount = net_face
            platform_retained = refunded_fee
            organizer_charged = net_face
        else:
            refund_amount = net_face + refunded_fee
            platform_retained = 0
            organizer_charged = net_face + refunded_fee

    return {
        "refund_amount_cents": refund_amount,
        "platform_retained_cents": platform_retained,
        "organizer_charged_cents": organizer_charged,
    }
