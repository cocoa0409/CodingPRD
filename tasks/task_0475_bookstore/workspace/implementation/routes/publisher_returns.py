"""Returns to publisher (guarded branch + OCC submit)."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_int,
                    parse_pagination, paginate)
from db import db
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_TITLE_NOT_RETURNABLE, ERR_INSUFFICIENT_STOCK,
                    ERR_INVALID_REQUEST)
from middleware import authorize
from response import success_object, success_list
from serialize import publisher_return_out
from services import (recompute_title_counts, available_stock_for_title)
from calculations import return_credit

bp = Blueprint("publisher_returns", __name__)

PR_ROLES = {"InventoryManager", "StoreAdmin"}


def _find(pid):
    pr = db.publisher_returns.get(pid)
    if pr is None:
        raise err(ERR_NOT_FOUND, "Publisher return not found")
    return pr


@bp.route("/publisher-returns", methods=["POST"])
def create_return():
    authorize(PR_ROLES)
    body = json_body(optional=False)
    title_id = get_str(body, "title_id", required=True)
    quantity = get_int(body, "quantity", required=True, minimum=1)
    if title_id not in db.titles:
        raise err(ERR_NOT_FOUND, "Title not found")
    rec = make_record({
        "title_id": title_id,
        "quantity": quantity,
        "state": "DRAFT",
        "credit_unit_cents": None,
        "credit_total_cents": None,
    })
    db.publisher_returns[rec["id"]] = rec
    return success_object(publisher_return_out(rec), status=201)


@bp.route("/publisher-returns/<pid>", methods=["GET"])
def get_return(pid):
    authorize(PR_ROLES)
    pr = _find(pid)
    return success_object(publisher_return_out(pr), status=200)


@bp.route("/publisher-returns", methods=["GET"])
def list_returns():
    authorize(PR_ROLES)
    title_id = request.args.get("title_id")
    state = request.args.get("state")
    items = list(db.publisher_returns.values())
    if title_id is not None:
        items = [p for p in items if p["title_id"] == title_id]
    if state is not None:
        items = [p for p in items if p["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([publisher_return_out(p) for p in page], limit, offset, total)


@bp.route("/publisher-returns/<pid>/submit", methods=["POST"])
def submit(pid):
    authorize(PR_ROLES)
    pr = _find(pid)
    body = json_body(optional=True)
    # precedence: state (DRAFT) -> OCC -> returnable -> stock
    if pr["state"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Publisher return is not DRAFT")
    expected = body.get("expected_publisher_return_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err(ERR_INVALID_REQUEST, "expected_publisher_return_version must be an integer")
        if expected != pr["version"]:
            raise err(ERR_STALE_VERSION, "Publisher return version is stale")
    title = db.titles[pr["title_id"]]
    if not title["returnable"]:
        raise err(ERR_TITLE_NOT_RETURNABLE, "Title is not returnable")
    recompute_title_counts(title, mutate=False)
    if title["on_hand_qty"] < pr["quantity"]:
        raise err(ERR_INSUFFICIENT_STOCK, "Insufficient stock to return")

    # snapshot credit, reserve copies oldest-first
    credit_unit, credit_total = return_credit(title["list_price_cents"], pr["quantity"])
    pr["credit_unit_cents"] = credit_unit
    pr["credit_total_cents"] = credit_total
    avail = available_stock_for_title(pr["title_id"])
    for si in avail[:pr["quantity"]]:
        si["state"] = "RESERVED"
        si["reserved_order_line_id"] = None
        touch(si)
    recompute_title_counts(title, mutate=True)
    pr["state"] = "SUBMITTED"
    touch(pr)
    return success_object(publisher_return_out(pr), status=200)


def _reserved_copies_for_return(pr):
    """RESERVED copies of this return's title with no order line (held by a return).
    We track which copies a return reserved by selecting RESERVED stock for the
    title whose reserved_order_line_id is null, oldest-first, up to quantity."""
    items = [
        si for si in db.stock_items.values()
        if si["title_id"] == pr["title_id"] and si["state"] == "RESERVED"
        and si.get("reserved_order_line_id") is None
    ]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return items[:pr["quantity"]]


@bp.route("/publisher-returns/<pid>/accept", methods=["POST"])
def accept(pid):
    authorize(PR_ROLES)
    pr = _find(pid)
    json_body(optional=True)
    if pr["state"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Publisher return is not SUBMITTED")
    title = db.titles[pr["title_id"]]
    for si in _reserved_copies_for_return(pr):
        si["state"] = "RETURNED_TO_PUBLISHER"
        touch(si)
    recompute_title_counts(title, mutate=True)
    pr["state"] = "ACCEPTED"
    touch(pr)
    return success_object(publisher_return_out(pr), status=200)


@bp.route("/publisher-returns/<pid>/reject", methods=["POST"])
def reject(pid):
    authorize(PR_ROLES)
    pr = _find(pid)
    json_body(optional=True)
    if pr["state"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Publisher return is not SUBMITTED")
    title = db.titles[pr["title_id"]]
    for si in _reserved_copies_for_return(pr):
        si["state"] = "AVAILABLE"
        touch(si)
    pr["credit_total_cents"] = 0
    recompute_title_counts(title, mutate=True)
    pr["state"] = "REJECTED"
    touch(pr)
    return success_object(publisher_return_out(pr), status=200)
