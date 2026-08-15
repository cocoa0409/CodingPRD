"""ExceptionRequest endpoints: submit, vote (quorum), withdraw."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import STORE
from errors import (err, ERR_DUPLICATE_VOTE, ERR_INVALID_STATE,
                    ERR_SELF_ACTION_FORBIDDEN)
from middleware import require_roles, insider_owns
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           QUORUM)
from util import Body, fmt_ts

bp = Blueprint("exceptions", __name__)

READ_ROLES = ("Insider", "ComplianceOfficer", "CommitteeMember", "LegalAdmin")


@bp.post("/exception-requests")
def create_exception():
    require_roles("Insider")
    body = Body()
    person_id = body.get_str("covered_person_id")
    ticker = body.get_str("security_ticker")
    quantity = body.get_num("quantity", positive=True, max_dp=4)
    reason = body.get_str("hardship_reason")
    if person_id is not None:
        insider_owns(person_id)
        get_or_404("covered_persons", person_id, "covered person")
    body.flush()
    x = new_entity()
    window_end = STORE.clock + timedelta(days=5)
    x.update({
        "covered_person_id": person_id,
        "security_ticker": ticker,
        "quantity": quantity,
        "hardship_reason": reason,
        "status": "SUBMITTED",
        "votes_for": 0,
        "votes_against": 0,
        "voter_ids": [],
        "decision_window_end": fmt_ts(window_end),
        "decided_at": None,
        "_decision_window_end_dt": window_end,
        "_decided_dt": None,
        "_votes": [],
    })
    STORE.exception_requests[x["id"]] = x
    return success(serialize(x), 201)


@bp.get("/exception-requests/<xid>")
def get_exception(xid):
    require_roles(*READ_ROLES)
    x = get_or_404("exception_requests", xid, "exception request")
    insider_owns(x["covered_person_id"])
    return success(serialize(x))


@bp.get("/exception-requests")
def list_exceptions():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.exception_requests.values())
    person_id = request.args.get("covered_person_id")
    status = request.args.get("status")
    if person_id is not None:
        items = [x for x in items if x["covered_person_id"] == person_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate([serialize(x) for x in items])


@bp.post("/exception-requests/<xid>/vote")
def vote_exception(xid):
    require_roles("CommitteeMember")
    x = get_or_404("exception_requests", xid, "exception request")
    # Guards in order: state, segregation of duties, duplicate vote.
    if x["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED exception request can be voted on")
    if g.user_id == x["covered_person_id"]:
        raise err(ERR_SELF_ACTION_FORBIDDEN, "a member may not vote on their own exception request")
    if g.user_id in x["voter_ids"]:
        raise err(ERR_DUPLICATE_VOTE, "committee member has already voted on this request")
    body = Body()
    vote = body.get_enum("vote", {"APPROVE", "REJECT"})
    body.flush()
    x["voter_ids"].append(g.user_id)
    x["_votes"].append({"voter": g.user_id, "vote": vote})
    x["votes_for"] = sum(1 for v in x["_votes"] if v["vote"] == "APPROVE")
    x["votes_against"] = sum(1 for v in x["_votes"] if v["vote"] == "REJECT")
    if x["votes_for"] >= QUORUM:
        x["status"] = "APPROVED"
        x["decided_at"] = fmt_ts(STORE.clock)
        x["_decided_dt"] = STORE.clock
    elif x["votes_against"] >= QUORUM:
        x["status"] = "DENIED"
        x["decided_at"] = fmt_ts(STORE.clock)
        x["_decided_dt"] = STORE.clock
    touch(x)
    return success(serialize(x))


@bp.post("/exception-requests/<xid>/withdraw")
def withdraw_exception(xid):
    require_roles("Insider")
    x = get_or_404("exception_requests", xid, "exception request")
    insider_owns(x["covered_person_id"])
    if x["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED exception request can be withdrawn")
    x["status"] = "WITHDRAWN"
    touch(x)
    return success(serialize(x))


@bp.get("/exception-requests/<xid>/preclearance-requests")
def exception_preclearances(xid):
    require_roles(*READ_ROLES)
    x = get_or_404("exception_requests", xid, "exception request")
    insider_owns(x["covered_person_id"])
    items = [r for r in sort_created(STORE.preclearance_requests.values())
             if r["exception_id"] == xid]
    return paginate([serialize(r) for r in items])
