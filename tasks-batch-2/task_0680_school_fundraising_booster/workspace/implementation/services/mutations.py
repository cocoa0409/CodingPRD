"""Shared mutation helpers and cascades (PRD §2.4, §3.2, §3.3).

A mutation refreshes updated_at and increments version. When one request fans
out to several resources, each affected resource independently records its own
mutation (own updated_at + version bump).
"""

from db import db, now_ts


def touch(resource):
    """Record a mutation on a resource: bump version, refresh updated_at."""
    resource["updated_at"] = now_ts()
    resource["version"] = resource.get("version", 0) + 1


def cancel_order_fulfillment(order):
    """Drive an order's fulfillment_status -> CANCELLED and release its
    reservations. Caller has already established the order qualifies. Records a
    mutation on the order; reserved_qty is recomputed on read so products need no
    direct write."""
    order["fulfillment_status"] = "CANCELLED"
    touch(order)


def cascade_close_campaign(campaign):
    """Campaign ACTIVE -> CLOSED cascade (PRD §3.2):
      - Orders with payment_status==PENDING and fulfillment_status in {PLACED,
        CONFIRMED} -> fulfillment CANCELLED (releases reservations on read).
      - Pledges with status==PROMISED -> CANCELLED.
      - VolunteerShifts with status==OPEN -> CANCELLED.
    Each affected resource records its own mutation."""
    cid = campaign["id"]
    for order in db.orders.values():
        if order["campaign_id"] != cid:
            continue
        if order["payment_status"] == "PENDING" and \
                order["fulfillment_status"] in ("PLACED", "CONFIRMED"):
            cancel_order_fulfillment(order)
    for pledge in db.pledges.values():
        if pledge["campaign_id"] != cid:
            continue
        if pledge["status"] == "PROMISED":
            pledge["status"] = "CANCELLED"
            touch(pledge)
    for shift in db.shifts.values():
        if shift["campaign_id"] != cid:
            continue
        if shift["status"] == "OPEN":
            shift["status"] = "CANCELLED"
            touch(shift)


def cascade_block_seller(seller):
    """Seller ACTIVE -> BLOCKED cascade (PRD §3.3):
      - Orders crediting this seller with payment_status==PENDING and
        fulfillment_status in {PLACED, CONFIRMED} -> fulfillment CANCELLED.
      - Pledges crediting this seller with status==PROMISED -> CANCELLED.
    Already-settled money is untouched: credited_cents / earned_prize_tier_id
    are computed-on-read and are unaffected (settled orders/pledges remain)."""
    sid = seller["id"]
    for order in db.orders.values():
        if order["seller_id"] != sid:
            continue
        if order["payment_status"] == "PENDING" and \
                order["fulfillment_status"] in ("PLACED", "CONFIRMED"):
            cancel_order_fulfillment(order)
    for pledge in db.pledges.values():
        if pledge["seller_id"] != sid:
            continue
        if pledge["status"] == "PROMISED":
            pledge["status"] = "CANCELLED"
            touch(pledge)
