"""Order lifecycle endpoints (PRD §3.3) — parallel payment × fulfillment dims."""
from flask import Blueprint, request

import errors
from db import db, new_id, add_common_fields, touch
from errors import ApiError
from middleware import authenticate, require_role
from response import success, list_success
from services import serialize
from services.calculations import quote_order
from services.common import (
    get_json_body, require_enum, require_int, optional_bool,
    parse_pagination, paginate,
)
from services.lookup import get_park, get_guest, get_order, require_owner
from routes.pricing import find_active_policy

bp = Blueprint("orders", __name__)

PRODUCT_TYPES = {"DAY_TICKET", "SEASON_PASS"}


@bp.route("/orders", methods=["POST"])
def create_order():
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    body = get_json_body()

    # Ownership (priority 3) precedes existence (priority 4): a guest may create
    # orders only for themselves (PRD §2.9, §3.3). The body's guest_id must equal
    # X-User-ID. Only enforced when guest_id is present and a string.
    body_guest_id = body.get("guest_id")
    if isinstance(body_guest_id, str):
        require_owner(role, user_id, body_guest_id)

    # Existence (priority 4) left-to-right before schema: park_id then guest_id.
    if "park_id" not in body or body["park_id"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: park_id")
    park = get_park(body["park_id"])
    if "guest_id" not in body or body["guest_id"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: guest_id")
    guest = get_guest(body["guest_id"])

    product_type = require_enum(body, "product_type", PRODUCT_TYPES)
    party_size = require_int(body, "party_size", minimum=1)
    food_beverage_combo = optional_bool(body, "food_beverage_combo", False)

    rec = {
        "id": new_id(),
        "park_id": park["id"],
        "guest_id": guest["id"],
        "product_type": product_type,
        "party_size": party_size,
        "food_beverage_combo": food_beverage_combo,
        "resident_rate_applied": False,
        "group_rate_applied": False,
        "subtotal_cents": 0,
        "total_cents": 0,
        "wallet_credit_used_cents": 0,
        "payment_status": "PENDING",
        "fulfillment_status": "UNFULFILLED",
    }
    add_common_fields(rec)
    db.orders[rec["id"]] = rec
    return success(serialize.order(rec), status=201)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order_route(oid):
    _, role = authenticate()
    require_role(role, {"Guest", "FinanceClerk", "ParkManager"})
    rec = get_order(oid)
    return success(serialize.order(rec))


@bp.route("/orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    require_role(role, {"Guest", "FinanceClerk", "ParkManager"})
    limit, offset = parse_pagination()
    rows = list(db.orders.values())
    guest_id = request.args.get("guest_id")
    park_id = request.args.get("park_id")
    payment_status = request.args.get("payment_status")
    if guest_id is not None:
        rows = [o for o in rows if o["guest_id"] == guest_id]
    if park_id is not None:
        rows = [o for o in rows if o["park_id"] == park_id]
    if payment_status is not None:
        rows = [o for o in rows if o["payment_status"] == payment_status]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.order(r) for r in page], limit, offset, total)


@bp.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    order = get_order(oid)
    require_owner(role, user_id, order["guest_id"])

    # State (priority 6) before business rule ERR_NO_ACTIVE_POLICY.
    if order["payment_status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "pay requires payment_status PENDING")
    policy = find_active_policy(order["park_id"], order["product_type"])
    if policy is None:
        raise ApiError(errors.ERR_NO_ACTIVE_POLICY, 409,
                       "No active pricing policy for this park and product type")

    park = db.parks[order["park_id"]]
    guest = db.guests[order["guest_id"]]
    quote = quote_order(order, policy, guest, park)

    order["resident_rate_applied"] = quote["resident_rate_applied"]
    order["group_rate_applied"] = quote["group_rate_applied"]
    order["subtotal_cents"] = quote["subtotal_cents"]
    order["wallet_credit_used_cents"] = quote["wallet_credit_used_cents"]
    order["total_cents"] = quote["total_cents"]

    # Debit guest wallet by the credit consumed.
    guest["wallet_credit_cents"] -= quote["wallet_credit_used_cents"]
    if quote["wallet_credit_used_cents"] != 0:
        touch(guest)

    order["payment_status"] = "PAID"
    touch(order)
    return success(serialize.order(order))


@bp.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    order = get_order(oid)
    require_owner(role, user_id, order["guest_id"])

    if order["payment_status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "cancel requires payment_status PENDING")

    # Release any HELD cabana rental under this order; decrement window reserved_count.
    for cr in db.cabana_rentals.values():
        if cr["order_id"] == order["id"] and cr["status"] == "HELD":
            cr["status"] = "CANCELLED"
            touch(cr)
            _release_window_slot(cr["entry_window_id"])

    order["payment_status"] = "VOID"
    touch(order)
    return success(serialize.order(order))


@bp.route("/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    order = get_order(oid)
    require_owner(role, user_id, order["guest_id"])

    # Business referential: fulfillment only from a PAID order (ERR_ORDER_NOT_PAID).
    if order["payment_status"] != "PAID":
        raise ApiError(errors.ERR_ORDER_NOT_PAID, 409,
                       "fulfill requires payment_status PAID")
    # State: fulfillment_status must still be UNFULFILLED.
    if order["fulfillment_status"] != "UNFULFILLED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "fulfill requires fulfillment_status UNFULFILLED")

    party_size = order["party_size"]
    per_ticket = order["subtotal_cents"] // party_size
    for _ in range(party_size):
        adm = {
            "id": new_id(),
            "order_id": order["id"],
            "park_id": order["park_id"],
            "guest_id": None,
            "entry_window_id": None,
            "product_type": order["product_type"],
            "ticket_price_cents": per_ticket,
            "status": "ISSUED",
            "freeze_days_used": 0,
            "frozen_at": None,
            "band_color": None,
        }
        add_common_fields(adm)
        db.admissions[adm["id"]] = adm

    # Promote every HELD cabana rental under this order to CONFIRMED.
    for cr in db.cabana_rentals.values():
        if cr["order_id"] == order["id"] and cr["status"] == "HELD":
            cr["status"] = "CONFIRMED"
            touch(cr)

    order["fulfillment_status"] = "FULFILLED"
    touch(order)
    return success(serialize.order(order))


@bp.route("/orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    _, role = authenticate()
    require_role(role, {"FinanceClerk"})
    order = get_order(oid)

    # State: refund only while payment_status PAID.
    if order["payment_status"] != "PAID":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "refund requires payment_status PAID")
    # Fiscal: reject if any admission under the order is CHECKED_IN.
    for adm in db.admissions.values():
        if adm["order_id"] == order["id"] and adm["status"] == "CHECKED_IN":
            raise ApiError(errors.ERR_ALREADY_CONSUMED, 409,
                           "refund rejected: an admission is CHECKED_IN")

    guest = db.guests[order["guest_id"]]
    guest["wallet_credit_cents"] += order["total_cents"]
    touch(guest)

    # Cascade: every non-terminal admission -> CANCELLED; if was CONFIRMED, release slot.
    for adm in db.admissions.values():
        if adm["order_id"] == order["id"] and adm["status"] in {"ISSUED", "CONFIRMED", "FROZEN"}:
            was_confirmed = adm["status"] == "CONFIRMED"
            adm["status"] = "CANCELLED"
            touch(adm)
            if was_confirmed:
                _release_window_slot(adm["entry_window_id"])

    # Cascade: every CONFIRMED/HELD cabana rental -> CANCELLED, release slot.
    for cr in db.cabana_rentals.values():
        if cr["order_id"] == order["id"] and cr["status"] in {"CONFIRMED", "HELD"}:
            cr["status"] = "CANCELLED"
            touch(cr)
            _release_window_slot(cr["entry_window_id"])

    order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success(serialize.order(order))


# ---- Nested collections ----
@bp.route("/orders/<oid>/admissions", methods=["GET"])
def list_order_admissions(oid):
    _, role = authenticate()
    require_role(role, {"Guest", "FinanceClerk", "ParkManager", "GateAgent"})
    order = get_order(oid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = [a for a in db.admissions.values() if a["order_id"] == order["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.admission(r) for r in page], limit, offset, total)


@bp.route("/orders/<oid>/cabana-rentals", methods=["GET"])
def list_order_cabana_rentals(oid):
    _, role = authenticate()
    require_role(role, {"Guest", "FinanceClerk", "ParkManager"})
    order = get_order(oid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = [c for c in db.cabana_rentals.values() if c["order_id"] == order["id"]]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.cabana_rental(r) for r in page], limit, offset, total)


@bp.route("/orders/<oid>/locker-rentals", methods=["GET"])
def list_order_locker_rentals(oid):
    _, role = authenticate()
    require_role(role, {"Guest", "FinanceClerk", "ParkManager"})
    order = get_order(oid)
    limit, offset = parse_pagination()
    rows = [l for l in db.locker_rentals.values() if l["order_id"] == order["id"]]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.locker_rental(r) for r in page], limit, offset, total)


def _release_window_slot(window_id):
    if not window_id:
        return
    win = db.entry_windows.get(window_id)
    if win is None:
        return
    if win["reserved_count"] > 0:
        win["reserved_count"] -= 1
        touch(win)
