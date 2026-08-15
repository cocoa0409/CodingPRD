"""Store endpoints."""

from flask import Blueprint

from db import db
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import body, req_string, get_or_404
from services.entities import make_store, pub, touch
from errors import err409, ERR_DUPLICATE_STORE_NUMBER, ERR_INVALID_STATE_TRANSITION, ERR_PERIOD_LOCKED

bp = Blueprint("stores", __name__)


@bp.route("/stores", methods=["POST"])
def create_store():
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    data = body()
    store_number = req_string(data, "store_number")
    name = req_string(data, "name")
    region_code = req_string(data, "region_code")
    for s in db.stores.values():
        if s["store_number"] == store_number:
            raise err409(ERR_DUPLICATE_STORE_NUMBER,
                         "store_number %s already exists" % store_number)
    store = make_store(store_number, name, region_code)
    db.stores[store["id"]] = store
    return success_object(pub(store), status=201)


@bp.route("/stores", methods=["GET"])
def list_stores():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    region_code = _opt_query("region_code")
    status = _opt_query("status")
    items = sorted(db.stores.values(), key=lambda s: (s["created_at"], s["id"]))
    if region_code is not None:
        items = [s for s in items if s["region_code"] == region_code]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(s) for s in page], limit, offset, total)


@bp.route("/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    store = get_or_404(db.stores, store_id, "store")
    return success_object(pub(store))


@bp.route("/stores/<store_id>/close", methods=["POST"])
def close_store(store_id):
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    store = get_or_404(db.stores, store_id, "store")
    if store["status"] != "ACTIVE":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Store must be ACTIVE to close")
    for p in db.shrink_periods.values():
        if p["store_id"] == store_id and p["status"] in ("OPEN", "COUNTED"):
            raise err409(ERR_PERIOD_LOCKED,
                         "Store has a shrink period in OPEN or COUNTED status")
    store["status"] = "CLOSED"
    touch(store)
    return success_object(pub(store))


def _opt_query(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None
