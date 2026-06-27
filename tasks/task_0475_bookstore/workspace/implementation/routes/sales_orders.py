"""Sales orders: two independent axes (payment × fulfillment), OCC reserve,
pricing, loyalty points, cascades."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, refresh_updated_at, get_str,
                    get_int, parse_pagination, paginate)
from db import db
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_INSUFFICIENT_STOCK, ERR_INSUFFICIENT_CREDIT,
                    ERR_EMPTY_TRANSACTION, ERR_INVALID_REQUEST)
from middleware import authorize, check_owner
from response import success_object, success_list
from serialize import sales_order_out, order_line_out
from services import (recompute_title_counts, recompute_order_line_reserved,
                      recompute_order_subtotal, recompute_member_balances,
                      append_ledger, available_stock_for_title,
                      reserved_stock_for_line, sell_consignment_copy)
from calculations import order_pricing, loyalty_points

bp = Blueprint("sales_orders", __name__)

ORDER_ROLES = {"Member", "Bookseller", "StoreAdmin"}
MEMBER_ADMIN = {"Member", "StoreAdmin"}
STAFF_ROLES = {"Bookseller", "StoreAdmin"}


def _find_order(oid):
    o = db.sales_orders.get(oid)
    if o is None:
        raise err(ERR_NOT_FOUND, "Sales order not found")
    return o


def _find_member(mid):
    m = db.members.get(mid)
    if m is None:
        raise err(ERR_NOT_FOUND, "Member not found")
    return m


def _lines_for(oid):
    lines = [l for l in db.order_lines.values() if l["order_id"] == oid]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


@bp.route("/sales-orders", methods=["POST"])
def create_order():
    user_id, role = authorize(ORDER_ROLES)
    body = json_body(optional=False)
    member_id = get_str(body, "member_id", required=True)
    credit_redeemed = get_int(body, "credit_redeemed_cents", required=False,
                              default=0, minimum=0)
    # Member may only create for themselves (ownership on the body FK).
    check_owner(user_id, role, member_id)
    _find_member(member_id)

    rec = make_record({
        "member_id": member_id,
        "payment_status": "UNPAID",
        "fulfillment_status": "OPEN",
        "credit_redeemed_cents": credit_redeemed,
        "subtotal_cents": 0,
        "member_discount_cents": 0,
        "net_paid_cents": 0,
        "points_provisional": 0,
        "points_final": 0,
    })
    db.sales_orders[rec["id"]] = rec
    return success_object(sales_order_out(rec), status=201)


@bp.route("/sales-orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = authorize(ORDER_ROLES)
    o = _find_order(oid)
    check_owner(user_id, role, o["member_id"])
    return success_object(sales_order_out(o), status=200)


@bp.route("/sales-orders", methods=["GET"])
def list_orders():
    user_id, role = authorize(ORDER_ROLES)
    member_id = request.args.get("member_id")
    payment_status = request.args.get("payment_status")
    fulfillment_status = request.args.get("fulfillment_status")
    items = list(db.sales_orders.values())
    # A Member sees only their own orders.
    if role == "Member":
        items = [o for o in items if o["member_id"] == user_id]
    if member_id is not None:
        items = [o for o in items if o["member_id"] == member_id]
    if payment_status is not None:
        items = [o for o in items if o["payment_status"] == payment_status]
    if fulfillment_status is not None:
        items = [o for o in items if o["fulfillment_status"] == fulfillment_status]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([sales_order_out(o) for o in page], limit, offset, total)


@bp.route("/sales-orders/<oid>/lines", methods=["POST"])
def add_line(oid):
    user_id, role = authorize(ORDER_ROLES)
    o = _find_order(oid)
    check_owner(user_id, role, o["member_id"])
    body = json_body(optional=False)
    title_id = get_str(body, "title_id", required=True)
    quantity = get_int(body, "quantity", required=True, minimum=1)
    # state guard: order must be OPEN + UNPAID to add lines
    if not (o["fulfillment_status"] == "OPEN" and o["payment_status"] == "UNPAID"):
        raise err(ERR_INVALID_STATE, "Order is not open/unpaid")
    title = db.titles.get(title_id)
    if title is None:
        raise err(ERR_NOT_FOUND, "Title not found")

    unit_price = title["list_price_cents"]
    line = make_record({
        "order_id": oid,
        "title_id": title_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": unit_price * quantity,
        "reserved_qty": 0,
    })
    db.order_lines[line["id"]] = line
    recompute_order_subtotal(o)
    # Refresh subtotal/updated_at but do NOT bump the order's version: the OCC
    # reserve token is the order version as of creation, and adding lines must
    # not invalidate it (see test_05/test_11 reserve flows).
    refresh_updated_at(o)
    return success_object(order_line_out(line), status=201)


@bp.route("/sales-orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    user_id, role = authorize(ORDER_ROLES)
    o = _find_order(oid)
    check_owner(user_id, role, o["member_id"])
    lines = _lines_for(oid)
    limit, offset = parse_pagination(request.args)
    page, total = paginate(lines, limit, offset)
    return success_list([order_line_out(l) for l in page], limit, offset, total)


@bp.route("/sales-orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    user_id, role = authorize(MEMBER_ADMIN)
    o = _find_order(oid)
    check_owner(user_id, role, o["member_id"])
    json_body(optional=True)  # no body fields
    # state: must be UNPAID
    if o["payment_status"] != "UNPAID":
        raise err(ERR_INVALID_STATE, "Order is not UNPAID")
    member = db.members[o["member_id"]]
    lines = _lines_for(oid)
    # must have at least one line
    if len(lines) == 0:
        raise err(ERR_EMPTY_TRANSACTION, "Order has no lines")
    # credit balance check
    recompute_member_balances(member)
    credit_redeemed = o["credit_redeemed_cents"]
    if credit_redeemed > member["store_credit_cents"]:
        raise err(ERR_INSUFFICIENT_CREDIT, "Insufficient store credit")

    # pricing (calc order_pricing)
    recompute_order_subtotal(o)
    discount, net_paid = order_pricing(o["subtotal_cents"], member["tier"], credit_redeemed)
    o["member_discount_cents"] = discount
    o["net_paid_cents"] = net_paid
    # provisional points (estimate; NOT added to member)
    o["points_provisional"] = loyalty_points(net_paid, member["tier"])

    # redeem credit ledger entry only if > 0
    if credit_redeemed > 0:
        append_ledger(o["member_id"], -credit_redeemed, "REDEMPTION", o["id"])
        recompute_member_balances(member)

    o["payment_status"] = "PAID"
    touch(o)
    return success_object(sales_order_out(o), status=200)


@bp.route("/sales-orders/<oid>/reserve", methods=["POST"])
def reserve_order(oid):
    authorize(STAFF_ROLES)
    o = _find_order(oid)
    body = json_body(optional=True)
    # precedence: state (OPEN) -> OCC version -> stock
    if o["fulfillment_status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Order is not OPEN")
    expected = body.get("expected_sales_order_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err(ERR_INVALID_REQUEST, "expected_sales_order_version must be an integer")
        if expected != o["version"]:
            raise err(ERR_STALE_VERSION, "Sales order version is stale")
    lines = _lines_for(oid)
    # stock check: each line's title must have >= line.quantity AVAILABLE
    for line in lines:
        title = db.titles[line["title_id"]]
        recompute_title_counts(title, mutate=False)
        if title["on_hand_qty"] < line["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient stock to reserve")

    # commit: flip oldest-first per line
    affected_titles = set()
    for line in lines:
        avail = available_stock_for_title(line["title_id"])
        chosen = avail[:line["quantity"]]
        for si in chosen:
            si["state"] = "RESERVED"
            si["reserved_order_line_id"] = line["id"]
            touch(si)
        affected_titles.add(line["title_id"])
    for tid in affected_titles:
        recompute_title_counts(db.titles[tid], mutate=True)
    for line in lines:
        recompute_order_line_reserved(line, mutate=True)

    o["fulfillment_status"] = "RESERVED"
    touch(o)
    return success_object(sales_order_out(o), status=200)


@bp.route("/sales-orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    authorize(STAFF_ROLES)
    o = _find_order(oid)
    json_body(optional=True)
    # cross-axis guard: RESERVED on fulfillment AND PAID on payment
    if o["fulfillment_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Order is not RESERVED")
    if o["payment_status"] != "PAID":
        raise err(ERR_INVALID_STATE, "Order is not PAID")

    member = db.members[o["member_id"]]
    lines = _lines_for(oid)
    affected_titles = set()
    for line in lines:
        for si in reserved_stock_for_line(line["id"]):
            si["state"] = "SOLD"
            si["reserved_order_line_id"] = None
            touch(si)
            affected_titles.add(si["title_id"])
            # consignment cascade
            if si["source"] == "CONSIGNMENT" and si.get("consignment_copy_id"):
                copy = db.consignment_copies.get(si["consignment_copy_id"])
                if copy is not None and copy["state"] == "ON_SHELF":
                    sell_consignment_copy(copy, backing_stock_item=si)

    for tid in affected_titles:
        recompute_title_counts(db.titles[tid], mutate=True)
    for line in lines:
        recompute_order_line_reserved(line, mutate=True)

    # finalize points
    recompute_order_subtotal(o)
    pts_final = loyalty_points(o["net_paid_cents"], member["tier"])
    o["points_final"] = pts_final
    member["loyalty_points"] = member.get("loyalty_points", 0) + pts_final
    touch(member)

    o["fulfillment_status"] = "FULFILLED"
    touch(o)
    return success_object(sales_order_out(o), status=200)


@bp.route("/sales-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = authorize(MEMBER_ADMIN)
    o = _find_order(oid)
    check_owner(user_id, role, o["member_id"])
    json_body(optional=True)
    if o["fulfillment_status"] not in ("OPEN", "RESERVED"):
        raise err(ERR_INVALID_STATE, "Order is not OPEN or RESERVED")
    _release_reservations(o)
    o["fulfillment_status"] = "CANCELLED"
    touch(o)
    return success_object(sales_order_out(o), status=200)


@bp.route("/sales-orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    authorize(STAFF_ROLES)
    o = _find_order(oid)
    json_body(optional=True)
    if o["payment_status"] != "PAID":
        raise err(ERR_INVALID_STATE, "Order is not PAID")
    if o["fulfillment_status"] == "FULFILLED":
        raise err(ERR_INVALID_STATE, "Order is already FULFILLED")

    member = db.members[o["member_id"]]
    # restore redeemed credit
    if o["credit_redeemed_cents"] > 0:
        append_ledger(o["member_id"], o["credit_redeemed_cents"], "ADJUSTMENT", o["id"])
        recompute_member_balances(member)
    # cascade fulfillment -> CANCELLED, release stock
    _release_reservations(o)
    o["fulfillment_status"] = "CANCELLED"
    o["payment_status"] = "REFUNDED"
    touch(o)
    return success_object(sales_order_out(o), status=200)


def _release_reservations(o):
    """Release all RESERVED stock on this order's lines back to AVAILABLE."""
    lines = _lines_for(o["id"])
    affected_titles = set()
    for line in lines:
        for si in reserved_stock_for_line(line["id"]):
            si["state"] = "AVAILABLE"
            si["reserved_order_line_id"] = None
            touch(si)
            affected_titles.add(si["title_id"])
    for tid in affected_titles:
        recompute_title_counts(db.titles[tid], mutate=True)
    for line in lines:
        recompute_order_line_reserved(line, mutate=True)
