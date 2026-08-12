from datetime import timedelta

from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_SUBSCRIPTION_NOT_FOUND, ERR_ADD_ON_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND, ERR_PRODUCT_INACTIVE, ERR_NOT_AN_ADD_ON_SKU,
    ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_ADD_ON_NOT_QUOTED, ERR_ADD_ON_NOT_CANCELLABLE,
    ERR_CUSTOMER_SUSPENDED, ERR_INVALID_REQUEST,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_addon
from services import (
    find_product_by_sku, earliest_scheduled_box, recompute_box_provisional,
    QUOTE_EXPIRY_DAYS,
)
from util import req_str, req_int, fmt_dt3

bp = Blueprint("addons", __name__)

READ_ROLES = ["Customer", "Agronomist", "PlatformAdmin"]


def _get_addon_or_404(aid):
    rec = store.addons.get(aid)
    if rec is None:
        raise_err(ERR_ADD_ON_NOT_FOUND, "Add-on order not found")
    return rec


def _owner_of_addon(ao):
    sub = store.subscriptions.get(ao.subscription_id)
    return sub.customer_id if sub else None


@bp.route("/api/add-ons", methods=["POST"])
def create_addon():
    body = get_body()
    subscription_id = req_str(body, "subscription_id")
    add_on_sku = req_str(body, "add_on_sku")
    qty_units = req_int(body, "qty_units")
    if qty_units <= 0:
        raise_err(ERR_INVALID_REQUEST, "Field 'qty_units' must be greater than zero")

    uid, role = authenticate(["Customer"])
    sub = store.subscriptions.get(subscription_id)
    if sub is None:
        raise_err(ERR_SUBSCRIPTION_NOT_FOUND, "Subscription not found")
    check_ownership(uid, role, sub.customer_id)
    product = find_product_by_sku(add_on_sku)
    if product is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Add-on sku '%s' does not exist" % add_on_sku)
    cust = store.customers.get(sub.customer_id)
    if cust is not None and cust.status == "SUSPENDED":
        raise_err(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED; creates are blocked")
    if sub.status != "ACTIVE":
        raise_err(ERR_SUBSCRIPTION_NOT_ACTIVE, "Add-on quote requires subscription ACTIVE")
    if not product.active:
        raise_err(ERR_PRODUCT_INACTIVE, "Add-on sku '%s' is inactive" % add_on_sku)
    if product.category not in ("PEST", "WEED") or product.add_on_flat_price_cents is None:
        raise_err(ERR_NOT_AN_ADD_ON_SKU,
                  "Add-on sku must be category PEST or WEED and carry add_on_flat_price_cents")

    ts = now()
    expires = ts + timedelta(days=QUOTE_EXPIRY_DAYS)
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        subscription_id=subscription_id, add_on_sku=add_on_sku, qty_units=qty_units,
        status="QUOTED", quoted_price_cents=qty_units * product.add_on_flat_price_cents,
        quote_expires_at=expires, attached_shipment_id=None,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    rec.raw["quote_expires_at"] = fmt_dt3(expires)
    store.addons[rec.id] = rec
    return ok(ser_addon(rec), 201)


@bp.route("/api/add-ons/<aid>", methods=["GET"])
def get_addon(aid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_addon_or_404(aid)
    check_ownership(uid, role, _owner_of_addon(rec))
    return ok(ser_addon(rec))


@bp.route("/api/add-ons", methods=["GET"])
def list_addons():
    uid, role = authenticate(READ_ROLES)
    items = list(store.addons.values())
    if role == "Customer":
        own_subs = {s.id for s in store.subscriptions.values() if s.customer_id == uid}
        items = [a for a in items if a.subscription_id in own_subs]
    for param in ("subscription_id", "attached_shipment_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if getattr(a, param) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_addon(a) for a in page], total, limit, offset)


@bp.route("/api/add-ons/<aid>/confirm", methods=["POST"])
def confirm_addon(aid):
    uid, role = authenticate(["Customer"])
    rec = _get_addon_or_404(aid)
    check_ownership(uid, role, _owner_of_addon(rec))
    if rec.status != "QUOTED":
        raise_err(ERR_ADD_ON_NOT_QUOTED, "confirm requires add-on QUOTED")
    sub = store.subscriptions.get(rec.subscription_id)
    if sub is None or sub.status != "ACTIVE":
        raise_err(ERR_SUBSCRIPTION_NOT_ACTIVE, "Add-on confirm requires subscription ACTIVE")

    rec.status = "CONFIRMED"
    box = earliest_scheduled_box(rec.subscription_id)
    if box is not None:
        rec.attached_shipment_id = box.id
        recompute_box_provisional(box)  # attach recomputes the charge and bumps the box
    # no SCHEDULED box: stays CONFIRMED, unattached, until the next box is created
    touch(rec)
    return ok(ser_addon(rec))


@bp.route("/api/add-ons/<aid>/cancel", methods=["POST"])
def cancel_addon(aid):
    uid, role = authenticate(["Customer"])
    rec = _get_addon_or_404(aid)
    check_ownership(uid, role, _owner_of_addon(rec))
    if rec.status not in ("QUOTED", "CONFIRMED"):
        raise_err(ERR_ADD_ON_NOT_CANCELLABLE, "cancel requires add-on QUOTED or CONFIRMED")

    attached = rec.attached_shipment_id
    rec.status = "CANCELLED"
    rec.attached_shipment_id = None
    if attached is not None:
        box = store.shipments.get(attached)
        if box is not None and box.fulfillment_status != "CANCELLED":
            # detach compensation: recompute the live box's provisional charge
            recompute_box_provisional(box)
    touch(rec)
    return ok(ser_addon(rec))
