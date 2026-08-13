"""OfficerElection and ElectionVote endpoints."""

from flask import Blueprint

import db
from core import (as_str, body, check_frozen, get_chapter, get_election,
                  get_vote, member_has_conflict, new_record, recompute_member,
                  require_fields, touch)
from db import now_iso, parse_dt
from errors import (ERR_ATHLETICS_CONFLICT, ERR_DUPLICATE_VOTE,
                    ERR_ELECTION_ALREADY_OPEN, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_INVALID_VOTE_STATE,
                    ERR_MEMBER_MISMATCH, ERR_NOT_FOUND, ERR_NO_VOTES_CAST,
                    ERR_OFFICE_ALREADY_OCCUPIED, ERR_RUNOFF_REQUIRED, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("elections", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")
OFFICES = ("PRESIDENT", "VICE_PRESIDENT", "SECRETARY", "TREASURER", "HISTORIAN")


@bp.route("/chapters/<chapterId>/elections", methods=["POST"])
def create_election(chapterId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    check_frozen(ch)
    data = body()
    require_fields(data, ["cycle_id", "office"])
    office = as_str(data["office"], "office")
    if office not in OFFICES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "office must be one of PRESIDENT, VICE_PRESIDENT, SECRETARY, TREASURER, HISTORIAN")
    cycle_id = as_str(data["cycle_id"], "cycle_id")
    cycle = db.cycles.get(cycle_id)
    if cycle is None or cycle["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"MembershipCycle not found: {cycle_id}")
    rec = new_record({
        "chapter_id": ch["id"],
        "cycle_id": cycle["id"],
        "office": office,
        "status": "DRAFT",
        "opened_at": None,
        "tallied_at": None,
        "winner_member_id": None,
        "runoff_required": False,
    })
    db.elections[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/elections/<electionId>", methods=["GET"])
def fetch_election(chapterId, electionId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    e = get_election(ch, electionId)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/elections", methods=["GET"])
def list_elections(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    items = [e for e in db.elections.values() if e["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/elections/<electionId>/open", methods=["POST"])
def open_election(chapterId, electionId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    e = get_election(ch, electionId)
    check_frozen(ch)
    if e["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT election can be opened")
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chapter must be ACTIVE to open an election")
    cycle = db.cycles.get(e["cycle_id"])
    if cycle is None or cycle["status"] not in ("REVIEW", "INDUCTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The referenced cycle must be in REVIEW or INDUCTED")
    # scheduling guard: any chapter member with an ACTIVE block overlapping the
    # cycle's induction date conflicts with committing the election schedule
    induction = parse_dt(cycle["induction_date"], "induction_date")
    for m in db.members.values():
        if m["chapter_id"] == ch["id"] and member_has_conflict(m["id"], induction):
            raise ApiError(ERR_ATHLETICS_CONFLICT, 409,
                           "A member's ACTIVE athletics block overlaps the relevant date")
    # election singularity last
    for other in db.elections.values():
        if (other["chapter_id"] == ch["id"] and other["id"] != e["id"]
                and other["status"] in ("OPEN", "TALLIED")):
            raise ApiError(ERR_ELECTION_ALREADY_OPEN, 409,
                           "Another election is already OPEN or TALLIED for this chapter")
    e["status"] = "OPEN"
    e["opened_at"] = now_iso()
    touch(e)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/elections/<electionId>/tally", methods=["POST"])
def tally_election(chapterId, electionId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    e = get_election(ch, electionId)
    check_frozen(ch)
    if e["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN election can be tallied")
    counts = {}
    for v in db.votes.values():
        if v["election_id"] == e["id"] and v["status"] == "CAST":
            counts[v["candidate_member_id"]] = counts.get(v["candidate_member_id"], 0) + 1
    if not counts:
        raise ApiError(ERR_NO_VOTES_CAST, 409, "Cannot tally an election with zero CAST votes")
    top = max(counts.values())
    leaders = [c for c, n in counts.items() if n == top]
    if len(leaders) == 1:
        e["winner_member_id"] = leaders[0]
        e["runoff_required"] = False
    else:
        e["winner_member_id"] = None
        e["runoff_required"] = True
    e["status"] = "TALLIED"
    e["tallied_at"] = now_iso()
    touch(e)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/elections/<electionId>/certify", methods=["POST"])
def certify_election(chapterId, electionId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    e = get_election(ch, electionId)
    check_frozen(ch)
    if e["status"] != "TALLIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a TALLIED election can be certified")
    # occupancy first, decisiveness second (pinned order, PRD 3.4)
    for r in db.officer_roles.values():
        if (r["chapter_id"] == ch["id"] and r["office"] == e["office"]
                and r["status"] == "ACTIVE"):
            raise ApiError(ERR_OFFICE_ALREADY_OCCUPIED, 409,
                           "An ACTIVE OfficerRole already holds this office")
    if e["runoff_required"] or not e["winner_member_id"]:
        raise ApiError(ERR_RUNOFF_REQUIRED, 409,
                       "The tally produced a tie; a runoff is required before certification")
    winner_id = e["winner_member_id"]
    rec = new_record({
        "chapter_id": ch["id"],
        "election_id": e["id"],
        "member_id": winner_id,
        "office": e["office"],
        "status": "ACTIVE",
        "started_at": now_iso(),
        "ended_at": None,
    })
    db.officer_roles[rec["id"]] = rec
    e["status"] = "CERTIFIED"
    touch(e)
    winner = db.members.get(winner_id)
    if winner is not None:
        recompute_member(winner)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/elections/<electionId>/void", methods=["POST"])
def void_election(chapterId, electionId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    e = get_election(ch, electionId)
    check_frozen(ch)
    if e["status"] not in ("DRAFT", "OPEN", "TALLIED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT, OPEN, or TALLIED election can be voided")
    if e["status"] == "OPEN":
        for v in db.votes.values():
            if v["election_id"] == e["id"] and v["status"] == "CAST":
                v["status"] = "VOIDED"
                touch(v)
    e["status"] = "VOIDED"
    touch(e)
    return success(serialize(e), 200)


# --- ElectionVote ---

@bp.route("/chapters/<chapterId>/elections/<electionId>/votes", methods=["POST"])
def cast_vote(chapterId, electionId):
    uid, role = auth()
    require_roles(role, ("Member",))
    ch = get_chapter(chapterId)
    e = get_election(ch, electionId)
    check_frozen(ch)
    if e["status"] != "OPEN":
        raise ApiError(ERR_INVALID_VOTE_STATE, 409,
                       "Votes can only be cast while the election is OPEN")
    data = body()
    require_fields(data, ["voter_member_id", "candidate_member_id"])
    voter_id = as_str(data["voter_member_id"], "voter_member_id")
    candidate_id = as_str(data["candidate_member_id"], "candidate_member_id")
    if uid != voter_id:
        raise ApiError(ERR_MEMBER_MISMATCH, 403,
                       "A member may only cast a vote as themselves")
    voter = db.members.get(voter_id)
    if voter is None or voter["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"Member not found: {voter_id}")
    candidate = db.members.get(candidate_id)
    if candidate is None or candidate["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"Member not found: {candidate_id}")
    for v in db.votes.values():
        if (v["election_id"] == e["id"] and v["voter_member_id"] == voter_id
                and v["status"] == "CAST"):
            raise ApiError(ERR_DUPLICATE_VOTE, 409,
                           "Voter has already cast a vote in this election")
    rec = new_record({
        "chapter_id": ch["id"],
        "election_id": e["id"],
        "voter_member_id": voter_id,
        "candidate_member_id": candidate_id,
        "cast_at": now_iso(),
        "status": "CAST",
    })
    db.votes[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/elections/<electionId>/votes", methods=["GET"])
def list_votes(chapterId, electionId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor"))
    ch = get_chapter(chapterId)
    e = get_election(ch, electionId)
    items = [v for v in db.votes.values() if v["election_id"] == e["id"]]
    items = apply_filters(items, ["status", "candidate_member_id"])
    return list_response(serialize_many(sorted_items(items)))
