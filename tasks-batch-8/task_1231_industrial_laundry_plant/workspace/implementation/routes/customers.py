"""Customer and CustomerParLevel endpoints."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_STATE
from response import success, list_response
from util import (
    ALL_ROLES,
    PLANT_SIDE,
    authenticate,
    require_roles,
    cc_owns,
    body_json,
    field,
    path_get,
    filter_eq,
)

bp = Blueprint("customers", __name__)

CUSTOMER_KINDS = ("HEALTHCARE", "HOSPITALITY")
BILLING_MODES = ("RENTAL", "COG")


@bp.route("/plants/<pid>/customers", methods=["POST"])
def create_customer(pid):
    data = body_json()
    name = field(data, "name", "s")
    kind = field(data, "customer_kind", "s", choices=CUSTOMER_KINDS)
    mode = field(data, "billing_mode", "s", choices=BILLING_MODES)
    chips = field(data, "chip_tracking_enabled", "b")
    limit = field(data, "credit_limit_cents", "i", minv=0)
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    plant = path_get(db.plants, pid)
    cust = db.new_entity()
    cust.update(
        {
            "plant_id": plant["id"],
            "name": name,
            "customer_kind": kind,
            "billing_mode": mode,
            "chip_tracking_enabled": chips,
            "credit_limit_cents": limit,
            "account_balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    db.customers[cust["id"]] = cust
    return success(cust, 201)


@bp.route("/plants/<pid>/customers", methods=["GET"])
def list_customers(pid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    plant = path_get(db.plants, pid)
    items = [c for c in db.sorted_all(db.customers) if c["plant_id"] == plant["id"]]
    items = filter_eq(items, "billing_mode", "billing_mode")
    items = filter_eq(items, "status", "status")
    return list_response(items)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    cust = path_get(db.customers, cid)
    cc_owns(auth, cust["id"])
    return success(cust)


@bp.route("/customers/<cid>/suspend", methods=["POST"])
def suspend_customer(cid):
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    cust = path_get(db.customers, cid)
    if cust["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Customer is not ACTIVE")
    cust["status"] = "SUSPENDED"
    db.touch(cust)
    return success(cust)


@bp.route("/customers/<cid>/resume", methods=["POST"])
def resume_customer(cid):
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    cust = path_get(db.customers, cid)
    if cust["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Customer is not SUSPENDED")
    cust["status"] = "ACTIVE"
    db.touch(cust)
    return success(cust)


@bp.route("/customers/<cid>/stops", methods=["GET"])
def list_customer_stops(cid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    cust = path_get(db.customers, cid)
    cc_owns(auth, cust["id"])
    items = [s for s in db.sorted_all(db.stops) if s["customer_id"] == cust["id"]]
    return list_response(items)


@bp.route("/customers/<cid>/garments", methods=["GET"])
def list_customer_garments(cid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    cust = path_get(db.customers, cid)
    cc_owns(auth, cust["id"])
    items = [g for g in db.sorted_all(db.garments) if g["customer_id"] == cust["id"]]
    items = filter_eq(items, "state", "state")
    return list_response(items)


@bp.route("/customers/<cid>/par-levels/<category_id>", methods=["PUT"])
def upsert_par_level(cid, category_id):
    data = body_json()
    par_pieces = field(data, "par_pieces", "i", minv=0)
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    cust = path_get(db.customers, cid)
    cat = path_get(db.categories, category_id)
    row = next(
        (
            p
            for p in db.par_levels.values()
            if p["customer_id"] == cust["id"] and p["category_id"] == cat["id"]
        ),
        None,
    )
    if row is None:
        row = db.new_entity()
        row.update(
            {
                "customer_id": cust["id"],
                "category_id": cat["id"],
                "par_pieces": par_pieces,
                "current_on_site_pieces": 0,
            }
        )
        db.par_levels[row["id"]] = row
    else:
        row["par_pieces"] = par_pieces
        db.touch(row)
    # Deliberately leaves Customer.version unchanged.
    return success(row)


@bp.route("/customers/<cid>/par-levels", methods=["GET"])
def list_par_levels(cid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    cust = path_get(db.customers, cid)
    cc_owns(auth, cust["id"])
    items = [p for p in db.sorted_all(db.par_levels) if p["customer_id"] == cust["id"]]
    return list_response(items)
