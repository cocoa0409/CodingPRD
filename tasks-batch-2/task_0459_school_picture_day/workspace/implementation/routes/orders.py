"""PhotoOrder and OrderLine routes (Guardian ordering, clerk payment/reject)."""
from flask import Blueprint, request

import db
import store
from common import (
    get_body,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
    require_str,
    sort_by_creation,
)
from errors import err
from middleware import get_user_context, require_role
from response import array_response, object_response
from services import ledger
from services.pricing import compute_order_total, lines_for_order

bp = Blueprint("orders", __name__)


def _check_guardian_owns_order(role, uid, order):
    """Guardian ownership: target order's student.guardian_user_id == uid."""
    if role != "Guardian":
        return
    student = db.students.get(order["student_id"])
    if student is None or student["guardian_user_id"] != uid:
        raise err("ERR_NOT_OWNER", "Guardian does not own this order")


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@bp.route("/api/photo-orders", methods=["POST"])
def create_order():
    uid, role = get_user_context()
    require_role(role, ["Guardian"])
    body = get_body()
    require_fields(body, ["picture_day_session_id", "student_id"])
    sid = require_str(body, "picture_day_session_id")
    student_id = require_str(body, "student_id")

    with db.LOCK:
        store.get_session(sid)
        student = store.get_student(student_id)
        # Ownership (priority 3) before body/state checks.
        if student["guardian_user_id"] != uid:
            raise err("ERR_NOT_OWNER", "Guardian does not own this student")
        row = store.new_row("order", {
            "picture_day_session_id": sid,
            "student_id": student_id,
            "subtotal_cents": 0,
            "discount_pct": 0,
            "discount_cents": 0,
            "merchandise_cents": 0,
            "shipping_cents": 0,
            "total_cents": 0,
            "has_premium_line": False,
            "status": "CART",
        })
        db.photo_orders[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/photo-orders", methods=["GET"])
def list_orders():
    uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator", "FulfillmentClerk", "Guardian"])
    limit, offset = parse_pagination()
    sid = request.args.get("picture_day_session_id")
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    rows = list(db.photo_orders.values())
    if sid is not None:
        rows = [r for r in rows if r["picture_day_session_id"] == sid]
    if student_id is not None:
        rows = [r for r in rows if r["student_id"] == student_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # Guardian sees only their own orders.
    if role == "Guardian":
        owned = {
            s["id"] for s in db.students.values() if s["guardian_user_id"] == uid
        }
        rows = [r for r in rows if r["student_id"] in owned]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/photo-orders/<rid>", methods=["GET"])
def get_order(rid):
    uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator", "FulfillmentClerk", "Guardian"])
    order = store.get_order(rid)
    _check_guardian_owns_order(role, uid, order)
    return object_response(store.serialize(order))


@bp.route("/api/photo-orders/<rid>/submit", methods=["POST"])
def submit_order(rid):
    uid, role = get_user_context()
    require_role(role, ["Guardian"])
    with db.LOCK:
        order = store.get_order(rid)
        _check_guardian_owns_order(role, uid, order)
        session = store.get_session(order["picture_day_session_id"])
        if session["status"] != "GALLERY_OPEN":
            raise err("ERR_SESSION_NOT_ORDERING", "Session is not accepting orders")
        if order["status"] != "CART":
            raise err("ERR_ORDER_NOT_CART", "Order is not in CART")
        if not lines_for_order(rid):
            raise err("ERR_EMPTY_ORDER", "Order has no lines")
        compute_order_total(order)
        order["status"] = "SUBMITTED"
        store.touch(order)
    return object_response(store.serialize(order))


@bp.route("/api/photo-orders/<rid>/pay", methods=["POST"])
def pay_order(rid):
    _uid, role = get_user_context()
    require_role(role, ["FulfillmentClerk"])
    with db.LOCK:
        order = store.get_order(rid)
        if order["status"] != "SUBMITTED":
            raise err("ERR_ORDER_NOT_SUBMITTED", "Order is not SUBMITTED")
        order["status"] = "PAID"
        store.touch(order)
        session = store.get_session(order["picture_day_session_id"])
        ledger.accrue_provisional_commission(session, order)
    return object_response(store.serialize(order))


@bp.route("/api/photo-orders/<rid>/reject", methods=["POST"])
def reject_order(rid):
    _uid, role = get_user_context()
    require_role(role, ["FulfillmentClerk"])
    with db.LOCK:
        order = store.get_order(rid)
        if order["status"] != "SUBMITTED":
            raise err("ERR_ORDER_NOT_SUBMITTED", "Order is not SUBMITTED")
        order["status"] = "REJECTED"
        store.touch(order)
    return object_response(store.serialize(order))


@bp.route("/api/photo-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    uid, role = get_user_context()
    require_role(role, ["Guardian"])
    with db.LOCK:
        order = store.get_order(rid)
        _check_guardian_owns_order(role, uid, order)
        if order["status"] not in ("CART", "SUBMITTED"):
            raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is not cancellable")
        order["status"] = "CANCELLED"
        store.touch(order)
    return object_response(store.serialize(order))


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------
@bp.route("/api/order-lines", methods=["POST"])
def create_line():
    uid, role = get_user_context()
    require_role(role, ["Guardian"])
    body = get_body()
    require_fields(body, ["photo_order_id", "package_item_id", "quantity"])
    order_id = require_str(body, "photo_order_id")
    package_id = require_str(body, "package_item_id")
    quantity = require_int(body, "quantity")
    if quantity < 1:
        raise err("ERR_INVALID_REQUEST", "quantity must be >= 1")

    with db.LOCK:
        order = store.get_order(order_id)
        package = store.get_package(package_id)
        # Ownership before state.
        _check_guardian_owns_order(role, uid, order)
        if order["status"] != "CART":
            raise err("ERR_ORDER_NOT_CART", "Order is not in CART")

        unit_price = package["base_price_cents"]
        row = store.new_row("line", {
            "photo_order_id": order_id,
            "package_item_id": package_id,
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "line_total_cents": unit_price * quantity,
        })
        db.order_lines[row["id"]] = row
        # Recompute has_premium_line on the order.
        has_premium = any(
            db.packages.get(l["package_item_id"], {}).get("tier") == "PREMIUM"
            for l in lines_for_order(order_id)
        )
        if order["has_premium_line"] != has_premium:
            order["has_premium_line"] = has_premium
        store.touch(order)
    return object_response(store.serialize(row), 201)


@bp.route("/api/order-lines", methods=["GET"])
def list_lines():
    uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator", "FulfillmentClerk", "Guardian"])
    limit, offset = parse_pagination()
    order_id = request.args.get("photo_order_id")
    package_id = request.args.get("package_item_id")
    rows = list(db.order_lines.values())
    if order_id is not None:
        rows = [r for r in rows if r["photo_order_id"] == order_id]
    if package_id is not None:
        rows = [r for r in rows if r["package_item_id"] == package_id]
    if role == "Guardian":
        owned_students = {
            s["id"] for s in db.students.values() if s["guardian_user_id"] == uid
        }
        owned_orders = {
            o["id"] for o in db.photo_orders.values() if o["student_id"] in owned_students
        }
        rows = [r for r in rows if r["photo_order_id"] in owned_orders]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/order-lines/<rid>", methods=["GET"])
def get_line(rid):
    uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator", "FulfillmentClerk", "Guardian"])
    line = store.get_line(rid)
    if role == "Guardian":
        order = db.photo_orders.get(line["photo_order_id"])
        if order is not None:
            _check_guardian_owns_order(role, uid, order)
    return object_response(store.serialize(line))
