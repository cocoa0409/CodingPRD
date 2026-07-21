"""payout_net_amount (PRD §3.9) — seven pinned steps, no back-propagation."""
from decimal import Decimal

import db
from services import constants as C
from services.money import cents

_CONTRIBUTING_PAYMENT_STATUSES = (
    "PAID",
    "REFUND_PENDING",
    "PARTIALLY_REFUNDED",
    "REFUNDED",
)


def _contributing_orders(event_id):
    return [
        o
        for o in db.store.orders.values()
        if o["event_id"] == event_id
        and o["payment_status"] in _CONTRIBUTING_PAYMENT_STATUSES
    ]


def reserve_rate_for(snapshot):
    if snapshot >= C.RESERVE_TIER_A_MIN_SCORE:
        return C.RESERVE_TIER_A_RATE
    if snapshot >= C.RESERVE_TIER_B_MIN_SCORE:
        return C.RESERVE_TIER_B_RATE
    if snapshot >= C.RESERVE_TIER_C_MIN_SCORE:
        return C.RESERVE_TIER_C_RATE
    return C.RESERVE_TIER_D_RATE


def compute_chain(event, snapshot):
    orders = _contributing_orders(event["id"])

    # 1
    gross = sum(o["organizer_gross_cents"] for o in orders)

    # 2
    refunds = 0
    for rr in db.store.refund_requests.values():
        if rr["status"] != "SETTLED":
            continue
        order = db.store.orders.get(rr["order_id"])
        if order is not None and order["event_id"] == event["id"]:
            refunds += rr["organizer_charged_cents"]

    # 3
    platform_fee = sum(o["fee_total_cents"] for o in orders) if event["fee_mode"] == "ABSORB" else 0

    # 4
    reserve_basis = gross - refunds - platform_fee

    # 5 — from the FROZEN snapshot, never a live recompute
    rate = reserve_rate_for(snapshot)

    # 6
    reserve = max(0, cents(rate * Decimal(reserve_basis)))

    # 7
    net = reserve_basis - reserve

    return {
        "gross_cents": gross,
        "refunds_cents": refunds,
        "platform_fee_cents": platform_fee,
        "reserve_basis_cents": reserve_basis,
        "reserve_rate": float(rate),
        "reserve_cents": reserve,
        "net_amount_cents": net,
    }


def apply_chain(payout, event):
    payout.update(compute_chain(event, payout["reliability_score_snapshot"]))
    return payout
