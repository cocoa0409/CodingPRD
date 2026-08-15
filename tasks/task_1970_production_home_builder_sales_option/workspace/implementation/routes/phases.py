"""PricePhase endpoints: create / community-scoped list (PRD section 3.1)."""

import db
from constants import READ_ROLES
from errors import (
    ApiError,
    ERR_COMMUNITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PHASE_WINDOW_OVERLAP,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import ser_phase, phases_of
from util import (
    body_json,
    check_shape,
    require_fk,
    parse_dt,
    pagination_params,
    paginate,
)

bp = make_blueprint("price_phases")

CREATE_SPEC = {
    "community_id": {"type": "string", "required": True},
    "phase_name": {"type": "string", "required": True},
    "uplift_pct": {"type": "number", "required": True},
    "effective_from": {"type": "datetime", "required": True},
    "effective_to": {"type": "datetime", "required": True},
}


@bp.post("/price-phases")
def create_phase():
    authenticate(["SalesDirector"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    from_dt = parse_dt(body["effective_from"], "effective_from")
    to_dt = parse_dt(body["effective_to"], "effective_to")
    # Malformed window (tier 3, before existence): end must be strictly after start.
    if not (to_dt > from_dt):
        raise ApiError(ERR_INVALID_REQUEST, 400, "effective_to must be strictly after effective_from")
    require_fk("communities", body["community_id"], ERR_COMMUNITY_NOT_FOUND, "community")
    # Half-open [from, to) windows may touch but never overlap within a community.
    for existing in phases_of(body["community_id"]):
        if from_dt < existing["_to_dt"] and existing["_from_dt"] < to_dt:
            raise ApiError(
                ERR_PHASE_WINDOW_OVERLAP,
                409,
                "price phase window overlaps an existing phase of the community",
            )
    phase = db.new_entity("price_phases", {
        "community_id": body["community_id"],
        "phase_name": body["phase_name"],
        "uplift_pct": body["uplift_pct"],
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "_from_dt": from_dt,
        "_to_dt": to_dt,
    })
    return success_obj(ser_phase(phase), 201)


@bp.get("/communities/<cid>/price-phases")
def list_phases(cid):
    authenticate(READ_ROLES)
    require_fk("communities", cid, ERR_COMMUNITY_NOT_FOUND, "community")
    limit, offset = pagination_params()
    items = phases_of(cid)
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_phase(p) for p in page], limit, offset, total, has_more)
