"""Customer, Truck, Crew routes (PRD §3.1).

Customer.email unique (ERR_DUPLICATE_EMAIL); Truck.plate unique
(ERR_DUPLICATE_PLATE). Crew.head_count >= 2; Truck.capacity_cubic_feet > 0.
"""
from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common

bp = Blueprint("fleet", __name__)


# ---------------------------------------------------------------- Customers
@bp.route("/customers", methods=["POST"])
def create_customer():
    user_id, role = authenticate()
    require_roles(role, {"PlatformAdmin", "Customer"})
    body = common.get_json_body()
    common.require_fields(body, ["email", "full_name", "origin_state_code", "phone"])

    email = body["email"]
    if not isinstance(email, str) or email == "":
        raise err("ERR_INVALID_FIELD", "email must be a non-empty string.")
    # Uniqueness (PRD §3.1 -> ERR_DUPLICATE_EMAIL).
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "A customer with this email already exists.")

    record = db.new_common({
        "email": email,
        "full_name": body["full_name"],
        "origin_state_code": body["origin_state_code"],
        "phone": body["phone"],
    })
    db.customers[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = authenticate()
    require_roles(role, {"PlatformAdmin", "Customer", "Estimator", "Dispatcher", "ClaimsAdjuster"})
    record = common.lookup(db.customers, cid)
    return object_response(public(record), 200)


# ---------------------------------------------------------------- Trucks
@bp.route("/trucks", methods=["POST"])
def create_truck():
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin"})
    body = common.get_json_body()
    common.require_fields(body, ["plate", "capacity_cubic_feet", "home_state_code"])

    plate = body["plate"]
    if not isinstance(plate, str) or plate == "":
        raise err("ERR_INVALID_FIELD", "plate must be a non-empty string.")
    common.require_int_field(body, "capacity_cubic_feet")
    if body["capacity_cubic_feet"] <= 0:
        raise err("ERR_INVALID_FIELD", "capacity_cubic_feet must be > 0.")
    # Uniqueness (PRD §3.1 -> ERR_DUPLICATE_PLATE).
    for t in db.trucks.values():
        if t["plate"] == plate:
            raise err("ERR_DUPLICATE_PLATE", "A truck with this plate already exists.")

    record = db.new_common({
        "plate": plate,
        "capacity_cubic_feet": body["capacity_cubic_feet"],
        "home_state_code": body["home_state_code"],
    })
    db.trucks[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/trucks/<tid>", methods=["GET"])
def get_truck(tid):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin"})
    record = common.lookup(db.trucks, tid)
    return object_response(public(record), 200)


# ---------------------------------------------------------------- Crews
@bp.route("/crews", methods=["POST"])
def create_crew():
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin"})
    body = common.get_json_body()
    common.require_fields(body, ["name", "head_count", "home_state_code"])

    common.require_int_field(body, "head_count")
    if body["head_count"] < 2:
        raise err("ERR_INVALID_FIELD", "head_count must be >= 2.")

    record = db.new_common({
        "name": body["name"],
        "head_count": body["head_count"],
        "home_state_code": body["home_state_code"],
    })
    db.crews[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin"})
    record = common.lookup(db.crews, cid)
    return object_response(public(record), 200)
