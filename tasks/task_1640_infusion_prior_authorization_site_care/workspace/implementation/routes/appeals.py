"""Appeals: open on DENIED requests, decisions per level, escalations (PRD 3.5)."""
from flask import Blueprint

from db import db, next_seq, touch
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_OPEN_APPEAL,
    ERR_APPEAL_WINDOW_CLOSED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_request, get_appeal, list_response
from serializers import serialize
from services.transitions import cascade_appeal_closed
from util import new_id, CLOCK
from validate import get_body, req_str, req_enum

bp = Blueprint("appeals", __name__)

APPEAL_ROLES = ["AuthCoordinator", "MedicalDirector"]
CLOSED_APPEAL_STATES = {"CLOSED_UPHELD", "CLOSED_OVERTURNED"}


@bp.post("/infusion/authorization-requests/<rid>/appeals")
def create_appeal(rid):
    authorized(["AuthCoordinator"])
    body = get_body()
    reason = req_str(body, "reason")

    req = get_request(rid)
    if req["status"] != "DENIED":
        raise_error(ERR_INVALID_STATE,
                    f"appeals may only be opened on a DENIED request, found {req['status']}")
    # at most one open appeal per request
    for existing in db["appeals"].values():
        if (existing["authorization_request_id"] == req["id"]
                and existing["status"] not in CLOSED_APPEAL_STATES):
            raise_error(ERR_DUPLICATE_OPEN_APPEAL,
                        "an open appeal already exists for this request")
    # appeal window: now <= appeal_deadline
    now = CLOCK.now()
    if req["appeal_deadline"] is not None and now > req["appeal_deadline"]:
        raise_error(ERR_APPEAL_WINDOW_CLOSED,
                    "the appeal window closed at the request's appeal_deadline")

    rec = {
        "id": new_id(),
        "authorization_request_id": req["id"],
        "reason": reason,
        "status": "LEVEL_1",
        "decided_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["appeals"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests/<rid>/appeals")
def list_appeals(rid):
    authorized(APPEAL_ROLES)
    get_request(rid)
    items = [a for a in db["appeals"].values() if a["authorization_request_id"] == rid]
    return list_response(items)


@bp.get("/infusion/appeals/<aid>")
def read_appeal(aid):
    authorized(APPEAL_ROLES)
    return success_object(serialize(get_appeal(aid)))


@bp.post("/infusion/appeals/<aid>/decisions")
def decide_appeal(aid):
    caller = authorized(["MedicalDirector"])
    body = get_body()
    outcome = req_enum(body, "outcome", ["UPHELD", "OVERTURNED"])

    appeal = get_appeal(aid)
    now = CLOCK.now()
    status = appeal["status"]

    if status == "LEVEL_1":
        if outcome == "UPHELD":
            appeal["status"] = "LEVEL_1_DECIDED"
            closed = None
        else:
            appeal["status"] = "CLOSED_OVERTURNED"
            closed = "CLOSED_OVERTURNED"
    elif status == "LEVEL_2":
        if outcome == "UPHELD":
            appeal["status"] = "LEVEL_2_DECIDED"
            closed = None
        else:
            appeal["status"] = "CLOSED_OVERTURNED"
            closed = "CLOSED_OVERTURNED"
    elif status == "EXTERNAL_REVIEW":
        if outcome == "UPHELD":
            appeal["status"] = "CLOSED_UPHELD"
            closed = "CLOSED_UPHELD"
        else:
            appeal["status"] = "CLOSED_OVERTURNED"
            closed = "CLOSED_OVERTURNED"
    else:
        raise_error(ERR_INVALID_STATE,
                    f"appeal in {status} cannot be decided")

    appeal["decided_by_user_id"] = caller.user_id
    touch(appeal, now)
    if closed is not None:
        cascade_appeal_closed(appeal, closed, now)
    return success_object(serialize(appeal))


@bp.post("/infusion/appeals/<aid>/escalations")
def escalate_appeal(aid):
    authorized(["AuthCoordinator"])
    get_body()
    appeal = get_appeal(aid)
    if appeal["status"] == "LEVEL_1_DECIDED":
        appeal["status"] = "LEVEL_2"
    elif appeal["status"] == "LEVEL_2_DECIDED":
        appeal["status"] = "EXTERNAL_REVIEW"
    else:
        raise_error(ERR_INVALID_STATE,
                    f"appeal in {appeal['status']} cannot be escalated")
    touch(appeal, CLOCK.now())
    return success_object(serialize(appeal))
