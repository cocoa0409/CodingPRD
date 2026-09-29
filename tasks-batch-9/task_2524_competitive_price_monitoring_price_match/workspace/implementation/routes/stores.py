"""Store endpoints (PRD 3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import ALL_ROLES, PLATFORM_ADMIN, body, endpoint
from response import object_response
from routes.common import FK_MARKET, filtered, list_page, path_lookup, resolve_fks
from services import serialize
from util import as_int, as_str, get_required

bp = Blueprint("stores", __name__)


@bp.post("/stores")
@endpoint([PLATFORM_ADMIN])
def create_store(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_MARKET])

    market = fks["market_id"]
    if market is None:
        get_required(payload, "market_id")
    store_code = as_str(get_required(payload, "store_code"), "store_code", min_len=1)
    override_authority_cents = as_int(
        get_required(payload, "override_authority_cents"),
        "override_authority_cents", minimum=0)
    capacity = as_int(get_required(payload, "label_printer_capacity_per_day"),
                      "label_printer_capacity_per_day", gt=0)

    for existing in db.stores.values():
        if (existing["market_id"] == market["id"]
                and existing["store_code"] == store_code):
            raise err("ERR_DUPLICATE_RESOURCE",
                      "store_code '%s' is already used in this market." % store_code)

    record = db.new_record()
    record.update({
        "market_id": market["id"],
        "store_code": store_code,
        "override_authority_cents": override_authority_cents,
        "label_printer_capacity_per_day": capacity,
    })
    db.stores[record["id"]] = record
    return object_response(serialize.store(record), 201)


@bp.get("/stores/<store_id>")
@endpoint(ALL_ROLES)
def read_store(user_id, role, store_id):
    store = path_lookup("stores", store_id, "ERR_STORE_NOT_FOUND")
    return object_response(serialize.store(store))


@bp.get("/stores")
@endpoint(ALL_ROLES)
def list_stores(user_id, role):
    rows = filtered(db.ordered(db.stores), request.args,
                    [("market_id", "market_id")])
    return list_page(rows, serialize.store)
