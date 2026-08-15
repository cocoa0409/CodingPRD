"""District endpoints (PRD section 3.1)."""

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk

bp = make_blueprint("districts")


@bp.post("/districts")
def create_district():
    authenticate(["PlatformAdmin"])
    body = body_json()
    check_shape(body, {
        "district_code": {"type": "string", "required": True},
        "state_code": {"type": "state_code", "required": True},
        "funding_rate_cents": {"type": "integer", "required": True, "min": 1},
        "enrollment_cap": {"type": "integer", "required": True, "min": 0},
    })
    # district_code is unique across all districts and immutable.
    for d in db.all_of("districts"):
        if d["district_code"] == body["district_code"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, "district_code must be unique across all districts")
    district = db.new_entity("districts", {
        "district_code": body["district_code"],
        "state_code": body["state_code"],
        "funding_rate_cents": body["funding_rate_cents"],
        "enrollment_cap": body["enrollment_cap"],
    })
    return success_obj(db.public(district), 201)


@bp.get("/districts/<did>")
def get_district(did):
    authenticate(ALL_ROLES)
    district = require_fk("districts", did, "district")
    return success_obj(db.public(district), 200)


@bp.get("/districts")
def list_districts():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("districts"), ["state_code"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(d) for d in page], limit, offset, total, has_more)
