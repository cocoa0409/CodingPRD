"""Meetings, quorum, ballots, elections (PRD §3.9)."""
from flask import request

import domain as D
from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_NOT_RESOURCE_OWNER,
    ERR_TEMPORAL_CONFLICT,
    ERR_CROSS_ENTITY_VIOLATION,
)
from middleware import ctx, require_role, ALL_ROLES
from response import ok, ok_list
from util import get_body, req_str, req_int, req_enum, req_dt, req_str_array, pagination
from routes.core import bp, list_response

READ_ALL = list(ALL_ROLES)
READ_BOARD = ["PlatformAdmin", "BoardOfficer", "BoardMember", "ManagingAgent"]


@bp.post("/cooperatives/<cid>/meetings")
def create_meeting(cid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    body = get_body()
    kind = req_enum(body, "meeting_kind", ["ANNUAL", "SPECIAL"])
    scheduled_at = req_dt(body, "scheduled_at")
    m = D.make(
        "meetings", coop,
        cooperative_id=cid,
        meeting_kind=kind,
        scheduled_at=scheduled_at,
        preparation_state="PREPARING",
        quorum_state="QUORUM_PENDING",
        shares_represented=0,
        meeting_status="SCHEDULED",
    )
    return ok(D.ser(m), 201)


@bp.get("/cooperatives/<cid>/meetings")
def list_meetings(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    return list_response("meetings", cid, [
        ("meeting_kind", request.args.get("meeting_kind"), False),
        ("meeting_status", request.args.get("meeting_status"), False),
    ])


@bp.get("/cooperatives/<cid>/meetings/<mid>")
def get_meeting(cid, mid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    m = D.get_scoped("meetings", mid, cid, "Meeting")
    return ok(D.ser(m))


@bp.post("/cooperatives/<cid>/meetings/<mid>/send-notice")
def send_notice(cid, mid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    m = D.get_scoped("meetings", mid, cid, "Meeting")
    if m["meeting_status"] in ("COMPLETED", "ADJOURNED_NO_QUORUM"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Meeting is in terminal state", 409)
    if m["preparation_state"] != "PREPARING":
        raise ApiError(ERR_INVALID_STATE, "Notice has already been sent", 409)
    m["preparation_state"] = "NOTICE_SENT"
    D.touch(m, coop)
    return ok(D.ser(m))


@bp.post("/cooperatives/<cid>/meetings/<mid>/open")
def open_meeting(cid, mid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    m = D.get_scoped("meetings", mid, cid, "Meeting")
    if m["meeting_status"] in ("COMPLETED", "ADJOURNED_NO_QUORUM"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Meeting is in terminal state", 409)
    if m["meeting_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Meeting is not SCHEDULED", 409)
    if m["preparation_state"] != "NOTICE_SENT":
        raise ApiError(ERR_INVALID_STATE, "Notice must be sent before opening", 409)
    if coop["current_utc"] < m["scheduled_at"]:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "Meeting scheduled_at has not been reached", 422)
    m["meeting_status"] = "IN_SESSION"
    D.touch(m, coop)
    D.recompute_meeting(coop, m)
    return ok(D.ser(m))


@bp.post("/cooperatives/<cid>/meetings/<mid>/close")
def close_meeting(cid, mid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    m = D.get_scoped("meetings", mid, cid, "Meeting")
    body = get_body()
    open_seats = req_int(body, "open_seats")
    if m["meeting_status"] in ("COMPLETED", "ADJOURNED_NO_QUORUM"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Meeting is in terminal state", 409)
    if m["meeting_status"] != "IN_SESSION":
        raise ApiError(ERR_INVALID_STATE, "Meeting is not IN_SESSION", 409)
    D.recompute_meeting(coop, m)
    if m["quorum_state"] == "QUORUM_MET":
        m["meeting_status"] = "COMPLETED"
        for b in STORE["ballots"].values():
            if b["meeting_id"] == mid and b["ballot_status"] == "SUBMITTED":
                b["ballot_status"] = "COUNTED"
                D.touch(b, coop)
        D.touch(m, coop)
        D.run_election_tally(coop, m, open_seats)
    else:
        D.adjourn_meeting(coop, m)
    return ok(D.ser(m))


# ---------------------------------------------------------------------------
# Ballots
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/meetings/<mid>/ballots")
def cast_ballot(cid, mid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    m = D.get_scoped("meetings", mid, cid, "Meeting")
    body = get_body()
    shareholder_id = req_str(body, "shareholder_id")
    ballot_kind = req_enum(body, "ballot_kind", ["IN_PERSON", "PROXY"])
    candidates = req_str_array(body, "candidate_user_ids")
    if uid != shareholder_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "X-User-ID must equal shareholder_id", 403)
    sh = STORE["shareholders"].get(shareholder_id)
    if sh is None or sh["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced shareholder does not exist", 422)
    if m["meeting_status"] in ("COMPLETED", "ADJOURNED_NO_QUORUM"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Meeting is in terminal state", 409)
    # Re-vote replaces: invalidate the shareholder's prior SUBMITTED ballot.
    for b in STORE["ballots"].values():
        if (
            b["meeting_id"] == mid
            and b["shareholder_id"] == shareholder_id
            and b["ballot_status"] == "SUBMITTED"
        ):
            b["ballot_status"] = "INVALIDATED"
            D.touch(b, coop)
    shares_voted = sum(
        e["shares_held"]
        for e in STORE["share_ledger_entries"].values()
        if e["cooperative_id"] == cid
        and e["shareholder_id"] == shareholder_id
        and e["entry_status"] == "ACTIVE"
    )
    b = D.make(
        "ballots", coop,
        cooperative_id=cid,
        meeting_id=mid,
        shareholder_id=shareholder_id,
        ballot_kind=ballot_kind,
        shares_voted=shares_voted,
        candidate_user_ids=list(candidates),
        ballot_status="SUBMITTED",
    )
    D.recompute_meeting(coop, m)
    return ok(D.ser(b), 201)


@bp.get("/cooperatives/<cid>/meetings/<mid>/ballots")
def list_ballots(cid, mid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    D.get_scoped("meetings", mid, cid, "Meeting")
    items = [
        b for b in D.all_of("ballots", cid)
        if b["meeting_id"] == mid
    ]
    status = request.args.get("ballot_status")
    if status is not None:
        items = [b for b in items if b["ballot_status"] == status]
    total = len(items)
    limit, offset = pagination()
    return ok_list([D.ser(b) for b in items[offset:offset + limit]], total, limit, offset)


@bp.get("/cooperatives/<cid>/meetings/<mid>/ballots/<bid>")
def get_ballot(cid, mid, bid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    D.get_scoped("meetings", mid, cid, "Meeting")
    b = STORE["ballots"].get(bid)
    if b is None or b["cooperative_id"] != cid or b["meeting_id"] != mid:
        raise ApiError("ERR_NOT_FOUND", "Ballot %s not found" % bid, 404)
    return ok(D.ser(b))
