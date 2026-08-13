"""Return + return-line endpoints (PRD §3.8)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request, g

import db
from errors import (err_invalid_request, err_not_found, err_invalid_state,
                    err_return_window_expired, err_return_line_mismatch,
                    err_custom_not_returnable, err_return_qty_exceeded)
from middleware import require_roles, get_json_body, check_account_ownership, scoped_account_id
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_return, ser_return_line, account_open_receivable
from services import sourcing
from util import is_int

bp = Blueprint("returns", __name__)
PREFIX = "/packaging-distribution"

READ_ROLES = ("PlatformAdmin", "CustomerService", "WarehouseOps", "Buyer")
RETURN_TYPES = {"STOCK", "CUSTOM"}
RETURN_STATUSES = {"REQUESTED", "APPROVED", "REJECTED", "RECEIVED", "RESTOCKED"}
CUSTOM_RESTOCK_PCT = Decimal("0.15")


def _get_return(return_id):
    r = db.returns.get(return_id)
    if r is None:
        raise err_not_found("Return not found.")
    return r


def _return_lines_of(return_id):
    items = [rl for rl in db.return_lines.values() if rl["return_id"] == return_id]
    items.sort(key=lambda rl: rl["_seq"])
    return items


def _prior_returned_qty(order_line_id, excluding_return_id=None):
    """Qty on prior non-REJECTED return lines for the order line."""
    total = 0
    for rl in db.return_lines.values():
        if rl["order_line_id"] != order_line_id:
            continue
        r = db.returns.get(rl["return_id"])
        if r is None or r["status"] == "REJECTED":
            continue
        if excluding_return_id is not None and r["id"] == excluding_return_id:
            continue
        total += rl["qty"]
    return total


def _round_half_up_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _compute_return_financials(ret):
    """calc_return_restock: round half-up per line, then sum."""
    pct = CUSTOM_RESTOCK_PCT if ret["return_type"] == "CUSTOM" else Decimal("0")
    refund = 0
    fee = 0
    for rl in _return_lines_of(ret["id"]):
        line = db.order_lines[rl["order_line_id"]]
        unit = Decimal(line["unit_price_cents"])
        credit = Decimal(rl["qty"]) * unit * (Decimal(1) - pct)
        fee_part = Decimal(rl["qty"]) * unit * pct
        refund += _round_half_up_cents(credit)
        fee += _round_half_up_cents(fee_part)
    ret["refund_cents"] = refund
    ret["restock_fee_cents"] = fee


def _check_type_eligibility(ret_type, lines):
    for line in lines:
        is_custom = db.products[line["product_id"]]["is_custom_print"]
        if ret_type == "CUSTOM" and not is_custom:
            raise err_custom_not_returnable("A CUSTOM return may reference only custom-print lines.")
        if ret_type == "STOCK" and is_custom:
            raise err_custom_not_returnable("A STOCK return may reference only stock lines.")


@bp.route(f"{PREFIX}/returns", methods=["POST"])
@require_roles("Buyer", "CustomerService")
def create_return():
    body = get_json_body(required=True)
    order_id = body.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise err_invalid_request("Missing required field: order_id.")
    return_type = body.get("return_type")
    if not isinstance(return_type, str) or not return_type:
        raise err_invalid_request("Missing required field: return_type.")
    reason_code = body.get("reason_code")
    if not isinstance(reason_code, str) or not reason_code:
        raise err_invalid_request("Missing required field: reason_code.")

    order = db.orders.get(order_id)
    if order is None:
        raise err_not_found("Order not found.")
    if g.role == "Buyer":
        check_account_ownership(order["account_id"])
    if order["status"] != "SHIPPED":
        raise err_invalid_state("Returns may be requested only against SHIPPED orders.")
    if return_type not in RETURN_TYPES:
        raise err_invalid_request("Field 'return_type' must be STOCK or CUSTOM.")

    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise err_invalid_request("Field 'lines' must be a non-empty array.")

    # Resolve referenced order lines (existence, left to right).
    resolved = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise err_invalid_request("Each return line must be an object.")
        ol_id = entry.get("order_line_id")
        if not isinstance(ol_id, str) or not ol_id:
            raise err_invalid_request("Each return line requires 'order_line_id'.")
        line = db.order_lines.get(ol_id)
        if line is None:
            raise err_not_found("Order line not found.")
        resolved.append((entry, line))

    # Priority 18: every line must belong to this return's order.
    for entry, line in resolved:
        if line["order_id"] != order["id"]:
            raise err_return_line_mismatch()

    # Priority 19: custom-vs-stock eligibility.
    _check_type_eligibility(return_type, [line for _, line in resolved])

    # Priority 21 (+ malformed qty): qty >= 1 and within shipped minus prior.
    in_request = {}
    for entry, line in resolved:
        qty = entry.get("qty")
        if not is_int(qty) or qty < 1:
            raise err_invalid_request("Return line 'qty' must be an integer >= 1.")
        prior = _prior_returned_qty(line["id"]) + in_request.get(line["id"], 0)
        if qty > line["shipped_qty"] - prior:
            raise err_return_qty_exceeded()
        in_request[line["id"]] = in_request.get(line["id"], 0) + qty

    now = db.now()
    ret = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "order_id": order["id"],
        "return_type": return_type,
        "status": "REQUESTED",
        "reason_code": reason_code,
        "restock_fee_cents": 0,
        "refund_cents": 0,
        "requested_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.returns[ret["id"]] = ret
    for entry, line in resolved:
        rl = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "return_id": ret["id"],
            "order_line_id": line["id"],
            "qty": entry["qty"],
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.return_lines[rl["id"]] = rl
    return success_object(ser_return(ret), status=201)


@bp.route(f"{PREFIX}/returns", methods=["GET"])
@require_roles(*READ_ROLES)
def list_returns():
    limit, offset = parse_pagination(request.args)
    order_f = request.args.get("order_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in RETURN_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    scoped = scoped_account_id()
    items = sorted(db.returns.values(), key=lambda r: (r["created_at"], r["_seq"]))
    if scoped is not None:
        items = [r for r in items
                 if r["order_id"] in db.orders and db.orders[r["order_id"]]["account_id"] == scoped]
    if order_f is not None:
        items = [r for r in items if r["order_id"] == order_f]
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_return(r) for r in page], pagination)


@bp.route(f"{PREFIX}/returns/<return_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_return(return_id):
    ret = _get_return(return_id)
    order = db.orders.get(ret["order_id"])
    if order is not None:
        check_account_ownership(order["account_id"])
    return success_object(ser_return(ret))


@bp.route(f"{PREFIX}/returns/<return_id>/lines", methods=["GET"])
@require_roles(*READ_ROLES)
def list_return_lines(return_id):
    ret = _get_return(return_id)
    order = db.orders.get(ret["order_id"])
    if order is not None:
        check_account_ownership(order["account_id"])
    limit, offset = parse_pagination(request.args)
    items = _return_lines_of(ret["id"])
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_return_line(rl) for rl in page], pagination)


@bp.route(f"{PREFIX}/return-lines", methods=["GET"])
@require_roles(*READ_ROLES)
def list_return_lines_flat():
    limit, offset = parse_pagination(request.args)
    return_f = request.args.get("return_id")
    line_f = request.args.get("order_line_id")
    scoped = scoped_account_id()
    items = sorted(db.return_lines.values(), key=lambda rl: (rl["created_at"], rl["_seq"]))
    if scoped is not None:
        def owned(rl):
            r = db.returns.get(rl["return_id"])
            if r is None:
                return False
            o = db.orders.get(r["order_id"])
            return o is not None and o["account_id"] == scoped
        items = [rl for rl in items if owned(rl)]
    if return_f is not None:
        items = [rl for rl in items if rl["return_id"] == return_f]
    if line_f is not None:
        items = [rl for rl in items if rl["order_line_id"] == line_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_return_line(rl) for rl in page], pagination)


@bp.route(f"{PREFIX}/return-lines/<line_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_return_line(line_id):
    rl = db.return_lines.get(line_id)
    if rl is None:
        raise err_not_found("Return line not found.")
    ret = db.returns.get(rl["return_id"])
    order = db.orders.get(ret["order_id"]) if ret else None
    if order is not None:
        check_account_ownership(order["account_id"])
    return success_object(ser_return_line(rl))


@bp.route(f"{PREFIX}/returns/<return_id>/approve", methods=["POST"])
@require_roles("CustomerService")
def approve_return(return_id):
    ret = _get_return(return_id)
    if ret["status"] != "REQUESTED":
        raise err_invalid_state("Only a REQUESTED return can be approved.")
    # Priority 17: 30-calendar-day window (now - 30d <= requested_at).
    if ret["requested_at"] < db.now() - timedelta(days=30):
        raise err_return_window_expired()
    # Priority 19: type eligibility re-checked at approval.
    lines = [db.order_lines[rl["order_line_id"]] for rl in _return_lines_of(ret["id"])]
    _check_type_eligibility(ret["return_type"], lines)
    _compute_return_financials(ret)
    ret["status"] = "APPROVED"
    db.touch(ret)
    return success_object(ser_return(ret))


@bp.route(f"{PREFIX}/returns/<return_id>/reject", methods=["POST"])
@require_roles("CustomerService")
def reject_return(return_id):
    ret = _get_return(return_id)
    get_json_body()  # optional reason
    if ret["status"] != "REQUESTED":
        raise err_invalid_state("Only a REQUESTED return can be rejected.")
    ret["status"] = "REJECTED"
    db.touch(ret)
    return success_object(ser_return(ret))


@bp.route(f"{PREFIX}/returns/<return_id>/receive", methods=["POST"])
@require_roles("WarehouseOps")
def receive_return(return_id):
    ret = _get_return(return_id)
    if ret["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED return can be received.")
    _compute_return_financials(ret)  # finalize under the same per-line-then-sum rule
    ret["status"] = "RECEIVED"
    db.touch(ret)
    return success_object(ser_return(ret))


@bp.route(f"{PREFIX}/returns/<return_id>/restock", methods=["POST"])
@require_roles("WarehouseOps")
def restock_return(return_id):
    ret = _get_return(return_id)
    if ret["status"] != "RECEIVED":
        raise err_invalid_state("Only a RECEIVED return can be restocked.")

    order = db.orders[ret["order_id"]]
    crossings = []
    if ret["return_type"] == "STOCK":
        for rl in _return_lines_of(ret["id"]):
            line = db.order_lines[rl["order_line_id"]]
            inv_id = db.inventory_by_pair.get((line["product_id"], line["allocated_warehouse_id"]))
            if inv_id is None:
                continue
            inv = db.inventory[inv_id]
            before = inv["on_hand_qty"] - inv["reserved_qty"]
            inv["on_hand_qty"] += rl["qty"]
            db.touch(inv)
            crossings.append((inv_id, before))
    # CUSTOM returns are scrapped: no inventory movement.

    ret["status"] = "RESTOCKED"
    db.touch(ret)

    for inv_id, before in crossings:
        sourcing.fire_notifications_for_crossing(db.inventory[inv_id], before)

    # Full-coverage check: every order line covered by RESTOCKED return qty.
    order_lines = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    fully = True
    for l in order_lines:
        restocked = 0
        for rl in db.return_lines.values():
            if rl["order_line_id"] != l["id"]:
                continue
            r = db.returns.get(rl["return_id"])
            if r is not None and r["status"] == "RESTOCKED":
                restocked += rl["qty"]
        if restocked != l["shipped_qty"]:
            fully = False
            break
    if order["status"] == "SHIPPED" and fully:
        order["status"] = "RETURNED"
        order["invoice_status"] = "VOID"
        db.touch(order)

    return success_object(ser_return(ret))
