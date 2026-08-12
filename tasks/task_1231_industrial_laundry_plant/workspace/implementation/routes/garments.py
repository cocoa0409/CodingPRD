"""Garment endpoints."""

from flask import Blueprint

import clock
import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_CHIP_TRACKING_DISABLED,
    ERR_DUPLICATE,
)
from response import success, list_response
from util import (
    PLANT_SIDE,
    authenticate,
    require_roles,
    body_json,
    field,
    path_get,
    ref_get,
    filter_eq,
)

bp = Blueprint("garments", __name__)


@bp.route("/garments/register", methods=["POST"])
def register_garment():
    data = body_json()
    customer_id = field(data, "customer_id", "s")
    category_id = field(data, "category_id", "s")
    chip_code = field(data, "chip_code", "s")
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    cust = ref_get(db.customers, customer_id)
    cat = ref_get(db.categories, category_id)
    if any(g["chip_code"] == chip_code for g in db.garments.values()):
        raise ApiError(ERR_DUPLICATE, 409, "chip_code must be globally unique")
    g = db.new_entity()
    g.update(
        {
            "customer_id": cust["id"],
            "category_id": cat["id"],
            "chip_code": chip_code,
            "state": "AT_CUSTOMER",
            "lost_at": None,
        }
    )
    db.garments[g["id"]] = g
    return success(g, 201)


@bp.route("/garments/<gid>", methods=["GET"])
def get_garment(gid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    return success(path_get(db.garments, gid))


@bp.route("/garments/<gid>/load-out", methods=["POST"])
def load_out_garment(gid):
    auth = authenticate()
    require_roles(auth, {"PlantOperator"})
    g = path_get(db.garments, gid)
    if g["state"] != "CLEAN_STOCK":
        raise ApiError(ERR_INVALID_STATE, 409, "Garment is not CLEAN_STOCK")
    g["state"] = "LOADED_OUT"
    db.touch(g)
    return success(g)


@bp.route("/garments/<gid>/mark-lost", methods=["POST"])
def mark_lost_garment(gid):
    auth = authenticate()
    require_roles(auth, {"CustomerServiceRep"})
    g = path_get(db.garments, gid)
    if g["state"] not in ("AT_CUSTOMER", "IN_TRANSIT_SOILED", "LOADED_OUT"):
        raise ApiError(ERR_INVALID_STATE, 409, "Garment state does not permit mark-lost")
    cust = db.customers.get(g["customer_id"])
    if not cust or not cust["chip_tracking_enabled"]:
        raise ApiError(ERR_CHIP_TRACKING_DISABLED, 422, "Customer does not have chip tracking enabled")
    g["state"] = "LOST"
    g["lost_at"] = clock.fmt(clock.now())
    db.touch(g)
    cat = db.categories.get(g["category_id"])
    db.lost_queue.append(
        {
            "id": db.next_seq(),
            "customer_id": cust["id"],
            "charge_cents": cat["replacement_cost_cents"] if cat else 0,
            "invoice_id": None,
        }
    )
    return success(g)


@bp.route("/garments", methods=["GET"])
def list_garments():
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    items = db.sorted_all(db.garments)
    items = filter_eq(items, "customer_id", "customer_id")
    items = filter_eq(items, "category_id", "category_id")
    items = filter_eq(items, "state", "state")
    items = filter_eq(items, "chip_code", "chip_code")
    return list_response(items)
