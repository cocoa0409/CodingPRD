"""Used-book buyback transactions."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_int, get_enum,
                    parse_pagination, paginate)
from db import db
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_EMPTY_TRANSACTION,
                    ERR_MEMBER_SUSPENDED)
from middleware import authorize
from response import success_object, success_list
from serialize import buyback_out, buyback_line_out
from services import (recompute_title_counts, recompute_member_balances,
                      append_ledger)
from calculations import buyback_line_offer

bp = Blueprint("buybacks", __name__)

STAFF_ROLES = {"Bookseller", "StoreAdmin"}
READ_ROLES = {"Member", "Bookseller", "StoreAdmin"}


def _find(bid):
    b = db.buybacks.get(bid)
    if b is None:
        raise err(ERR_NOT_FOUND, "Buyback transaction not found")
    return b


def _lines_for(bid):
    lines = [l for l in db.buyback_lines.values() if l["buyback_id"] == bid]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


@bp.route("/buybacks", methods=["POST"])
def create_buyback():
    authorize(STAFF_ROLES)
    body = json_body(optional=False)
    member_id = get_str(body, "member_id", required=True)
    if member_id not in db.members:
        raise err(ERR_NOT_FOUND, "Member not found")
    rec = make_record({
        "member_id": member_id,
        "state": "PENDING",
        "offer_total_cents": None,
    })
    db.buybacks[rec["id"]] = rec
    return success_object(buyback_out(rec), status=201)


@bp.route("/buybacks/<bid>", methods=["GET"])
def get_buyback(bid):
    authorize(READ_ROLES)
    b = _find(bid)
    return success_object(buyback_out(b), status=200)


@bp.route("/buybacks", methods=["GET"])
def list_buybacks():
    user_id, role = authorize(READ_ROLES)
    member_id = request.args.get("member_id")
    state = request.args.get("state")
    items = list(db.buybacks.values())
    if role == "Member":
        items = [b for b in items if b["member_id"] == user_id]
    if member_id is not None:
        items = [b for b in items if b["member_id"] == member_id]
    if state is not None:
        items = [b for b in items if b["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([buyback_out(b) for b in page], limit, offset, total)


@bp.route("/buybacks/<bid>/lines", methods=["POST"])
def add_line(bid):
    authorize(STAFF_ROLES)
    b = _find(bid)
    body = json_body(optional=False)
    title_id = get_str(body, "title_id", required=True)
    condition_grade = get_enum(body, "condition_grade",
                               ["LIKE_NEW", "GOOD", "FAIR"], required=True)
    quantity = get_int(body, "quantity", required=True, minimum=1)
    if b["state"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Buyback is not PENDING")
    if title_id not in db.titles:
        raise err(ERR_NOT_FOUND, "Title not found")
    line = make_record({
        "buyback_id": bid,
        "title_id": title_id,
        "condition_grade": condition_grade,
        "quantity": quantity,
        "line_offer_cents": None,
    })
    db.buyback_lines[line["id"]] = line
    touch(b)
    return success_object(buyback_line_out(line), status=201)


@bp.route("/buybacks/<bid>/lines", methods=["GET"])
def list_lines(bid):
    authorize(READ_ROLES)
    b = _find(bid)
    lines = _lines_for(bid)
    limit, offset = parse_pagination(request.args)
    page, total = paginate(lines, limit, offset)
    return success_list([buyback_line_out(l) for l in page], limit, offset, total)


@bp.route("/buybacks/<bid>/offer", methods=["POST"])
def offer(bid):
    authorize(STAFF_ROLES)
    b = _find(bid)
    json_body(optional=True)
    if b["state"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Buyback is not PENDING")
    lines = _lines_for(bid)
    if len(lines) == 0:
        raise err(ERR_EMPTY_TRANSACTION, "Buyback has no lines")
    total = 0
    for line in lines:
        title = db.titles[line["title_id"]]
        line_offer = buyback_line_offer(title["list_price_cents"], title["demand_flag"],
                                        line["condition_grade"], line["quantity"])
        line["line_offer_cents"] = line_offer
        touch(line)
        total += line_offer
    b["offer_total_cents"] = total
    b["state"] = "OFFERED"
    touch(b)
    return success_object(buyback_out(b), status=200)


@bp.route("/buybacks/<bid>/complete", methods=["POST"])
def complete(bid):
    authorize(STAFF_ROLES)
    b = _find(bid)
    json_body(optional=True)
    if b["state"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Buyback is not OFFERED")
    member = db.members[b["member_id"]]
    if member["status"] != "ACTIVE":
        raise err(ERR_MEMBER_SUSPENDED, "Member is suspended")

    lines = _lines_for(bid)
    affected_titles = set()
    for line in lines:
        per_copy_cost = line["line_offer_cents"] // line["quantity"] if line["quantity"] else 0
        for _ in range(line["quantity"]):
            si = make_record({
                "title_id": line["title_id"],
                "source": "BUYBACK",
                "cost_cents": per_copy_cost,
                "state": "AVAILABLE",
                "reserved_order_line_id": None,
                "consignment_copy_id": None,
            })
            db.stock_items[si["id"]] = si
        affected_titles.add(line["title_id"])
    append_ledger(b["member_id"], b["offer_total_cents"], "BUYBACK", b["id"])
    recompute_member_balances(member)
    for tid in affected_titles:
        recompute_title_counts(db.titles[tid], mutate=True)
    b["state"] = "COMPLETED"
    touch(b)
    return success_object(buyback_out(b), status=200)


@bp.route("/buybacks/<bid>/void", methods=["POST"])
def void(bid):
    authorize(STAFF_ROLES)
    b = _find(bid)
    json_body(optional=True)
    if b["state"] not in ("PENDING", "OFFERED"):
        raise err(ERR_INVALID_STATE, "Buyback is not PENDING or OFFERED")
    b["state"] = "VOIDED"
    touch(b)
    return success_object(buyback_out(b), status=200)
