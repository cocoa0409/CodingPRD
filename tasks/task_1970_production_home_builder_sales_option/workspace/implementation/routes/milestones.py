"""ConstructionMilestone endpoints: list / get / complete (PRD section 3.6)."""

import db
from constants import READ_ROLES, ROLE_BUYER
from errors import (
    ApiError,
    ERR_MILESTONE_NOT_FOUND,
    ERR_MILESTONE_ALREADY_COMPLETE,
    ERR_MILESTONE_OUT_OF_ORDER,
    ERR_AGREEMENT_INVALID_STATE,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import ser_milestone, complete_milestone, milestones_of
from util import (
    require_fk,
    pagination_params,
    paginate,
    apply_filters,
)

bp = make_blueprint("milestones")


@bp.get("/milestones")
def list_milestones():
    user_id, role = authenticate(READ_ROLES)
    limit, offset = pagination_params()
    # The milestone list orders by construction sequence, not creation time.
    items = sorted(db.all_of("milestones"), key=lambda m: (m["sequence_no"], m["_seq"]))
    if role == ROLE_BUYER:
        items = [
            m for m in items
            if (db.get("agreements", m["agreement_id"]) or {}).get("buyer_id") == user_id
        ]
    items = apply_filters(items, ["agreement_id", "stage", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_milestone(m) for m in page], limit, offset, total, has_more)


@bp.get("/milestones/<mid>")
def get_milestone(mid):
    authenticate(READ_ROLES)
    milestone = require_fk("milestones", mid, ERR_MILESTONE_NOT_FOUND, "milestone")
    return success_obj(ser_milestone(milestone), 200)


@bp.post("/milestones/<mid>/complete")
def complete(mid):
    authenticate(["ConstructionManager"])
    milestone = require_fk("milestones", mid, ERR_MILESTONE_NOT_FOUND, "milestone")
    # State tier (scaffold order): repeat completion, sequence order, then the
    # agreement's state.
    if milestone["status"] != "NOT_STARTED":
        raise ApiError(ERR_MILESTONE_ALREADY_COMPLETE, 409, "milestone is already COMPLETE")
    peers = milestones_of(milestone["agreement_id"])
    if any(p["sequence_no"] < milestone["sequence_no"] and p["status"] != "COMPLETE" for p in peers):
        raise ApiError(ERR_MILESTONE_OUT_OF_ORDER, 409, "a lower-sequence milestone is not COMPLETE")
    agreement = db.get("agreements", milestone["agreement_id"])
    if agreement["status"] not in ("PENDING_CONTINGENCIES", "CONTINGENCIES_CLEARED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, 409, "agreement is not under construction")
    complete_milestone(milestone, db.now())
    return success_obj(ser_milestone(milestone), 200)
