"""OperatorTruck endpoints (PRD §3.1)."""

from flask import request, Blueprint

import serializers
from db import db
from helpers import get_body, require_str, require_fk, require_state_code, get_pagination, paginate
from lookups import get_truck, get_commissary
from middleware import require_user_context, require_role
from response import ok_object, ok_array

bp = Blueprint("trucks", __name__)

WRITE_ROLES = {"Dispatcher", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}


@bp.post("/trucks")
def create_truck():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    commissary_id = require_fk(body, "commissary_id")
    get_commissary(commissary_id)
    name = require_str(body, "name")
    home_state_code = require_state_code(body, "home_state_code")
    rec = db.new_record({
        "commissary_id": commissary_id,
        "name": name,
        "home_state_code": home_state_code,
        "operability": "GROUNDED",
        "propane_psi": 0,
        "generator_runtime_hours": 0,
        "gross_sales_cents": 0,
    })
    db.trucks[rec["id"]] = rec
    return ok_object(serializers.truck(rec), 201)


@bp.get("/trucks")
def list_trucks():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.trucks.values())
    commissary_id = request.args.get("commissary_id")
    if commissary_id is not None:
        records = [r for r in records if r["commissary_id"] == commissary_id]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.truck(r) for r in window], limit, offset, total)


@bp.get("/trucks/<truck_id>")
def get_truck_route(truck_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_truck(truck_id)
    return ok_object(serializers.truck(rec))
