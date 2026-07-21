"""Customer, loyalty-adjustment, and loyalty-event endpoints."""
from flask import Blueprint

import store
import api as h
import serialize as s

bp = Blueprint("customers", __name__)

LOYALTY_REASONS = {"ORDER_EARN", "ORDER_REVERSAL", "FINAL_ADJUSTMENT",
                   "EXCHANGE_REVERSAL", "PROMOTION", "CORRECTION"}


@bp.post("/boutique/customers")
def create_customer():
    h.require_role("StoreManager")
    body = h.get_body()
    h.require_fields(body, ["full_name", "email"])
    if not isinstance(body["full_name"], str) or not isinstance(body["email"], str):
        raise h.ApiError("ERR_VALIDATION", "full_name and email must be strings")
    phone = body.get("phone")
    pm = body.get("post_mastectomy_flag", False)
    if not isinstance(pm, bool):
        raise h.ApiError("ERR_VALIDATION", "post_mastectomy_flag must be boolean")
    rec = store.new_record({
        "full_name": body["full_name"],
        "email": body["email"],
        "phone": phone,
        "post_mastectomy_flag": pm,
        "loyalty_points": 0,
        "store_credit_cents": 0,
    })
    store.customers[rec["id"]] = rec
    return h.success(s.customer_out(rec), status=201)


@bp.get("/boutique/customers/<cid>")
def get_customer(cid):
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    rec = h.lookup("customers", cid)
    return h.success(s.customer_out(rec))


@bp.post("/boutique/customers/<cid>/loyalty-adjustments")
def loyalty_adjustment(cid):
    h.require_role("StoreManager")
    customer = h.lookup("customers", cid)
    body = h.get_body()
    h.require_fields(body, ["points_delta", "reason"])
    delta = h.require_int(body, "points_delta")
    h.check_enum(body["reason"], LOYALTY_REASONS, "reason")
    order_id = body.get("order_id")
    if order_id is not None:
        h.lookup("orders", order_id)
    ev = h.append_loyalty_event(customer, delta, body["reason"], order_id)
    return h.success(s.loyalty_event_out(ev), status=201)


@bp.get("/boutique/loyalty-events/<eid>")
def get_loyalty_event(eid):
    h.require_role("Customer", "StoreManager", "BillingClerk")
    ev = h.lookup_loyalty_event(eid)
    return h.success(s.loyalty_event_out(ev))


@bp.get("/boutique/loyalty-events")
def list_loyalty_events():
    h.require_role("Customer", "StoreManager", "BillingClerk")
    customer_id = h.filter_arg("customer_id")
    order_id = h.filter_arg("order_id")

    def pred(r):
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if order_id is not None and r.get("order_id") != order_id:
            return False
        return True

    return h.list_response("loyalty_events", s.loyalty_event_out, pred)
