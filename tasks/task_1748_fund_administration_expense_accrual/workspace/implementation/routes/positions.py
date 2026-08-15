"""Position endpoints: open, get, list."""
from flask import Blueprint

import db
from db import store
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services.navmath import D
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("positions", __name__)

POSITION_SCHEMA = {
    "share_class_id": ("string", True, None),
    "security_id": ("string", True, None),
    "quantity": ("posnumber", True, None),
    "cost_basis_total": ("number", True, None),
    "opened_date": ("date", True, None),
}


@bp.post("/positions")
def create_position():
    get_context()
    require_roles(["FundAccountant"])
    body = parse_body(POSITION_SCHEMA)
    cls = require_fk(store.share_classes, body["share_class_id"], "share_class_id")
    security = require_fk(store.securities, body["security_id"], "security_id")
    position = {
        "id": db.new_id(),
        "share_class_id": cls["id"],
        "security_id": security["id"],
        "quantity": D(body["quantity"]),
        "cost_basis_total": D(body["cost_basis_total"]),
        "opened_date": body["opened_date"],
        "status": "OPEN",
    }
    db.new_common(position)
    store.positions[position["id"]] = position
    return created(position)


@bp.get("/positions/<position_id>")
def get_position(position_id):
    get_context()
    position = require_path_entity(store.positions, position_id)
    require_roles(ALL_ROLES)
    return ok(position)


@bp.get("/positions")
def list_positions():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.positions.values())
    rows = filter_arg(rows, "share_class_id")
    rows = filter_arg(rows, "security_id")
    rows = filter_arg(rows, "status")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)
