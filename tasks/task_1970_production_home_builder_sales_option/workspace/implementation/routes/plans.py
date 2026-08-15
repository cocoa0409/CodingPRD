"""HomePlan endpoints: create / community-scoped list (PRD section 3.1)."""

import db
from constants import READ_ROLES
from errors import (
    ApiError,
    ERR_COMMUNITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import ser_plan
from util import (
    body_json,
    check_shape,
    require_fk,
    pagination_params,
    paginate,
)

bp = make_blueprint("plans")

ELEVATION_SPEC = {
    "name": {"type": "string", "required": True},
    "price_cents": {"type": "integer", "required": True, "min": 0},
}

CREATE_SPEC = {
    "community_id": {"type": "string", "required": True},
    "plan_name": {"type": "string", "required": True},
    "base_price_cents": {"type": "integer", "required": True, "min": 1},
    "elevations": {"type": "array", "required": True, "items": ELEVATION_SPEC},
}


@bp.post("/plans")
def create_plan():
    authenticate(["SalesDirector"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    elevations = body["elevations"]
    if len(elevations) < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "elevations must contain at least one entry")
    names = [e["name"] for e in elevations]
    if len(set(names)) != len(names):
        raise ApiError(ERR_INVALID_REQUEST, 400, "elevation names must be unique within the plan")
    require_fk("communities", body["community_id"], ERR_COMMUNITY_NOT_FOUND, "community")
    plan = db.new_entity("plans", {
        "community_id": body["community_id"],
        "plan_name": body["plan_name"],
        "base_price_cents": body["base_price_cents"],
        "elevations": [{"name": e["name"], "price_cents": e["price_cents"]} for e in elevations],
    })
    return success_obj(ser_plan(plan), 201)


@bp.get("/communities/<cid>/plans")
def list_plans(cid):
    authenticate(READ_ROLES)
    require_fk("communities", cid, ERR_COMMUNITY_NOT_FOUND, "community")
    limit, offset = pagination_params()
    items = [p for p in db.all_of("plans") if p["community_id"] == cid]
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_plan(p) for p in page], limit, offset, total, has_more)
