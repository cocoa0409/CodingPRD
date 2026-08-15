"""Ticket sales: sell (tiered pricing + service fee + capacity gate), read, list,
same-day void (with queued-redemption compensation)."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DAY_POSTURE,
    ERR_PRODUCT_INACTIVE,
    ERR_DAY_AT_CAPACITY,
    ERR_CROSS_FAIR_REFERENCE,
    ERR_SALE_NOT_ACTIVE,
    ERR_SALE_HAS_REDEMPTIONS,
)
from helpers import get_or_404, paginate, qparam, fair_id_of_sale
from middleware import authenticate, scope_to_fair
from response import ok
from services.calculations import sale_pricing
from validators import get_body, reject_unknown, req_str, req_int

bp = Blueprint("sales", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


@bp.post("/ticket-sales")
def create_sale():
    ctx = authenticate(["TicketClerk"])
    body = get_body()
    reject_unknown(body, {"product_id", "operating_day_id", "quantity", "holder_height_in"})
    product_id = req_str(body, "product_id")
    day_id = req_str(body, "operating_day_id")
    quantity = req_int(body, "quantity", lo=1)
    holder_height = req_int(body, "holder_height_in", lo=20, hi=96)
    product = db.get("products", product_id)
    scope_to_fair(ctx, product["fair_id"] if product else None)
    product = get_or_404("products", product_id)
    scope_to_fair(ctx, product["fair_id"])
    day = get_or_404("operating_days", day_id)
    if product["kind"] == "WRISTBAND" and quantity != 1:
        raise_err(ERR_INVALID_REQUEST, "WRISTBAND sales must carry quantity exactly 1")
    if day["posture"] != "OPEN":
        raise_err(ERR_INVALID_DAY_POSTURE, "Sales happen only while the day's gates are OPEN")
    if product["active"] is not True:
        raise_err(ERR_PRODUCT_INACTIVE, "An inactive product cannot be sold")
    if day["attendance_count"] >= day["max_attendance"]:
        raise_err(ERR_DAY_AT_CAPACITY, "The day has reached its attendance cap")
    if product["fair_id"] != day["fair_id"]:
        raise_err(ERR_CROSS_FAIR_REFERENCE, "The product belongs to a different fair than the operating day")

    subtotal, fee, total = sale_pricing(product["kind"], product["base_price_cents"], quantity)
    is_unlimited = product["kind"] == "WRISTBAND"
    if is_unlimited:
        granted = remaining = redeemed = forfeited = None
    else:
        granted = quantity
        remaining = quantity
        redeemed = 0
        forfeited = 0
    sale = db.register(
        "sales",
        {
            "product_id": product_id,
            "operating_day_id": day_id,
            "clerk_staff_id": ctx["user_id"],
            "holder_height_in": holder_height,
            "quantity": quantity,
            "is_unlimited": is_unlimited,
            "credits_granted": granted,
            "credits_remaining": remaining,
            "credits_redeemed": redeemed,
            "credits_forfeited": forfeited,
            "subtotal_cents": subtotal,
            "service_fee_cents": fee,
            "total_charged_cents": total,
            "status": "ACTIVE",
        },
    )
    day["attendance_count"] += 1
    touch(day)
    return ok(serialize(sale), 201)


@bp.get("/ticket-sales/<sid>")
def get_sale(sid):
    ctx = authenticate(ALL)
    sale = get_or_404("sales", sid)
    scope_to_fair(ctx, fair_id_of_sale(sale))
    return ok(serialize(sale))


@bp.get("/ticket-sales")
def list_sales():
    authenticate(ALL)
    return paginate(
        "sales",
        {
            "operating_day_id": qparam("operating_day_id"),
            "product_id": qparam("product_id"),
            "clerk_staff_id": qparam("clerk_staff_id"),
            "status": qparam("status"),
        },
    )


@bp.post("/ticket-sales/<sid>/void")
def void_sale(sid):
    ctx = authenticate(["TicketClerk"])
    sale = get_or_404("sales", sid)
    scope_to_fair(ctx, fair_id_of_sale(sale))
    body = get_body()
    reject_unknown(body, set())
    if sale["status"] != "ACTIVE":
        raise_err(ERR_SALE_NOT_ACTIVE, "Only an ACTIVE sale can be voided")
    day = db.get("operating_days", sale["operating_day_id"])
    if day["posture"] != "OPEN":
        raise_err(ERR_INVALID_DAY_POSTURE, "Voids are same-day operations gated on the OPEN posture")
    for redemption in store["redemptions"].values():
        if redemption["wristband_id"] == sale["id"] and redemption["status"] == "REDEEMED":
            raise_err(ERR_SALE_HAS_REDEMPTIONS, "A boarded redemption exists for this wristband")
    sale["status"] = "VOIDED"
    touch(sale)
    for redemption in store["redemptions"].values():
        if redemption["wristband_id"] == sale["id"] and redemption["status"] == "QUEUED":
            redemption["status"] = "VOIDED"
            touch(redemption)
    day["attendance_count"] -= 1
    touch(day)
    return ok(serialize(sale))
