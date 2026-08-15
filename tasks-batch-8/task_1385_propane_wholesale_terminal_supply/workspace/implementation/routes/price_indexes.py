"""Price index publication endpoints (append-only configuration)."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import (
    err_not_found,
    err_invalid_request,
    err_duplicate_index_publication,
)

bp = Blueprint("price_indexes", __name__)

READ_ROLES = ["PricingDesk", "CreditManager", "SupplyPlanner", "SupplyAdmin", "Dispatcher", "DealerUser"]
INDEX_NAMES = {"MT_BELVIEU", "CONWAY"}


@bp.route("/price-index-publications", methods=["POST"])
def create_publication():
    caller = mw.authenticate()
    mw.authorize(caller, ["PricingDesk"])
    body = mw.get_json_body(required=True)
    index_name = mw.req_enum(body, "index_name", INDEX_NAMES)
    effective_date = mw.req_date(body, "effective_date")
    price_mc_per_gal = mw.req_int(body, "price_mc_per_gal")

    if price_mc_per_gal <= 0:
        raise err_invalid_request("price_mc_per_gal must be > 0")

    for p in db.price_index_publications.values():
        if p["index_name"] == index_name and p["effective_date"] == effective_date:
            raise err_duplicate_index_publication()

    now = svc.stamp_now()
    p = {
        "id": db.new_id(),
        "index_name": index_name,
        "effective_date": effective_date,
        "price_mc_per_gal": price_mc_per_gal,
        "created_at": now,
        "_seq": db.next_seq(),
    }
    db.price_index_publications[p["id"]] = p
    return resp.created(ser.serialize_price_index_publication(p))


# NOTE: /resolve must be registered before /<pid> so the literal wins.
@bp.route("/price-index-publications/resolve", methods=["GET"])
def resolve_publication():
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    from flask import request

    index_name = request.args.get("index_name")
    on_date = request.args.get("on_date")
    if index_name is None or index_name not in INDEX_NAMES:
        raise err_invalid_request("index_name query param is required and must be a valid index")
    if on_date is None:
        raise err_invalid_request("on_date query param is required")
    from datetime import date as _date

    try:
        d = _date.fromisoformat(on_date)
    except (ValueError, TypeError):
        raise err_invalid_request("on_date must be an ISO date")
    best = svc.resolve_index(index_name, d)
    if best is None:
        raise err_not_found("No publication effective on that date")
    return resp.ok(ser.serialize_price_index_publication(best))


@bp.route("/price-index-publications/<pid>", methods=["GET"])
def get_publication(pid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    p = db.price_index_publications.get(pid)
    if p is None:
        raise err_not_found()
    return resp.ok(ser.serialize_price_index_publication(p))


@bp.route("/price-index-publications", methods=["GET"])
def list_publications():
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    limit, offset = mw.pagination_params()
    index_name = mw.opt_query_enum("index_name", INDEX_NAMES)
    effective_date = mw.opt_query_string("effective_date")
    items = list(db.price_index_publications.values())
    if index_name is not None:
        items = [p for p in items if p["index_name"] == index_name]
    if effective_date is not None:
        items = [p for p in items if p["effective_date"].isoformat() == effective_date]
    items.sort(key=lambda p: p["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_price_index_publication(p) for p in page], limit, offset, total)
