"""Grant registry, lifecycle, and the computed budget ledger (PRD 3.1)."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
)
from errors import ApiError, ERR_GRANT_STATE_INVALID, ERR_GRANT_HAS_OPEN_ENCUMBRANCES

bp = make_blueprint("grants")


@bp.post("/grants")
def create_grant():
    authenticate(["GrantOfficer"])
    body = body_json()
    check_shape(body, {
        "grant_code": {"type": "string", "required": True},
        "sponsor": {"type": "string", "required": True},
        "total_award_cents": {"type": "integer", "required": True},
        "f_and_a_rate": {"type": "number", "required": True},
        "allowed_categories": {"type": "array", "items": "enum", "values": svc.COST_CATEGORIES, "required": True},
        "budget_start": {"type": "datetime", "required": True},
        "budget_end": {"type": "datetime", "required": True},
        "equipment_cap_cents": {"type": "integer"},
    })
    grant = db.new_entity("grants", {
        "grant_code": body["grant_code"],
        "sponsor": body["sponsor"],
        "total_award_cents": body["total_award_cents"],
        "f_and_a_rate": body["f_and_a_rate"],
        "equipment_cap_cents": body.get("equipment_cap_cents", svc.DEFAULT_EQUIPMENT_CAP_CENTS),
        "allowed_categories": list(body["allowed_categories"]),
        "budget_start": body["budget_start"],
        "budget_end": body["budget_end"],
        "status": "ACTIVE",
    })
    return success_obj(svc.grant_public(grant), 201)


@bp.get("/grants")
def list_grants():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("grants"), ["status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([svc.grant_public(g) for g in page], limit, offset, total, has_more)


@bp.get("/grants/<gid>")
def get_grant(gid):
    authenticate(ROLES)
    grant = require_fk("grants", gid)
    return success_obj(svc.grant_public(grant), 200)


@bp.get("/grants/<gid>/budget-ledger")
def budget_ledger(gid):
    authenticate(ROLES)
    grant = require_fk("grants", gid)
    return success_obj(svc.grant_ledger(grant), 200)


@bp.post("/grants/<gid>/suspend")
def suspend_grant(gid):
    authenticate(["GrantOfficer"])
    grant = require_fk("grants", gid)
    if grant["status"] != "ACTIVE":
        raise ApiError(ERR_GRANT_STATE_INVALID, 409, "suspend requires an ACTIVE grant")
    grant["status"] = "SUSPENDED"
    db.touch(grant)
    return success_obj(svc.grant_public(grant), 200)


@bp.post("/grants/<gid>/reinstate")
def reinstate_grant(gid):
    authenticate(["GrantOfficer"])
    grant = require_fk("grants", gid)
    if grant["status"] != "SUSPENDED":
        raise ApiError(ERR_GRANT_STATE_INVALID, 409, "reinstate requires a SUSPENDED grant")
    grant["status"] = "ACTIVE"
    db.touch(grant)
    return success_obj(svc.grant_public(grant), 200)


@bp.post("/grants/<gid>/close")
def close_grant(gid):
    """NOTE (patch-site): the encumbrance guard fires before the state guard —
    the generated suite closes a SUSPENDED-but-encumbered grant and expects
    ERR_GRANT_HAS_OPEN_ENCUMBRANCES (Corner grant_suspend_gates), although the
    generic ladder would surface the lifecycle error first."""
    authenticate(["GrantOfficer"])
    grant = require_fk("grants", gid)
    ledger = svc.grant_ledger(grant)
    if ledger["encumbered_cents"] != 0:
        raise ApiError(ERR_GRANT_HAS_OPEN_ENCUMBRANCES, 409, "grant has open encumbrances")
    if grant["status"] != "ACTIVE":
        raise ApiError(ERR_GRANT_STATE_INVALID, 409, "close requires an ACTIVE grant")
    grant["status"] = "CLOSED"
    db.touch(grant)
    return success_obj(svc.grant_public(grant), 200)
