"""Store endpoints (PRD §3.1)."""
from flask import Blueprint

from db import DB
from middleware import auth_context, require_role
from common import stamp_create, get_json_body, as_int, as_str
from response import success
from errors import err, ERR_NOT_FOUND, ERR_DUPLICATE_RESOURCE
from services.posture import store_view

bp = Blueprint("stores", __name__)


@bp.route("/stores", methods=["POST"])
def create_store():
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    body = get_json_body()
    name = as_str(body, "name")
    code = as_str(body, "code")
    # tax_rate_bps in 0..2000 inclusive (PRD §3.1)
    tax_rate_bps = as_int(body, "tax_rate_bps", minimum=0, maximum=2000)
    # loyalty_earn_rate_bps defaults 100, may not be negative (PRD §3.1)
    loyalty_earn_rate_bps = as_int(body, "loyalty_earn_rate_bps", required=False,
                                   default=100, minimum=0)

    with DB.lock:
        for s in DB.stores.values():
            if s["code"] == code:
                raise err(ERR_DUPLICATE_RESOURCE, "Store code already exists")
        store = {
            "name": name,
            "code": code,
            "tax_rate_bps": tax_rate_bps,
            "loyalty_earn_rate_bps": loyalty_earn_rate_bps,
        }
        stamp_create(store)
        DB.stores[store["id"]] = store
        return success(store_view(DB, store), status=201)


@bp.route("/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "InventoryClerk", "Customer"})
    with DB.lock:
        store = DB.stores.get(store_id)
        if store is None:
            raise err(ERR_NOT_FOUND, "Store not found")
        return success(store_view(DB, store))
