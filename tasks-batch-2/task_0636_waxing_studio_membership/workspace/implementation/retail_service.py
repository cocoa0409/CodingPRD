"""Retail attach + confirmation (PRD 3.7), calc retail_net."""
from db import db
from errors import err
from clock import clock
from mutate import touch
from util import new_id, round_half_up
from credits import membership_credit_balance  # noqa: F401 (kept for parity)


def _has_active_membership(member_id):
    for mb in db.memberships.values():
        if mb["member_id"] == member_id and mb["status"] == "ACTIVE":
            return True
    return False


def compute_retail_net(product, quantity, member_id):
    """calc retail_net — round per unit, then multiply (PRD 2.8 / 3.7)."""
    gross = product["unit_price_cents"] * quantity
    if _has_active_membership(member_id):
        per_unit_discount = round_half_up(product["unit_price_cents"]
                                          * product["member_discount_pct"])
    else:
        per_unit_discount = 0
    discount = per_unit_discount * quantity
    net = gross - discount
    if net < 0:
        net = 0
    return gross, discount, net


def create_retail_sale(member, reservation, product, quantity):
    # PRD 3.7: begins in PENDING; no stock decremented; provisional money.
    gross, discount, net = compute_retail_net(product, quantity, member["id"])
    rid = new_id()
    now = clock.get()
    rs = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "member_id": member["id"],
        "reservation_id": reservation["id"],
        "product_id": product["id"],
        "quantity": quantity,
        "status": "PENDING",
        "gross_cents": gross,
        "discount_cents": discount,
        "net_cents": net,
    }
    db.retail_sales[rid] = rs
    return rs


def confirm(rs):
    # PRD 3.7: confirm a PENDING sale only after the attached visit COMPLETED and
    # product stock_qty >= quantity. OCC guarded by expected_product_version
    # (checked in the route). Decrements stock; finalizes money.
    if rs["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "retail sale not PENDING")
    reservation = db.reservations.get(rs["reservation_id"])
    if reservation is None or reservation["booking_status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "attached visit not COMPLETED")
    product = db.products[rs["product_id"]]
    if product["stock_qty"] < rs["quantity"]:
        raise err("ERR_OUT_OF_STOCK", "insufficient stock")
    gross, discount, net = compute_retail_net(product, rs["quantity"], rs["member_id"])
    rs["gross_cents"] = gross
    rs["discount_cents"] = discount
    rs["net_cents"] = net
    product["stock_qty"] -= rs["quantity"]
    touch(product)
    rs["status"] = "CONFIRMED"
    touch(rs)
    return rs


def void(rs):
    # PRD 3.7: void a PENDING sale; no stock change.
    if rs["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "retail sale not PENDING")
    rs["status"] = "VOIDED"
    touch(rs)
    return rs
