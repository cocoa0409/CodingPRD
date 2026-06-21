"""Customers and Technicians routes (PRD §3.2)."""
from flask import Blueprint

import db
import errors
import lookup
import serialize
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("people", __name__)

SKILL_LEVELS = {"APPRENTICE", "CERTIFIED", "MASTER"}
TECH_STATUSES = {"AVAILABLE", "ON_LEAVE"}


# ----- Customers -----
@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["full_name", "email", "service_address"])
    full_name = util.require_string(body, "full_name")
    email = util.require_string(body, "email")
    service_address = util.require_string(body, "service_address")
    time_zone = util.optional_string(body, "time_zone", "America/Los_Angeles")
    # email unique among customers (PRD §2.7)
    for c in db.customers.values():
        if c["email"] == email:
            raise errors.err(errors.ERR_DUPLICATE, "email already exists")
    c = {
        "full_name": full_name, "email": email,
        "service_address": service_address, "time_zone": time_zone,
    }
    db.stamp_create(c, common_fields=True, versioned=True)
    db.customers[c["id"]] = c
    return success(serialize.customer(c), status=201)


@bp.route("/customers/<id>", methods=["GET"])
def get_customer(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer", "Dispatcher"])
    c = lookup.customer(id)
    return success(serialize.customer(c))


# ----- Technicians -----
@bp.route("/technicians", methods=["POST"])
def create_technician():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["display_name", "skill_level"])
    display_name = util.require_string(body, "display_name")
    skill_level = util.require_enum(body, "skill_level", SKILL_LEVELS)
    certified_for_install = util.optional_bool(body, "certified_for_install", False)
    t = {
        "display_name": display_name, "skill_level": skill_level,
        "certified_for_install": certified_for_install,
        "status": "AVAILABLE", "booked_minutes": 0,
    }
    db.stamp_create(t, common_fields=True, versioned=True)
    db.technicians[t["id"]] = t
    return success(serialize.technician(t), status=201)


@bp.route("/technicians/<id>", methods=["GET"])
def get_technician(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Dispatcher", "Technician"])
    t = lookup.technician(id)
    return success(serialize.technician(t))


@bp.route("/technicians/<id>/set-leave", methods=["POST"])
def set_leave(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    t = lookup.technician(id)
    body = util.get_body()
    util.require_fields(body, ["status"])
    status = util.require_enum(body, "status", TECH_STATUSES)
    t["status"] = status
    db.touch(t)
    return success(serialize.technician(t))
