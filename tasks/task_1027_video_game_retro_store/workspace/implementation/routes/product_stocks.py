from flask import Blueprint

import store
from common import authorize, require_found, parse_pagination, paginate
from envelope import object_response, array_response
from errors import err

bp = Blueprint("product_stocks", __name__)


@bp.get("/product-stocks/<sid>")
def get_stock(sid):
    authorize(["Member", "Clerk", "Manager"])
    s = require_found(store.product_stocks, sid)
    return object_response(store.serialize(s), 200)


@bp.post("/product-stocks/<sid>/release")
def release_stock(sid):
    authorize(["Manager"])
    s = require_found(store.product_stocks, sid)
    if s["release_state"] != "EMBARGOED":
        raise err("ERR_INVALID_STATE", "Pool is not EMBARGOED")
    s["release_state"] = "RELEASED"
    store.touch(s)
    return object_response(store.serialize(s), 200)


@bp.get("/product-stocks/<sid>/allocations")
def list_stock_allocations(sid):
    authorize(["Clerk", "Manager"])
    require_found(store.product_stocks, sid)
    limit, offset = parse_pagination()
    matching = [a for a in store.allocations.values() if a["product_stock_id"] == sid]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(a) for a in window], limit, offset, total)
