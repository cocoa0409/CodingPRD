"""Special orders and print-on-demand (revision cycle)."""
from flask import Blueprint, request

from clock import clock
from common import (json_body, make_record, touch, get_str, get_int, get_enum,
                    parse_pagination, paginate)
from datetime_util import format_iso8601
from db import db
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_TITLE_NOT_POD_ELIGIBLE, ERR_REVISION_LIMIT)
from middleware import authorize, check_owner
from response import success_object, success_list
from serialize import special_order_out
from services import recompute_title_counts
from calculations import special_order_quote

bp = Blueprint("special_orders", __name__)

CREATE_ROLES = {"Member", "Bookseller", "StoreAdmin"}
READ_ROLES = {"Member", "Bookseller", "StoreAdmin"}
MEMBER_ADMIN = {"Member", "StoreAdmin"}
STAFF_ROLES = {"Bookseller", "StoreAdmin"}


def _find(soid):
    so = db.special_orders.get(soid)
    if so is None:
        raise err(ERR_NOT_FOUND, "Special order not found")
    return so


@bp.route("/special-orders", methods=["POST"])
def create_special_order():
    user_id, role = authorize(CREATE_ROLES)
    body = json_body(optional=False)
    member_id = get_str(body, "member_id", required=True)
    title_id = get_str(body, "title_id", required=True)
    quantity = get_int(body, "quantity", required=True, minimum=1)
    fulfillment_method = get_enum(body, "fulfillment_method", ["DISTRIBUTOR", "POD"],
                                  required=True)
    check_owner(user_id, role, member_id)
    if member_id not in db.members:
        raise err(ERR_NOT_FOUND, "Member not found")
    if title_id not in db.titles:
        raise err(ERR_NOT_FOUND, "Title not found")

    rec = make_record({
        "member_id": member_id,
        "title_id": title_id,
        "quantity": quantity,
        "fulfillment_method": fulfillment_method,
        "state": "DRAFT",
        "quoted_unit_cents": None,
        "promised_eta": None,
        "revision_count": 0,
    })
    db.special_orders[rec["id"]] = rec
    return success_object(special_order_out(rec), status=201)


@bp.route("/special-orders/<soid>", methods=["GET"])
def get_special_order(soid):
    user_id, role = authorize(READ_ROLES)
    so = _find(soid)
    check_owner(user_id, role, so["member_id"])
    return success_object(special_order_out(so), status=200)


@bp.route("/special-orders", methods=["GET"])
def list_special_orders():
    user_id, role = authorize(READ_ROLES)
    member_id = request.args.get("member_id")
    title_id = request.args.get("title_id")
    state = request.args.get("state")
    items = list(db.special_orders.values())
    if role == "Member":
        items = [s for s in items if s["member_id"] == user_id]
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if title_id is not None:
        items = [s for s in items if s["title_id"] == title_id]
    if state is not None:
        items = [s for s in items if s["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([special_order_out(s) for s in page], limit, offset, total)


@bp.route("/special-orders/<soid>/quote", methods=["POST"])
def quote(soid):
    authorize(STAFF_ROLES)
    so = _find(soid)
    json_body(optional=True)
    if so["state"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Special order is not DRAFT")
    title = db.titles[so["title_id"]]
    if so["fulfillment_method"] == "POD" and not title["pod_eligible"]:
        raise err(ERR_TITLE_NOT_POD_ELIGIBLE, "Title is not POD eligible")
    quoted_unit, eta = special_order_quote(title["list_price_cents"],
                                           so["fulfillment_method"], clock.now())
    so["quoted_unit_cents"] = quoted_unit
    so["promised_eta"] = format_iso8601(eta)
    so["state"] = "QUOTED"
    touch(so)
    return success_object(special_order_out(so), status=200)


@bp.route("/special-orders/<soid>/revise", methods=["POST"])
def revise(soid):
    user_id, role = authorize(MEMBER_ADMIN)
    so = _find(soid)
    check_owner(user_id, role, so["member_id"])
    json_body(optional=True)
    if so["state"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "Special order is not QUOTED")
    if so["revision_count"] >= 3:
        raise err(ERR_REVISION_LIMIT, "Revision limit reached")
    so["quoted_unit_cents"] = None
    so["promised_eta"] = None
    so["revision_count"] += 1
    so["state"] = "DRAFT"
    touch(so)
    return success_object(special_order_out(so), status=200)


@bp.route("/special-orders/<soid>/confirm", methods=["POST"])
def confirm(soid):
    user_id, role = authorize(MEMBER_ADMIN)
    so = _find(soid)
    check_owner(user_id, role, so["member_id"])
    json_body(optional=True)
    if so["state"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "Special order is not QUOTED")
    so["state"] = "CONFIRMED"
    touch(so)
    return success_object(special_order_out(so), status=200)


@bp.route("/special-orders/<soid>/receive", methods=["POST"])
def receive(soid):
    authorize(STAFF_ROLES)
    so = _find(soid)
    json_body(optional=True)
    if so["state"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Special order is not CONFIRMED")
    title = db.titles[so["title_id"]]
    cost = so["quoted_unit_cents"] or 0
    for _ in range(so["quantity"]):
        si = make_record({
            "title_id": so["title_id"],
            "source": "DISTRIBUTOR",
            "cost_cents": cost,
            "state": "AVAILABLE",
            "reserved_order_line_id": None,
            "consignment_copy_id": None,
        })
        db.stock_items[si["id"]] = si
    recompute_title_counts(title, mutate=True)
    so["state"] = "RECEIVED"
    touch(so)
    return success_object(special_order_out(so), status=200)


@bp.route("/special-orders/<soid>/cancel", methods=["POST"])
def cancel(soid):
    user_id, role = authorize(MEMBER_ADMIN)
    so = _find(soid)
    check_owner(user_id, role, so["member_id"])
    json_body(optional=True)
    if so["state"] not in ("DRAFT", "QUOTED"):
        raise err(ERR_INVALID_STATE, "Special order is not DRAFT or QUOTED")
    so["state"] = "CANCELLED"
    touch(so)
    return success_object(special_order_out(so), status=200)
