"""Homebuyer and CustomerCareRep registries (PRD §3.1)."""
from flask import Blueprint

import db
from db import homebuyers, reps
from errors import err_duplicate_email
from middleware import ROLE_MANAGER, require_roles
from response import success_object
from validation import json_body, opt_bool, opt_int, opt_str, req_str

bp = Blueprint("registries", __name__)


@bp.post("/api/homebuyers")
def create_homebuyer():
    require_roles(ROLE_MANAGER)
    body = json_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    phone = opt_str(body, "phone")
    if any(b["email"] == email for b in homebuyers.values()):
        raise err_duplicate_email("A homebuyer with email %s already exists." % email)
    rec = db.stamp({
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "phone": phone,
    })
    homebuyers[rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.post("/api/reps")
def create_rep():
    require_roles(ROLE_MANAGER)
    body = json_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    active = opt_bool(body, "active")
    capacity = opt_int(body, "daily_visit_capacity_minutes")
    if any(r["email"] == email for r in reps.values()):
        raise err_duplicate_email("A representative with email %s already exists." % email)
    rec = db.stamp({
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "active": True if active is None else active,
        "daily_visit_capacity_minutes": 240 if capacity is None else capacity,
    })
    reps[rec["id"]] = rec
    return success_object(db.public(rec), status=201)
