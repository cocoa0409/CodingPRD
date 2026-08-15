"""Annual meeting, reconvene chain, tally, and ballot endpoints."""
from datetime import date

from flask import Blueprint, request

import db
from auth import require_roles, MEMBER, STAFF_ROLES
from errors import ApiError
from response import ok_object, paginate, now_iso
from serializers import serialize_meeting, serialize_ballot
from services import calc
from services.sweep import new_id, bump
from validators import get_body, req_str, req_int, req_enum, req_date

bp = Blueprint("meetings", __name__)

CHOICES = {"FOR_SLATE_A", "FOR_SLATE_B", "ABSTAIN"}


def _get_meeting_or_404(mid):
    m = db.meetings.get(mid)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", f"annual meeting {mid} not found")
    return m


def _new_meeting(meeting_date, record_date, voting_open_date, quorum_threshold,
                 reconvened_from_id):
    meeting = {
        "id": new_id(),
        "meeting_date": meeting_date,
        "record_date": record_date,
        "voting_open_date": voting_open_date,
        "quorum_threshold": quorum_threshold,
        "status": "SCHEDULED",
        "reconvened_from_id": reconvened_from_id,
        "quorum_met": None,
        "ballots_counted": None,
        "votes_for_slate_a": None,
        "votes_for_slate_b": None,
        "votes_abstain": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.meetings[meeting["id"]] = meeting
    return meeting


def _check_thirty_day_gap(meeting_date, exempt_chain_ids):
    """Reject when fewer than 30 days from a SCHEDULED/HELD meeting outside the
    reconvene chain; exactly 30 days is permitted."""
    new_d = date.fromisoformat(meeting_date)
    for m in db.meetings.values():
        if m["status"] in ("SCHEDULED", "HELD") and m["id"] not in exempt_chain_ids:
            if abs((new_d - date.fromisoformat(m["meeting_date"])).days) < 30:
                raise ApiError("ERR_MEETING_TOO_CLOSE",
                               "meeting is within 30 days of another SCHEDULED or HELD meeting")


@bp.post("/credit-union/annual-meetings")
def create_meeting():
    require_roles({"BoardDirector"})
    body = get_body()
    # Tier 4: syntactic
    meeting_date = req_date(body, "meeting_date")
    record_date = req_date(body, "record_date")
    voting_open_date = req_date(body, "voting_open_date")
    quorum_threshold = req_int(body, "quorum_threshold")
    if quorum_threshold <= 0:
        raise ApiError("ERR_VALIDATION_FAILED",
                       "quorum_threshold must be a positive integer")
    # Tier 11: thirty-day minimum gap (a freshly scheduled meeting has no chain)
    _check_thirty_day_gap(meeting_date, set())
    # Tier 11: record_date < voting_open_date <= meeting_date
    if not (record_date < voting_open_date <= meeting_date):
        raise ApiError("ERR_DATE_ORDER_INVALID",
                       "record_date must precede voting_open_date, which must be on or before meeting_date")
    meeting = _new_meeting(meeting_date, record_date, voting_open_date,
                           quorum_threshold, None)
    return ok_object(serialize_meeting(meeting), 201)


@bp.get("/credit-union/annual-meetings")
def list_meetings():
    require_roles(STAFF_ROLES)
    items = list(db.meetings.values())
    for f in ("status", "reconvened_from_id"):
        v = request.args.get(f)
        if v is not None:
            items = [m for m in items if m.get(f) == v]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return paginate([serialize_meeting(m) for m in items])


@bp.get("/credit-union/annual-meetings/<mid>")
def get_meeting(mid):
    require_roles(STAFF_ROLES | {MEMBER})
    return ok_object(serialize_meeting(_get_meeting_or_404(mid)), 200)


@bp.post("/credit-union/annual-meetings/<mid>/close-and-tally")
def close_and_tally(mid):
    require_roles({"BoardDirector"})
    meeting = _get_meeting_or_404(mid)
    if meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_MEETING_INVALID_STATE", "meeting is not SCHEDULED")
    ballots = calc.chain_ballots(meeting)
    distinct_voters = len({b["member_id"] for b in ballots})
    meeting["quorum_met"] = distinct_voters >= meeting["quorum_threshold"]
    meeting["ballots_counted"] = distinct_voters
    meeting["votes_for_slate_a"] = sum(1 for b in ballots if b["choice"] == "FOR_SLATE_A")
    meeting["votes_for_slate_b"] = sum(1 for b in ballots if b["choice"] == "FOR_SLATE_B")
    meeting["votes_abstain"] = sum(1 for b in ballots if b["choice"] == "ABSTAIN")
    meeting["status"] = "HELD" if meeting["quorum_met"] else "ADJOURNED_NO_QUORUM"
    bump(meeting)
    return ok_object(serialize_meeting(meeting), 200)


@bp.post("/credit-union/annual-meetings/<mid>/reconvene")
def reconvene(mid):
    require_roles({"BoardDirector"})
    body = get_body()
    meeting_date = req_date(body, "meeting_date")
    voting_open_date = req_date(body, "voting_open_date")
    source = _get_meeting_or_404(mid)
    if source["status"] != "ADJOURNED_NO_QUORUM":
        raise ApiError("ERR_MEETING_INVALID_STATE",
                       "meeting is not ADJOURNED_NO_QUORUM")
    # record_date < voting_open_date <= meeting_date with the inherited record_date
    if not (source["record_date"] < voting_open_date <= meeting_date):
        raise ApiError("ERR_DATE_ORDER_INVALID",
                       "voting_open_date must follow the record_date and be on or before meeting_date")
    # The 30-day spacing rule is waived only inside the chain; meetings outside
    # the chain still constrain the successor's date.
    _check_thirty_day_gap(meeting_date, set(calc.chain_ids(source)))
    meeting = _new_meeting(meeting_date, source["record_date"], voting_open_date,
                           source["quorum_threshold"], source["id"])
    return ok_object(serialize_meeting(meeting), 201)


@bp.get("/credit-union/annual-meetings/<mid>/ballots")
def list_meeting_ballots(mid):
    require_roles(STAFF_ROLES)
    _get_meeting_or_404(mid)
    items = [b for b in db.ballots.values() if b["meeting_id"] == mid]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    return paginate([serialize_ballot(b) for b in items])


@bp.post("/credit-union/ballots")
def cast_ballot():
    uid, role = require_roles({MEMBER})
    body = get_body()
    # Tier 4: syntactic
    meeting_id = req_str(body, "meeting_id")
    choice = req_enum(body, "choice", CHOICES)
    # Tier 5: existence
    meeting = _get_meeting_or_404(meeting_id)
    # Tier 7, left-most resource first: meeting state before voter eligibility
    if meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_MEETING_INVALID_STATE", "meeting is not SCHEDULED")
    member = db.members.get(uid)
    if (member is None or member["status"] != "ACTIVE"
            or member["membership_effective_date"] > meeting["record_date"]):
        raise ApiError("ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE",
                       "member is not ACTIVE or joined after the record_date")
    # Tier 10: one ballot per member per reconvene chain
    cids = set(calc.chain_ids(meeting))
    for b in db.ballots.values():
        if b["meeting_id"] in cids and b["member_id"] == uid:
            raise ApiError("ERR_BALLOT_ALREADY_CAST_IN_CHAIN",
                           "member already cast a ballot in this reconvene chain")
    # Tier 11: voting window
    current_s = db.clock.current_date_str()
    if not (meeting["voting_open_date"] <= current_s <= meeting["meeting_date"]):
        raise ApiError("ERR_VOTING_WINDOW_CLOSED",
                       "current date is outside the voting window")
    ballot = {
        "id": new_id(),
        "meeting_id": meeting_id,
        "member_id": uid,
        "choice": choice,
        "cast_date": current_s,
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.ballots[ballot["id"]] = ballot
    return ok_object(serialize_ballot(ballot), 201)
