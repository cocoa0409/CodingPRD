from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, g, request

from auth import auth, check_own
from envelope import created, list_response, success
from errors import err
from services import eligible_demo_credits, rhu, try_promote
from store import db, iso, new_entity, now, parse_date, parse_dt, pub, touch
from validate import body, get_or_404, req_date, req_int, req_str

bp = Blueprint("demo", __name__)

ALL_ROLES = ("Customer", "FrontDesk", "Technician", "Manager")


# ---------------------------------------------------------------------------
# Demo credits
# ---------------------------------------------------------------------------

@bp.post("/shop/demo-credits")
def create_demo_credit():
    auth("FrontDesk", "Manager")
    b = body()
    cust_id = b.get("customer_id")
    unit_id = b.get("equipment_item_id")
    if cust_id is not None:
        get_or_404(db.customers, cust_id, "Customer")
    if unit_id is not None:
        get_or_404(db.equipment_items, unit_id, "Equipment item")
    cust_id = req_str(b, "customer_id")
    unit_id = req_str(b, "equipment_item_id")
    demo_date = req_date(b, "demo_date")
    fee = req_int(b, "fee_paid_cents", minimum=1)
    unit = db.equipment_items[unit_id]
    if unit["tier"] != "DEMO":
        raise err("ERR_NOT_DEMO_TIER",
                  "Demo credits can only be recorded against DEMO-tier units")
    expires = datetime.combine(parse_date(demo_date) + timedelta(days=90),
                               time.min, tzinfo=timezone.utc)
    credit = new_entity({
        "customer_id": cust_id,
        "equipment_item_id": unit_id,
        "demo_date": demo_date,
        "fee_paid_cents": fee,
        "credit_cents": fee,  # 100% of the demo fee becomes purchase credit
        "expires_at": iso(expires),
        "status": "ACTIVE",
    })
    db.demo_credits[credit["id"]] = credit
    return created(pub(credit))


@bp.get("/shop/demo-credits/<did>")
def get_demo_credit(did):
    auth(*ALL_ROLES)
    credit = get_or_404(db.demo_credits, did, "Demo credit")
    check_own(credit["customer_id"])
    return success(pub(credit))


@bp.get("/shop/demo-credits")
def list_demo_credits():
    auth(*ALL_ROLES)
    items = list(db.demo_credits.values())
    if g.user_role == "Customer":
        items = [c for c in items if c["customer_id"] == g.user_id]
    customer_id = request.args.get("customer_id")
    equipment_item_id = request.args.get("equipment_item_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    if equipment_item_id is not None:
        items = [c for c in items if c["equipment_item_id"] == equipment_item_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

@bp.post("/shop/purchase-orders")
def create_purchase_order():
    auth("Customer", "FrontDesk", "Manager")
    b = body()
    cust_id = b.get("customer_id")
    if g.user_role == "Customer" and cust_id is not None and cust_id != g.user_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP",
                  "Customers may only create orders for themselves")
    if cust_id is not None:
        get_or_404(db.customers, cust_id, "Customer")
    unit_id = b.get("equipment_item_id")
    if unit_id is not None:
        get_or_404(db.equipment_items, unit_id, "Equipment item")
    credit_id = b.get("demo_credit_id")
    if credit_id is not None:
        get_or_404(db.demo_credits, credit_id, "Demo credit")
    cust_id = req_str(b, "customer_id")
    unit_id = req_str(b, "equipment_item_id")
    unit = db.equipment_items[unit_id]
    if unit["status"] != "AVAILABLE":
        raise err("ERR_EQUIPMENT_NOT_AVAILABLE",
                  "Only an AVAILABLE unit can be purchased")
    if credit_id is not None:
        credit = db.demo_credits[credit_id]
        # expiry check runs first, then ownership/status
        if parse_dt(credit["expires_at"]) <= now():
            raise err("ERR_DEMO_CREDIT_EXPIRED",
                      "The demo credit has expired")
        if credit["customer_id"] != cust_id or credit["status"] != "ACTIVE":
            raise err("ERR_DEMO_CREDIT_NOT_REDEEMABLE",
                      "The demo credit is not redeemable for this customer")
    if unit["tier"] == "DEMO":
        list_price = rhu(Decimal(unit["purchase_price_cents"]) * Decimal("0.75"))
    else:
        list_price = unit["purchase_price_cents"]
    cap = rhu(Decimal("0.30") * Decimal(list_price))
    if credit_id is not None:
        applicable = [db.demo_credits[credit_id]]
    else:
        applicable = eligible_demo_credits(cust_id)
    running = 0
    applied_ids = []
    for c in applicable:
        if running >= cap:
            break
        applied_ids.append(c["id"])
        running += c["credit_cents"]
    credit_applied = min(running, cap)
    order = new_entity({
        "customer_id": cust_id,
        "equipment_item_id": unit_id,
        "demo_credit_id": credit_id,
        "list_price_cents": list_price,
        "credit_applied_cents": credit_applied,
        "amount_due_cents": list_price - credit_applied,
        "status": "PENDING",
    })
    db.purchase_orders[order["id"]] = order
    db.order_credits[order["id"]] = applied_ids
    unit["status"] = "RESERVED"
    touch(unit)
    return created(pub(order))


@bp.get("/shop/purchase-orders/<oid>")
def get_purchase_order(oid):
    auth(*ALL_ROLES)
    order = get_or_404(db.purchase_orders, oid, "Purchase order")
    check_own(order["customer_id"])
    return success(pub(order))


@bp.get("/shop/purchase-orders")
def list_purchase_orders():
    auth(*ALL_ROLES)
    items = list(db.purchase_orders.values())
    if g.user_role == "Customer":
        items = [o for o in items if o["customer_id"] == g.user_id]
    customer_id = request.args.get("customer_id")
    equipment_item_id = request.args.get("equipment_item_id")
    demo_credit_id = request.args.get("demo_credit_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if equipment_item_id is not None:
        items = [o for o in items if o["equipment_item_id"] == equipment_item_id]
    if demo_credit_id is not None:
        items = [o for o in items if o["demo_credit_id"] == demo_credit_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items)


@bp.post("/shop/purchase-orders/<oid>/pay")
def pay_purchase_order(oid):
    auth("Customer", "FrontDesk", "Manager")
    order = get_or_404(db.purchase_orders, oid, "Purchase order")
    check_own(order["customer_id"])
    if order["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING order can be paid")
    order["status"] = "PAID"
    touch(order)
    for cid in db.order_credits.get(order["id"], []):
        credit = db.demo_credits[cid]
        credit["status"] = "REDEEMED"
        touch(credit)
    return success(pub(order))


@bp.post("/shop/purchase-orders/<oid>/fulfill")
def fulfill_purchase_order(oid):
    auth("FrontDesk", "Manager")
    order = get_or_404(db.purchase_orders, oid, "Purchase order")
    if order["status"] != "PAID":
        raise err("ERR_INVALID_STATE", "Only a PAID order can be fulfilled")
    order["status"] = "FULFILLED"
    touch(order)
    unit = db.equipment_items[order["equipment_item_id"]]
    unit["status"] = "SOLD"
    touch(unit)
    return success(pub(order))


@bp.post("/shop/purchase-orders/<oid>/cancel")
def cancel_purchase_order(oid):
    auth("Customer", "FrontDesk", "Manager")
    order = get_or_404(db.purchase_orders, oid, "Purchase order")
    check_own(order["customer_id"])
    if order["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING order can be cancelled")
    order["status"] = "CANCELLED"
    touch(order)
    # compensation: free the unit; credits are left untouched
    unit = db.equipment_items[order["equipment_item_id"]]
    if unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        touch(unit)
        try_promote(unit)
    return success(pub(order))
