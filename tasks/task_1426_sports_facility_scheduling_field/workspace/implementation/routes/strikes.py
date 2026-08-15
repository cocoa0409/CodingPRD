"""Strike record routes: list, read, rescind (PRD 3.1)."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("strikes", __name__)


@bp.get("/strike-records")
def list_strikes():
    require_roles(*ANY_ROLE)
    items = list(store.strike_records.values())
    for param in ("organization_id", "permit_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [s for s in items if s.get(param) == val]
    return util.paginate(items)


@bp.get("/strike-records/<sid>")
def get_strike(sid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_strike(sid))


@bp.post("/strike-records/<sid>/rescind")
def rescind_strike(sid):
    require_roles("AthleticsAdmin")
    strike = core.get_strike(sid)
    if strike["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_STRIKE_STATE,
                              "Strike is already RESCINDED", 409)
    strike["status"] = "RESCINDED"
    # StrikeRecord is the immutable exception to the common-fields contract:
    # no updated_at / version (PRD 2.5).

    org = core.get_organization(strike["organization_id"])
    core.recompute_org_strikes(org)
    core.reevaluate_standing(org)
    return success_object(strike)
