from flask import Blueprint

from db import db, common_create_fields
from middleware import get_identity, require_role
from response import success
from services import serialize
from services.common import get_body, require_fields, as_str, as_int, get_route

bp = Blueprint("routes", __name__)


@bp.post("/routes")
def create_route():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["name"])
    name = as_str(body["name"], "name")
    buffer = 30
    if "travel_buffer_minutes" in body and body["travel_buffer_minutes"] is not None:
        buffer = as_int(body["travel_buffer_minutes"], "travel_buffer_minutes", minimum=0)
    r = common_create_fields()
    r.update({"name": name, "travel_buffer_minutes": buffer})
    db.routes[r["id"]] = r
    return success(serialize.route_view(r), 201)


@bp.get("/routes/<rid>")
def get_one_route(rid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    r = get_route(rid)
    return success(serialize.route_view(r), 200)
