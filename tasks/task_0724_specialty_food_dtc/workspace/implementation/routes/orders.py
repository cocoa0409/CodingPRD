from flask import Blueprint, request

from db import db, new_common, public, touch
from clock import clock, parse_iso
from middleware import auth, require_role
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
    ERR_INVALID_STATE,
    ERR_ALLERGEN_CONFLICT,
    ERR_LOT_EXPIRED,
    ERR_INSUFFICIENT_POINTS,
    ERR_INSUFFICIENT_INVENTORY,
    ERR_LOT_UNDERSTOCK,
)
from helpers import (
    body,
    require_str,
    require_int,
    require_enum,
    find_customer,
    find_sku,
    find_order,
    find_order_line,
    paginate,
    sorted_by_created,
    ZONES,
    ORDER_KINDS,
)
from response import ok_object, ok_list
from services import calc, domain

bp = Blueprint("orders", __name__)


def serialize_order(o):
    return public(o)


def serialize_line(l):
    return public(l)


def _own_check(role, user_id, order):
    if role == "Customer" and user_id != order["customer_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")


def _lines_of(order_id):
    return sorted_by_created([l for l in db.order_lines.values() if l["order_id"] == order_id])


def _new_order_record(customer_id, order_kind, ship_zone, subscription_id=None,
                      gift_recipient_email=None, gift_box_count=0, requested_redeem_points=0):
    oid = db.new_id()
    order = {
        "id": oid,
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "order_kind": order_kind,
        "ship_zone": ship_zone,
        "gift_recipient_email": gift_recipient_email,
        "gift_box_count": gift_box_count,
        "requested_redeem_points": requested_redeem_points,
        "payment_status": "UNPAID",
        "fulfillment_status": "DRAFT",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "handling_cents": 0,
        "shipping_cents": 0,
        "redeemed_points": 0,
        "total_cents": 0,
        "accrued_points": 0,
    }
    order.update(new_common())
    db.orders[oid] = order
    return order


@bp.post("/orders")
def create_order():
    user_id, role = auth()
    require_role(role, {"Customer", "PlatformAdmin", "CorporateBuyer"})
    data = body()
    customer_id = require_str(data, "customer_id")
    order_kind = require_str(data, "order_kind")
    ship_zone = require_str(data, "ship_zone")
    subscription_id = data.get("subscription_id")
    gift_box_count = data.get("gift_box_count", 0)
    if gift_box_count is None:
        gift_box_count = 0
    requested_redeem = data.get("requested_redeem_points", 0)
    if requested_redeem is None:
        requested_redeem = 0
    if isinstance(gift_box_count, bool) or not isinstance(gift_box_count, int) or gift_box_count < 0:
        raise err(ERR_INVALID_REQUEST, "Invalid gift_box_count")
    if isinstance(requested_redeem, bool) or not isinstance(requested_redeem, int) or requested_redeem < 0:
        raise err(ERR_INVALID_REQUEST, "Invalid requested_redeem_points")

    # ownership (entity-backed)
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    if role == "CorporateBuyer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    # existence
    find_customer(customer_id)
    if subscription_id is not None:
        from helpers import find_subscription
        find_subscription(subscription_id)
    # gift email required when GIFT (request shape, priority 5)
    gift_recipient_email = data.get("gift_recipient_email")
    if order_kind == "GIFT":
        if not gift_recipient_email or not isinstance(gift_recipient_email, str):
            raise err(ERR_INVALID_REQUEST, "gift_recipient_email required for GIFT")
    # enum (priority 6)
    require_enum(order_kind, ORDER_KINDS, "order_kind")
    require_enum(ship_zone, ZONES, "ship_zone")

    order = _new_order_record(
        customer_id, order_kind, ship_zone,
        subscription_id=subscription_id,
        gift_recipient_email=gift_recipient_email,
        gift_box_count=gift_box_count,
        requested_redeem_points=requested_redeem,
    )
    return ok_object(serialize_order(order), 201)


@bp.post("/orders/<oid>/lines")
def add_line(oid):
    user_id, role = auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    data = body()
    order = find_order(oid)
    _own_check(role, user_id, order)
    sku_id = require_str(data, "sku_id")
    quantity = require_int(data, "quantity", minimum=1)
    find_sku(sku_id)
    if order["fulfillment_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Lines can only be added to a DRAFT order")

    lid = db.new_id()
    line = {
        "id": lid,
        "order_id": oid,
        "sku_id": sku_id,
        "lot_id": None,
        "quantity": quantity,
        "unit_price_cents": 0,
        "line_status": "PENDING",
    }
    line.update(new_common())
    db.order_lines[lid] = line
    return ok_object(serialize_line(line), 201)


@bp.get("/orders")
def list_orders():
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    items = list(db.orders.values())
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == user_id]
    for key in ("customer_id", "subscription_id"):
        v = request.args.get(key)
        if v is not None:
            items = [o for o in items if o.get(key) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_order(o) for o in page], limit, offset, total)


@bp.get("/orders/<oid>")
def get_order(oid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    order = find_order(oid)
    _own_check(role, user_id, order)
    return ok_object(serialize_order(order))


@bp.get("/orders/<oid>/lines")
def list_order_lines(oid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    order = find_order(oid)
    _own_check(role, user_id, order)
    items = _lines_of(oid)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_line(l) for l in page], limit, offset, total)


@bp.get("/order-lines/<lid>")
def get_order_line(lid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    line = find_order_line(lid)
    if role == "Customer":
        order = db.orders[line["order_id"]]
        if order["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    return ok_object(serialize_line(line))


@bp.get("/order-lines")
def list_all_order_lines():
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    items = list(db.order_lines.values())
    if role == "Customer":
        owned = {o["id"] for o in db.orders.values() if o["customer_id"] == user_id}
        items = [l for l in items if l["order_id"] in owned]
    for key in ("order_id", "sku_id", "lot_id"):
        v = request.args.get(key)
        if v is not None:
            items = [l for l in items if l.get(key) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_line(l) for l in page], limit, offset, total)


@bp.post("/orders/<oid>/reserve")
def reserve_order(oid):
    user_id, role = auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    order = find_order(oid)
    _own_check(role, user_id, order)
    if order["fulfillment_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Reserve requires DRAFT")
    lines = _lines_of(oid)
    if not lines:
        raise err(ERR_INVALID_STATE, "Order has no lines")

    cust = db.customers[order["customer_id"]]

    # business: every line's SKU ACTIVE (state) -> handled as inventory/state
    for line in lines:
        sku = db.skus[line["sku_id"]]
        if sku["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Line SKU not ACTIVE")

    # allergen conflict for GIFT (priority 10)
    if order["order_kind"] == "GIFT":
        recipient = order.get("gift_recipient_email")
        # recipient allergen conflict: if a registered customer with that email has
        # declared accepted allergens, a conflict exists when an ordered SKU carries
        # an allergen the recipient does not accept. We model "recorded allergen
        # conflict" via a recipient customer's home account allergen flags if present.
        rec_cust = None
        for c in db.customers.values():
            if c["email"] == recipient:
                rec_cust = c
                break
        if rec_cust is not None:
            blocked = set(rec_cust.get("_blocked_allergens", []))
            if blocked:
                for line in lines:
                    sku = db.skus[line["sku_id"]]
                    if set(sku["allergens"]) & blocked:
                        raise err(ERR_ALLERGEN_CONFLICT, "Allergen conflict for gift recipient")

    # insufficient points (priority 15) before inventory (priority 16)
    if order["requested_redeem_points"] > cust["loyalty_points_balance"]:
        raise err(ERR_INSUFFICIENT_POINTS, "Requested redeem points exceed balance")

    # inventory capacity per line (priority 16): aggregate per-SKU demand
    demand = {}
    for line in lines:
        demand[line["sku_id"]] = demand.get(line["sku_id"], 0) + line["quantity"]
    for sku_id, qty in demand.items():
        sku = db.skus[sku_id]
        if sku["available_units"] < qty:
            raise err(ERR_INSUFFICIENT_INVENTORY, "Insufficient inventory")
    # FEFO selectability per line
    for sku_id in demand:
        if domain.fefo_select(sku_id) is None:
            raise err(ERR_INSUFFICIENT_INVENTORY, "No consumable lot")

    # commit reservation
    lines_with_sku = []
    for line in lines:
        sku = db.skus[line["sku_id"]]
        lot = domain.fefo_select(line["sku_id"])
        line["lot_id"] = lot["id"]
        line["unit_price_cents"] = sku["unit_price_cents"]
        line["line_status"] = "PENDING"
        touch(line)
        sku["reserved_units"] += line["quantity"]
        domain.recompute_sku_availability(sku)
        lines_with_sku.append({
            "unit_price_cents": sku["unit_price_cents"],
            "quantity": line["quantity"],
            "storage_class": sku["storage_class"],
        })

    totals = calc.order_total(
        lines_with_sku, order["ship_zone"],
        order["requested_redeem_points"], cust["loyalty_points_balance"],
    )
    order.update(totals)
    order["accrued_points"] = calc.loyalty_points_accrual(lines_with_sku)
    order["fulfillment_status"] = "RESERVED"
    touch(order)
    return ok_object(serialize_order(order))


@bp.post("/orders/<oid>/pay")
def pay_order(oid):
    user_id, role = auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    data = body()
    order = find_order(oid)
    _own_check(role, user_id, order)
    outcome = require_str(data, "outcome")
    if outcome not in ("SUCCEEDED", "DECLINED"):
        raise err(ERR_INVALID_ENUM, "Invalid outcome")
    if order["payment_status"] not in ("UNPAID", "FAILED"):
        raise err(ERR_INVALID_STATE, "Payment not allowed from current state")
    if outcome == "SUCCEEDED":
        if order["fulfillment_status"] == "CANCELLED":
            raise err(ERR_INVALID_STATE, "Cannot pay a cancelled order")
        order["payment_status"] = "PAID"
        touch(order)
    else:
        order["payment_status"] = "FAILED"
        touch(order)
        cust = db.customers[order["customer_id"]]
        cust["lifetime_failed_payment_count"] += 1
        domain.record_event(cust, "fail")
        touch(cust)
        domain.recompute_customer_churn(cust)
    return ok_object(serialize_order(order))


@bp.post("/orders/<oid>/ship")
def ship_order(oid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    order = find_order(oid)
    if order["fulfillment_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Ship requires RESERVED")
    if order["payment_status"] != "PAID":
        raise err(ERR_INVALID_STATE, "Order not paid")
    lines = _lines_of(oid)
    # precondition checks across ALL lines before any mutation (atomicity).
    # PRD §3.5: ERR_LOT_EXPIRED fires only when the lot is *expired* (clock at/past
    # expiry_iso, §3.2); a lot that is merely no longer RELEASED (e.g. recalled, which
    # §3.2 guarantees zeroes remaining_units) but not past expiry falls to the
    # remaining_units check and is rejected with ERR_LOT_UNDERSTOCK.
    for line in lines:
        lot = db.lots.get(line["lot_id"])
        if lot is None:
            raise err(ERR_INVALID_STATE, "Line has no lot")
        if domain.lot_is_expired(lot):
            raise err(ERR_LOT_EXPIRED, "Lot expired")
    for line in lines:
        lot = db.lots[line["lot_id"]]
        if lot["remaining_units"] < line["quantity"]:
            raise err(ERR_LOT_UNDERSTOCK, "Lot understock")

    cust = db.customers[order["customer_id"]]
    affected_skus = set()
    # hop 1 + hop 2
    for line in lines:
        lot = db.lots[line["lot_id"]]
        sku = db.skus[line["sku_id"]]
        line["line_status"] = "COMMITTED"
        touch(line)
        lot["remaining_units"] -= line["quantity"]
        touch(lot)
        sku["reserved_units"] -= line["quantity"]
        if sku["reserved_units"] < 0:
            sku["reserved_units"] = 0
        affected_skus.add(sku["id"])
    for sku_id in affected_skus:
        sku = db.skus[sku_id]
        avail = domain.recompute_sku_availability(sku)
        # hop 3
        if avail == 0:
            domain.auto_pause_subscriptions_for_sku(sku_id)

    # credit loyalty, advance counters
    was_first = cust["lifetime_order_count"] == 0
    cust["loyalty_points_balance"] += order["accrued_points"]
    cust["lifetime_order_count"] += 1
    cust["last_order_at"] = order["created_at"]
    if cust["status"] == "DORMANT":
        cust["status"] = "WON_BACK"
    touch(cust)
    domain.recompute_customer_churn(cust)

    # referral qualification: referred customer's first order ships (0 -> 1)
    if was_first:
        for ref in db.referrals.values():
            if ref["referred_id"] == cust["id"] and ref["status"] == "PENDING":
                ref["status"] = "QUALIFIED"
                touch(ref)

    order["fulfillment_status"] = "SHIPPED"
    touch(order)
    return ok_object(serialize_order(order))


@bp.post("/orders/<oid>/deliver")
def deliver_order(oid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    order = find_order(oid)
    if order["fulfillment_status"] != "SHIPPED":
        raise err(ERR_INVALID_STATE, "Deliver requires SHIPPED")
    order["fulfillment_status"] = "DELIVERED"
    touch(order)
    return ok_object(serialize_order(order))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    order = find_order(oid)
    _own_check(role, user_id, order)
    if order["fulfillment_status"] not in ("DRAFT", "RESERVED"):
        raise err(ERR_INVALID_STATE, "Cancel requires DRAFT or RESERVED")

    if order["fulfillment_status"] == "RESERVED":
        for line in _lines_of(oid):
            sku = db.skus[line["sku_id"]]
            line["line_status"] = "RELEASED"
            touch(line)
            sku["reserved_units"] -= line["quantity"]
            if sku["reserved_units"] < 0:
                sku["reserved_units"] = 0
            domain.recompute_sku_availability(sku)

    order["fulfillment_status"] = "CANCELLED"
    # compensation if paid
    if order["payment_status"] == "PAID":
        cust = db.customers[order["customer_id"]]
        cust["wallet_credit_cents"] += order["total_cents"]
        touch(cust)
        order["payment_status"] = "REFUNDED"
    touch(order)
    return ok_object(serialize_order(order))


def build_renewal_order(cust, sub, final_charge_cents):
    """Create a SUBSCRIPTION order (1 line qty 1) for a renewal, charged FINAL."""
    order = _new_order_record(
        cust["id"], "SUBSCRIPTION", cust["home_zone"],
        subscription_id=sub["id"],
    )
    sku = db.skus[sub["sku_id"]]
    lid = db.new_id()
    line = {
        "id": lid,
        "order_id": order["id"],
        "sku_id": sub["sku_id"],
        "lot_id": None,
        "quantity": 1,
        "unit_price_cents": sku["unit_price_cents"],
        "line_status": "PENDING",
    }
    line.update(new_common())
    db.order_lines[lid] = line
    order["subtotal_cents"] = sku["unit_price_cents"]
    order["total_cents"] = final_charge_cents
    touch(order)
    return order
