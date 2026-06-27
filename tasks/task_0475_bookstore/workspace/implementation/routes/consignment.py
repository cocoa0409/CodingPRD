"""Local-author consignment: agreements, copies, sales, termination."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_int,
                    parse_pagination, paginate)
from db import db
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NOT_LOCAL_AUTHOR)
from middleware import authorize
from response import success_object, success_list
from serialize import consignment_agreement_out, consignment_copy_out
from services import recompute_title_counts, sell_consignment_copy

bp = Blueprint("consignment", __name__)

IM_ROLES = {"InventoryManager", "StoreAdmin"}
READ_ROLES = {"Member", "InventoryManager", "StoreAdmin"}
SELL_ROLES = {"Bookseller", "StoreAdmin"}


def _find_agreement(aid):
    a = db.consignment_agreements.get(aid)
    if a is None:
        raise err(ERR_NOT_FOUND, "Consignment agreement not found")
    return a


def _find_copy(cid):
    c = db.consignment_copies.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "Consignment copy not found")
    return c


@bp.route("/consignment-agreements", methods=["POST"])
def create_agreement():
    authorize(IM_ROLES)
    body = json_body(optional=False)
    author_member_id = get_str(body, "author_member_id", required=True)
    title_id = get_str(body, "title_id", required=True)
    # existence first (left-to-right): author then title
    author = db.members.get(author_member_id)
    if author is None:
        raise err(ERR_NOT_FOUND, "Author member not found")
    if title_id not in db.titles:
        raise err(ERR_NOT_FOUND, "Title not found")
    # business: author must be a local author
    if not author["is_local_author"]:
        raise err(ERR_NOT_LOCAL_AUTHOR, "Member is not a local author")
    rec = make_record({
        "author_member_id": author_member_id,
        "title_id": title_id,
        "units_sold_to_date": 0,
        "total_payout_cents": 0,
        "state": "ACTIVE",
    })
    db.consignment_agreements[rec["id"]] = rec
    return success_object(consignment_agreement_out(rec), status=201)


@bp.route("/consignment-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    authorize(READ_ROLES)
    a = _find_agreement(aid)
    return success_object(consignment_agreement_out(a), status=200)


@bp.route("/consignment-agreements", methods=["GET"])
def list_agreements():
    authorize(READ_ROLES)
    author_member_id = request.args.get("author_member_id")
    title_id = request.args.get("title_id")
    state = request.args.get("state")
    items = list(db.consignment_agreements.values())
    if author_member_id is not None:
        items = [a for a in items if a["author_member_id"] == author_member_id]
    if title_id is not None:
        items = [a for a in items if a["title_id"] == title_id]
    if state is not None:
        items = [a for a in items if a["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([consignment_agreement_out(a) for a in page], limit, offset, total)


@bp.route("/consignment-agreements/<aid>/copies", methods=["POST"])
def shelve_copy(aid):
    authorize(IM_ROLES)
    a = _find_agreement(aid)
    body = json_body(optional=False)
    sale_price_cents = get_int(body, "sale_price_cents", required=True, minimum=0)
    # terminated agreement accepts no new copies
    if a["state"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Agreement is not ACTIVE")
    copy = make_record({
        "agreement_id": aid,
        "sale_price_cents": sale_price_cents,
        "state": "ON_SHELF",
        "payout_cents": None,
    })
    db.consignment_copies[copy["id"]] = copy
    # backing CONSIGNMENT StockItem, AVAILABLE, linked via consignment_copy_id
    si = make_record({
        "title_id": a["title_id"],
        "source": "CONSIGNMENT",
        "cost_cents": 0,
        "state": "AVAILABLE",
        "reserved_order_line_id": None,
        "consignment_copy_id": copy["id"],
    })
    db.stock_items[si["id"]] = si
    recompute_title_counts(db.titles[a["title_id"]], mutate=True)
    return success_object(consignment_copy_out(copy), status=201)


@bp.route("/consignment-agreements/<aid>/copies", methods=["GET"])
def list_copies(aid):
    authorize(READ_ROLES)
    a = _find_agreement(aid)
    state = request.args.get("state")
    items = [c for c in db.consignment_copies.values() if c["agreement_id"] == aid]
    if state is not None:
        items = [c for c in items if c["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([consignment_copy_out(c) for c in page], limit, offset, total)


@bp.route("/consignment-copies/<cid>/mark-sold", methods=["POST"])
def mark_sold(cid):
    authorize(SELL_ROLES)
    copy = _find_copy(cid)
    json_body(optional=True)
    if copy["state"] != "ON_SHELF":
        raise err(ERR_INVALID_STATE, "Copy is not ON_SHELF")
    agreement = db.consignment_agreements[copy["agreement_id"]]
    if agreement["state"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Agreement is not ACTIVE")
    sell_consignment_copy(copy)
    recompute_title_counts(db.titles[agreement["title_id"]], mutate=True)
    return success_object(consignment_copy_out(copy), status=200)


@bp.route("/consignment-agreements/<aid>/terminate", methods=["POST"])
def terminate(aid):
    authorize(IM_ROLES)
    a = _find_agreement(aid)
    json_body(optional=True)
    if a["state"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Agreement is not ACTIVE")
    # cascade ON_SHELF copies -> RETURNED_TO_AUTHOR, remove backing stock
    for copy in db.consignment_copies.values():
        if copy["agreement_id"] == aid and copy["state"] == "ON_SHELF":
            copy["state"] = "RETURNED_TO_AUTHOR"
            touch(copy)
            for si in db.stock_items.values():
                if si.get("consignment_copy_id") == copy["id"] and si["state"] == "AVAILABLE":
                    si["state"] = "RETURNED_TO_PUBLISHER"
                    touch(si)
    recompute_title_counts(db.titles[a["title_id"]], mutate=True)
    a["state"] = "TERMINATED"
    touch(a)
    return success_object(consignment_agreement_out(a), status=200)
