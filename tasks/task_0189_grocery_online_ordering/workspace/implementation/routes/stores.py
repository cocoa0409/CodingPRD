"""Store endpoints (PRD §3.1, SCAFFOLD §1.5)."""
from flask import Blueprint

import db
from errors import err, ERR_STORE_NOT_FOUND, ERR_INVALID_ORDER_STATE
from middleware import get_user_context, require_role
import validate as V
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("stores", __name__)


def _serialize(store):
    return public(store)


@bp.route("/v1/stores", methods=["POST"])
def create_store():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin"})  # PRD §4: PlatformAdmin only
    body = V.get_body()
    name = V.require_str(body, "name")
    timezone = V.opt_str(body, "timezone", "UTC")          # default UTC (PRD §3.1)
    ebt_enabled = V.require_bool(body, "ebt_enabled", True)  # default true
    cold_chain = V.opt_int(body, "cold_chain_hold_minutes", 120, minimum=0)  # default 120
    with db.lock:
        store = {
            "name": name,
            "timezone": timezone,
            "ebt_enabled": ebt_enabled,
            "cold_chain_hold_minutes": cold_chain,
            "status": "ACTIVE",  # PRD §3.1: a store begins ACTIVE
        }
        db.stamp_create(store)
        db.stores[store["id"]] = store
        return object_response(_serialize(store), 201)


@bp.route("/v1/stores", methods=["GET"])
def list_stores():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})
    limit, offset = get_pagination()
    with db.lock:
        page, total = paginate(list(db.stores.values()), limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})
    with db.lock:
        store = db.stores.get(store_id)
        if store is None:
            err(ERR_STORE_NOT_FOUND, "Store not found")
        return object_response(_serialize(store))


@bp.route("/v1/stores/<store_id>/close", methods=["POST"])
def close_store(store_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin"})  # PRD §4: PlatformAdmin only
    with db.lock:
        store = db.stores.get(store_id)
        if store is None:
            err(ERR_STORE_NOT_FOUND, "Store not found")
        if store["status"] != "ACTIVE":
            err(ERR_INVALID_ORDER_STATE, "Store is not ACTIVE")
        store["status"] = "CLOSED"
        db.touch(store)
        return object_response(_serialize(store))
