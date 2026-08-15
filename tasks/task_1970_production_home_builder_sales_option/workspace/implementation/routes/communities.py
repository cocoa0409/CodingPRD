"""Community endpoints: create / get / open-sales (PRD section 3.1)."""

import db
from constants import READ_ROLES
from errors import (
    ApiError,
    ERR_COMMUNITY_NOT_FOUND,
    ERR_COMMUNITY_INVALID_STATE,
)
from middleware import authenticate
from response import success_obj
from routes import make_blueprint
from services import ser_community
from util import body_json, check_shape, require_fk

bp = make_blueprint("communities")

CREATE_SPEC = {
    "name": {"type": "string", "required": True},
    "incentive_budget_total_cents": {"type": "integer", "required": True, "min": 0},
}


@bp.post("/communities")
def create_community():
    authenticate(["SalesDirector"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    community = db.new_entity("communities", {
        "name": body["name"],
        "incentive_budget_total_cents": body["incentive_budget_total_cents"],
        "status": "SETUP",
    })
    return success_obj(ser_community(community), 201)


@bp.get("/communities/<cid>")
def get_community(cid):
    authenticate(READ_ROLES)
    community = require_fk("communities", cid, ERR_COMMUNITY_NOT_FOUND, "community")
    return success_obj(ser_community(community), 200)


@bp.post("/communities/<cid>/open-sales")
def open_sales(cid):
    authenticate(["SalesDirector"])
    community = require_fk("communities", cid, ERR_COMMUNITY_NOT_FOUND, "community")
    if community["status"] != "SETUP":
        raise ApiError(ERR_COMMUNITY_INVALID_STATE, 409, "open-sales requires SETUP")
    community["status"] = "SELLING"
    db.touch(community)
    return success_obj(ser_community(community), 200)
