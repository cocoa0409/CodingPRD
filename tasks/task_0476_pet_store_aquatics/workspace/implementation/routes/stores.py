"""Store endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from db import stamp_create
from middleware import require_auth, require_role
from response import object_response, array_response
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int,
)
from services.serialize import store_out

bp = Blueprint("stores", __name__)

READ_ROLES = ["InventoryManager", "LivestockKeeper", "ClinicVet", "StoreClerk", "Customer"]


@bp.route("/stores", methods=["POST"])
def create_store():
    _, role = require_auth()
    require_role(role, ["InventoryManager"])
    body = get_body()
    name = as_str(require_present(body, "name"), "name")
    state_code = as_str(require_present(body, "state_code"), "state_code")
    lpvc = 1
    if "loyalty_point_value_cents" in body and body["loyalty_point_value_cents"] is not None:
        lpvc = as_int(body["loyalty_point_value_cents"], "loyalty_point_value_cents")
    record = {
        "name": name,
        "state_code": state_code,
        "loyalty_point_value_cents": lpvc,
        "status": "OPEN",
    }
    stamp_create(record)
    db.stores[record["id"]] = record
    return object_response(store_out(record), 201)


@bp.route("/stores", methods=["GET"])
def list_stores():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    page, total = paginate(list(db.stores.values()), limit, offset)
    return array_response([store_out(r) for r in page], limit, offset, total)


@bp.route("/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("stores", store_id)
    return object_response(store_out(record))
