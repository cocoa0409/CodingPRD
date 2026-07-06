from flask import Blueprint, request

from db import db, new_common, public, touch
from middleware import auth, require_role
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INSUFFICIENT_INVENTORY,
)
from helpers import (
    body,
    require_str,
    require_int,
    find_customer,
    find_sku,
    find_bulk_quote,
    paginate,
    sorted_by_created,
)
from response import ok_object, ok_list
from services import calc

bp = Blueprint("bulk_quotes", __name__)


def serialize_quote(q):
    return public(q)


@bp.post("/bulk-quotes")
def create_quote():
    user_id, role = auth()
    require_role(role, {"CorporateBuyer", "PlatformAdmin"})
    data = body()
    buyer_id = require_str(data, "corporate_buyer_id")
    sku_id = require_str(data, "sku_id")
    quantity = require_int(data, "quantity", minimum=1)
    gift_box_count = data.get("gift_box_count", 0)
    if gift_box_count is None:
        gift_box_count = 0
    if isinstance(gift_box_count, bool) or not isinstance(gift_box_count, int) or gift_box_count < 0:
        raise err(ERR_INVALID_REQUEST, "Invalid gift_box_count")
    if role == "CorporateBuyer" and user_id != buyer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    find_customer(buyer_id)
    find_sku(sku_id)

    qid = db.new_id()
    quote = {
        "id": qid,
        "corporate_buyer_id": buyer_id,
        "sku_id": sku_id,
        "quantity": quantity,
        "gift_box_count": gift_box_count,
        "status": "DRAFT",
        "line_subtotal_cents": 0,
        "discount_cents": 0,
        "handling_cents": 0,
        "total_cents": 0,
    }
    quote.update(new_common())
    db.bulk_quotes[qid] = quote
    return ok_object(serialize_quote(quote), 201)


@bp.get("/bulk-quotes/<qid>")
def get_quote(qid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "CorporateBuyer"})
    quote = find_bulk_quote(qid)
    if role == "CorporateBuyer" and user_id != quote["corporate_buyer_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    return ok_object(serialize_quote(quote))


@bp.get("/bulk-quotes")
def list_quotes():
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "CorporateBuyer"})
    items = list(db.bulk_quotes.values())
    if role == "CorporateBuyer":
        items = [q for q in items if q["corporate_buyer_id"] == user_id]
    for key in ("corporate_buyer_id", "sku_id"):
        v = request.args.get(key)
        if v is not None:
            items = [q for q in items if q.get(key) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_quote(q) for q in page], limit, offset, total)


@bp.post("/bulk-quotes/<qid>/quote")
def quote_quote(qid):
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    quote = find_bulk_quote(qid)
    if quote["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Quote requires DRAFT")
    sku = db.skus[quote["sku_id"]]
    if sku["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "SKU not ACTIVE")
    figures = calc.corporate_bulk_quote(quote["quantity"], sku["unit_price_cents"], quote["gift_box_count"])
    quote.update(figures)
    quote["status"] = "QUOTED"
    touch(quote)
    return ok_object(serialize_quote(quote))


@bp.post("/bulk-quotes/<qid>/accept")
def accept_quote(qid):
    user_id, role = auth()
    require_role(role, {"CorporateBuyer"})
    quote = find_bulk_quote(qid)
    if user_id != quote["corporate_buyer_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    if quote["status"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "Accept requires QUOTED")
    sku = db.skus[quote["sku_id"]]
    if sku["available_units"] < quote["quantity"]:
        raise err(ERR_INSUFFICIENT_INVENTORY, "Insufficient inventory for quote")
    quote["status"] = "ACCEPTED"
    touch(quote)
    return ok_object(serialize_quote(quote))
