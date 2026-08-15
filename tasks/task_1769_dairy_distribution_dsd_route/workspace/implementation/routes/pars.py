"""StandingPar endpoints: OCC-guarded upsert with supersession, reads."""

from flask import Blueprint, request

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int,
    base_fields, paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_STORE_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_PAR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH, ERR_STALE_STORE_VERSION,
)
from serializers import serialize_par

bp = Blueprint("standing_pars", __name__)

PAR_DAYS = ["par_mon", "par_tue", "par_wed", "par_thu", "par_fri", "par_sat", "par_sun"]


def _owner_check(user_id, store):
    route = DB.routes.get(store["route_id"])
    if route is None or route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller does not own the store's route")


@bp.post("/dairy/stores/<storeId>/standing-pars")
def upsert_par(storeId):
    user_id, _role = require_role("DistributorOwner")
    store = DB.stores.get(storeId)
    if store is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    _owner_check(user_id, store)
    body = get_json_body()
    allowed = {"product_id", "expected_store_version"} | set(PAR_DAYS)
    check_unknown_fields(body, allowed)
    require_fields(body, ["product_id", "expected_store_version"])
    product = DB.products.get(body["product_id"])
    if product is None:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product id not found")
    expected = opt_int(body, "expected_store_version")
    pars = {}
    for f in PAR_DAYS:
        v = opt_int(body, f, ge=0)
        pars[f] = v if v is not None else 0
    if expected != store["version"]:
        raise err(ERR_STALE_STORE_VERSION, "expected_store_version does not match the store's current version")
    # Supersede the prior ACTIVE par for this (store, product) pair.
    for p in DB.standing_pars.values():
        if (p["store_id"] == store["id"] and p["product_id"] == product["id"]
                and p["status"] == "ACTIVE"):
            p["status"] = "SUPERSEDED"
            touch(p)
    p = base_fields()
    p.update({
        "store_id": store["id"],
        "product_id": product["id"],
        "status": "ACTIVE",
    })
    p.update(pars)
    DB.standing_pars[p["id"]] = p
    touch(store)  # the upsert increments the store's version by one
    return success_object(serialize_par(p), status=201)


@bp.get("/dairy/stores/<storeId>/standing-pars")
def list_store_pars(storeId):
    require_any()
    store = DB.stores.get(storeId)
    if store is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    items = [p for p in DB.standing_pars.values() if p["store_id"] == storeId]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_par(p) for p in page], limit, offset, total)


@bp.get("/dairy/products/<productId>/standing-pars")
def list_product_pars(productId):
    require_any()
    product = DB.products.get(productId)
    if product is None:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product id not found")
    items = [p for p in DB.standing_pars.values() if p["product_id"] == productId]
    items.sort(key=lambda p: p["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_par(p) for p in page], limit, offset, total)


@bp.get("/dairy/standing-pars/<parId>")
def get_par(parId):
    require_any()
    p = DB.standing_pars.get(parId)
    if p is None:
        raise err(ERR_PAR_NOT_FOUND, "StandingPar id not found")
    return success_object(serialize_par(p))
