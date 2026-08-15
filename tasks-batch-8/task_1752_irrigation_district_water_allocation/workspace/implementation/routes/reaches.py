"""CanalReach endpoints: create, list, get."""
from flask import Blueprint

from db import store, new_id, new_common
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity

bp = Blueprint("reaches", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser", "DitchRider"]


@bp.post("/district/canal-reaches")
def create_reach():
    uid, role = get_context()
    body = parse_body({
        "name": ("string", True, None, None),
        "max_capacity_cfs": ("number", True, None, "gt0"),
    }, allow_empty=False)
    require_roles(["DistrictAdmin"])
    reach = new_common({
        "id": new_id(),
        "name": body["name"],
        "max_capacity_cfs": body["max_capacity_cfs"],
        "status": "IN_SERVICE",
    })
    store.canal_reaches[reach["id"]] = reach
    return created(reach)


@bp.get("/district/canal-reaches")
def list_reaches():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = filter_eq(list(store.canal_reaches.values()), "status")
    return list_ok(rows)


@bp.get("/district/canal-reaches/<rid>")
def get_reach(rid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.canal_reaches, rid))
