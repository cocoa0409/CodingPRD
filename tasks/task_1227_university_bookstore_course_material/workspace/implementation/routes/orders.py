"""Orders: placement with shelf pricing, aid tender waterfall, stock
decrement; line returns with refund variants, restock, and CASCADE-2
(PRD §3.6, §3.7)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_entity, touch, pub
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_OWNER,
    ERR_NOT_FOUND, ERR_FORMAT_NOT_OFFERED, ERR_INSUFFICIENT_STOCK,
    ERR_NO_ACTIVE_AGREEMENT, ERR_ADOPTION_NOT_APPROVED,
    ERR_AID_WINDOW_CLOSED, ERR_INSUFFICIENT_AID, ERR_RETURN_WINDOW_CLOSED,
    ERR_DIGITAL_NOT_RETURNABLE,
)
from middleware import (
    require_roles, body, get_str, get_bool, get_or_404,
)
from response import success, list_response
from services import (
    active_agreement, shelf_base_price, round_half_up_cents,
    STOCK_FIELD, OFFERED_FIELD, FORMATS,
)

bp = Blueprint("orders", __name__)

RESTOCKING_KEEP_PCT = Decimal("0.20")
DIGITAL_RETURN_HOURS = 48


@bp.post("/bookstore/orders")
def create_order():
    uid, _ = require_roles("Student")
    student = store.students.get(uid)
    if student is None:
        raise ApiError(ERR_NOT_FOUND, 404, "student not found")
    data = body()
    term_id = get_str(data, "term_id")
    aid_only = get_bool(data, "aid_only", required=False, default=False)
    lines_raw = data.get("lines")
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise ApiError(ERR_VALIDATION, 400, "lines must be a non-empty array")
    # existence, left to right (priority 4)
    term = get_or_404(store.terms, term_id, "term")
    parsed = []
    for lr in lines_raw:
        if not isinstance(lr, dict):
            raise ApiError(ERR_VALIDATION, 400, "each line must be an object")
        adoption_id = get_str(lr, "adoption_id")
        fmt = get_str(lr, "format")
        qty = lr.get("qty")
        if qty is None:
            raise ApiError(ERR_VALIDATION, 400, "Missing required field: qty")
        adoption = get_or_404(store.adoptions, adoption_id, "adoption")
        parsed.append([adoption, fmt, qty])
    # business temporal (priority 7): aid window for aid-only orders
    n = now()
    aid_window_open = (term["aid_charge_window_start_at"] <= n
                       <= term["aid_charge_window_end_at"])
    if aid_only and not aid_window_open:
        raise ApiError(ERR_AID_WINDOW_CLOSED, 422,
                       "aid-only order outside the aid charge window")
    # business constraint (priority 8): shape, format offered, stock
    needed = {}
    for adoption, fmt, qty in parsed:
        if fmt not in FORMATS:
            raise ApiError(ERR_VALIDATION, 400, "invalid format")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ApiError(ERR_VALIDATION, 400, "qty must be an integer >= 1")
        if fmt in ("RENTAL", "DIGITAL") and qty != 1:
            raise ApiError(ERR_VALIDATION, 400,
                           "qty must be exactly 1 for RENTAL and DIGITAL")
        title = store.titles[adoption["title_id"]]
        if not title[OFFERED_FIELD[fmt]]:
            raise ApiError(ERR_FORMAT_NOT_OFFERED, 422,
                           "format not offered by the title")
        key = (title["id"], fmt)
        needed[key] = needed.get(key, 0) + qty
    for (tid, fmt), q in needed.items():
        if fmt == "DIGITAL":
            continue
        title = store.titles[tid]
        if title[STOCK_FIELD[fmt]] < q:
            raise ApiError(ERR_INSUFFICIENT_STOCK, 409,
                           "insufficient stock for requested format")
    # business referential (priority 9): active agreement, adoption approved
    agreements = {}
    for adoption, fmt, qty in parsed:
        title = store.titles[adoption["title_id"]]
        ag = active_agreement(title["publisher_id"])
        if ag is None:
            raise ApiError(ERR_NO_ACTIVE_AGREEMENT, 422,
                           "no active agreement covers the publisher")
        if adoption["status"] != "APPROVED":
            raise ApiError(ERR_ADOPTION_NOT_APPROVED, 422,
                           "referenced adoption not APPROVED")
        agreements[title["id"]] = ag
    # pricing: calculations.shelf_price_resolution (round per line, then
    # HEOA min() cap against the adoption's posted price)
    priced = []
    for adoption, fmt, qty in parsed:
        title = store.titles[adoption["title_id"]]
        base = shelf_base_price(fmt, title, term, agreements[title["id"]])
        unit_price = min(base, adoption["posted_price_cents"])
        priced.append([adoption, title, fmt, qty, unit_price,
                       unit_price * qty])
    total_cents = sum(p[5] for p in priced)
    # tender waterfall (calculations.aid_tender_waterfall), request order
    remaining_aid = student["aid_balance_cents"] if aid_window_open else 0
    for p in priced:
        line_total = p[5]
        aid_applied = min(line_total, remaining_aid)
        p.append(aid_applied)               # p[6] aid_tendered_cents
        p.append(line_total - aid_applied)  # p[7] card_tendered_cents
        remaining_aid -= aid_applied
    order_aid = sum(p[6] for p in priced)
    order_card = sum(p[7] for p in priced)
    # business fiscal (priority 10): aid-only must be fully aid-tendered
    if aid_only and order_aid < total_cents:
        raise ApiError(ERR_INSUFFICIENT_AID, 402,
                       "aid does not cover the order total")
    # commit: order born SETTLED, lines born FULFILLED
    order = new_entity()
    order.update({
        "student_id": uid,
        "term_id": term["id"],
        "aid_only": aid_only,
        "total_cents": total_cents,
        "aid_tendered_cents": order_aid,
        "card_tendered_cents": order_card,
        "refund_total_cents": 0,
        "status": "SETTLED",
    })
    store.orders[order["id"]] = order
    for adoption, title, fmt, qty, unit_price, line_total, aid_applied, card in priced:
        line = new_entity()
        line.update({
            "order_id": order["id"],
            "adoption_id": adoption["id"],
            "title_id": title["id"],
            "format": fmt,
            "qty": qty,
            "unit_price_cents": unit_price,
            "line_total_cents": line_total,
            "aid_tendered_cents": aid_applied,
            "card_tendered_cents": card,
            "aid_refunded_cents": 0,
            "card_refunded_cents": 0,
            "status": "FULFILLED",
        })
        store.order_lines[line["id"]] = line
    # placement decrements stock (DIGITAL touches no counter)
    for (tid, fmt), q in needed.items():
        if fmt == "DIGITAL":
            continue
        title = store.titles[tid]
        title[STOCK_FIELD[fmt]] -= q
        touch(title)
    if order_aid > 0:
        student["aid_balance_cents"] -= order_aid
        touch(student)
    return success(pub(order), status=201)


@bp.get("/bookstore/orders")
def list_orders():
    require_roles("BookstoreManager", "Student")
    student_id = request.args.get("student_id")
    term_id = request.args.get("term_id")
    status = request.args.get("status")
    items = [
        o for o in store.orders.values()
        if (student_id is None or o["student_id"] == student_id)
        and (term_id is None or o["term_id"] == term_id)
        and (status is None or o["status"] == status)
    ]
    return list_response(items)


@bp.get("/bookstore/orders/<oid>")
def get_order(oid):
    uid, role = require_roles("BookstoreManager", "Student")
    order = get_or_404(store.orders, oid, "order")
    # PRD §2.1/§2.8 priority 3: a Student actor must own the order.
    if role == "Student" and order["student_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the order owner")
    return success(pub(order))


@bp.get("/bookstore/orders/<oid>/lines")
def list_order_lines(oid):
    uid, role = require_roles("BookstoreManager", "Student")
    order = get_or_404(store.orders, oid, "order")
    if role == "Student" and order["student_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the order owner")
    items = [l for l in store.order_lines.values()
             if l["order_id"] == order["id"]]
    return list_response(items)


@bp.get("/bookstore/order-lines")
def list_all_order_lines():
    require_roles("BookstoreManager")
    order_id = request.args.get("order_id")
    adoption_id = request.args.get("adoption_id")
    title_id = request.args.get("title_id")
    items = [
        l for l in store.order_lines.values()
        if (order_id is None or l["order_id"] == order_id)
        and (adoption_id is None or l["adoption_id"] == adoption_id)
        and (title_id is None or l["title_id"] == title_id)
    ]
    return list_response(items)


@bp.get("/bookstore/order-lines/<lid>")
def get_order_line(lid):
    require_roles("BookstoreManager")
    return success(pub(get_or_404(store.order_lines, lid, "order line")))


@bp.post("/bookstore/orders/<oid>/lines/<lid>/return")
def return_order_line(oid, lid):
    uid, role = require_roles("Student", "BookstoreManager")
    # nested resolution, left to right: order first, line second
    order = get_or_404(store.orders, oid, "order")
    line = store.order_lines.get(lid)
    if line is None or line["order_id"] != order["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, "order line not found")
    if role == "Student" and order["student_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the order owner")
    if line["status"] != "FULFILLED":
        raise ApiError(ERR_INVALID_STATE, 409, "line not in FULFILLED")
    if order["status"] not in ("SETTLED", "PARTIALLY_REFUNDED"):
        raise ApiError(ERR_INVALID_STATE, 409, "order not returnable")
    data = body()
    override = data.get("override", False)
    if not isinstance(override, bool):
        raise ApiError(ERR_VALIDATION, 400, "override must be a boolean")
    term = store.terms[order["term_id"]]
    n = now()
    # calculations.order_line_refund
    if line["format"] == "DIGITAL":
        if n > order["created_at"] + timedelta(hours=DIGITAL_RETURN_HOURS):
            raise ApiError(ERR_DIGITAL_NOT_RETURNABLE, 422,
                           "digital return beyond 48 hours after placement")
        refund = line["line_total_cents"]
    else:
        if n <= term["add_drop_return_deadline_at"]:
            refund = line["line_total_cents"]
        elif role == "BookstoreManager" and override is True:
            # manager_override_post_deadline: 80% refunded, 20% restocking kept
            refund = round_half_up_cents(
                (Decimal(1) - RESTOCKING_KEEP_PCT) * line["line_total_cents"])
        else:
            raise ApiError(ERR_RETURN_WINDOW_CLOSED, 422,
                           "return past the add/drop deadline")
    aid_refunded = min(line["aid_tendered_cents"], refund)
    card_refunded = refund - aid_refunded
    line["aid_refunded_cents"] = aid_refunded
    line["card_refunded_cents"] = card_refunded
    line["status"] = "RETURNED"
    touch(line)
    # restock mirrors placement; DIGITAL restocks nothing
    if line["format"] != "DIGITAL":
        title = store.titles[line["title_id"]]
        title[STOCK_FIELD[line["format"]]] += line["qty"]
        touch(title)
    # aid credit back to the student
    if aid_refunded > 0:
        student = store.students[order["student_id"]]
        student["aid_balance_cents"] += aid_refunded
        touch(student)
    # CASCADE-2 hop 2: recompute order refund total and re-derive status
    order_lines = [l for l in store.order_lines.values()
                   if l["order_id"] == order["id"]]
    order["refund_total_cents"] = sum(
        l["aid_refunded_cents"] + l["card_refunded_cents"] for l in order_lines)
    order["status"] = ("REFUNDED"
                       if all(l["status"] == "RETURNED" for l in order_lines)
                       else "PARTIALLY_REFUNDED")
    touch(order)
    return success(pub(line))
