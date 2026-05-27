"""BoardElection + Vote endpoints."""
from __future__ import annotations

import datetime

from flask import Blueprint, g, request

import db
from errors import (
    ERR_DUPLICATE_VOTE,
    ERR_ELECTION_NOT_OPEN,
    ERR_INVALID_ELECTION_WINDOW,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
    ERR_VOTER_INELIGIBLE,
    raise_err,
)
from middleware import auth_required
from response import list_success, success
from routes.owners import _is_eligible_voter
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_str,
)


bp = Blueprint("elections", __name__)


def _serialize_election(e: dict) -> dict:
    return {
        "id": e["id"],
        "community_id": e["community_id"],
        "cycle_label": e["cycle_label"],
        "opens_at": e["opens_at"],
        "closes_at": e["closes_at"],
        "status": e["status"],
        "eligible_voter_count": int(e.get("eligible_voter_count", 0)),
        "votes_cast": int(e.get("votes_cast", 0)),
        "opened_by_user_id": e.get("opened_by_user_id"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _serialize_vote(v: dict) -> dict:
    return {
        "id": v["id"],
        "election_id": v["election_id"],
        "owner_id": v["owner_id"],
        "candidate_name": v["candidate_name"],
        "state": v["state"],
        "cast_at": v["cast_at"],
        "created_at": v["created_at"],
    }


def _recompute_votes_cast(election: dict):
    eid = election["id"]
    count = sum(
        1 for v in db.votes.values()
        if v["election_id"] == eid and v["state"] == "CAST"
    )
    election["votes_cast"] = count


# ---------------------------------------------------------------------------
# BoardElection endpoints
# ---------------------------------------------------------------------------
@bp.route("/hoa/elections", methods=["POST"])
@auth_required({"BoardSecretary"})
def create_election():
    body = get_json_body()
    community_id = require_str(body, "community_id")
    cycle_label = require_str(body, "cycle_label")
    opens_at_s = require_str(body, "opens_at")
    closes_at_s = require_str(body, "closes_at")

    fetch_or_404(db.communities, community_id, "Community")
    try:
        opens_at = db.parse_iso(opens_at_s)
        closes_at = db.parse_iso(closes_at_s)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "Invalid ISO 8601 timestamp")

    # cycle_label unique within community
    for existing in db.board_elections.values():
        if (existing["community_id"] == community_id
                and existing["cycle_label"] == cycle_label):
            raise_err(ERR_INVALID_STATE,
                      f"cycle_label already used in community: {cycle_label}")

    record = {
        **db.make_common_fields(),
        "community_id": community_id,
        "cycle_label": cycle_label,
        "opens_at": db.fmt_iso(opens_at),
        "closes_at": db.fmt_iso(closes_at),
        "status": "DRAFT",
        "eligible_voter_count": 0,
        "votes_cast": 0,
        "opened_by_user_id": None,
    }
    db.board_elections[record["id"]] = record
    return success(_serialize_election(record), status=201)


@bp.route("/hoa/elections/<eid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember", "HomeOwner"})
def fetch_election(eid):
    e = fetch_or_404(db.board_elections, eid, "BoardElection")
    return success(_serialize_election(e))


@bp.route("/hoa/elections", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember", "HomeOwner"})
def list_elections():
    limit, offset = parse_pagination()
    community_id = request.args.get("community_id")
    status = request.args.get("status")
    rows = list(db.board_elections.values())
    if community_id is not None:
        rows = [r for r in rows if r["community_id"] == community_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize_election(r) for r in page],
                        total, limit, offset)


@bp.route("/hoa/elections/<eid>/open", methods=["POST"])
@auth_required({"BoardSecretary"})
def open_election(eid):
    body = get_json_body()
    expected_version = require_int(body, "expected_community_version",
                                   min_value=0)
    e = fetch_or_404(db.board_elections, eid, "BoardElection")
    community = fetch_or_404(db.communities, e["community_id"], "Community")

    # state-machine eligibility first
    if e["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE,
                  f"BoardElection must be DRAFT to open (currently {e['status']})")

    # business_temporal: window length and opens_at in future
    opens_at = db.parse_iso(e["opens_at"])
    closes_at = db.parse_iso(e["closes_at"])
    now = db.get_current_utc()
    if not (now < opens_at):
        raise_err(ERR_INVALID_ELECTION_WINDOW,
                  "current_utc must be strictly before opens_at")
    if (closes_at - opens_at) < datetime.timedelta(days=14):
        raise_err(ERR_INVALID_ELECTION_WINDOW,
                  "Election window must be at least 14 days")

    # OCC last (priority 16)
    if int(community["version"]) != int(expected_version):
        raise_err(ERR_STALE_VERSION,
                  f"Community version is {community['version']}, "
                  f"expected {expected_version}")

    # snapshot eligible_voter_count for this community
    eligible = 0
    for owner in db.owners.values():
        if owner["community_id"] != community["id"]:
            continue
        if owner["status"] != "ACTIVE":
            continue
        if _is_eligible_voter(owner):
            eligible += 1

    e["status"] = "OPEN"
    e["eligible_voter_count"] = eligible
    e["opened_by_user_id"] = g.user_id
    db.bump(e)
    # bump community version per scaffold side effect
    db.bump(community)
    return success(_serialize_election(e))


@bp.route("/hoa/elections/<eid>/close", methods=["POST"])
@auth_required({"BoardSecretary"})
def close_election(eid):
    e = fetch_or_404(db.board_elections, eid, "BoardElection")
    if e["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE,
                  f"BoardElection must be OPEN to close (currently {e['status']})")
    closes_at = db.parse_iso(e["closes_at"])
    now = db.get_current_utc()
    if now < closes_at:
        raise_err(ERR_INVALID_STATE,
                  "current_utc must be at or past closes_at to close")
    _recompute_votes_cast(e)
    community = fetch_or_404(db.communities, e["community_id"], "Community")
    quorum_pct = int(community["election_quorum_pct"])
    if int(e["votes_cast"]) * 100 >= int(e["eligible_voter_count"]) * quorum_pct:
        e["status"] = "CLOSED_QUORUM_MET"
    else:
        e["status"] = "CLOSED_NO_QUORUM"
    db.bump(e)
    return success(_serialize_election(e))


@bp.route("/hoa/elections/<eid>/certify", methods=["POST"])
@auth_required({"BoardPresident"})
def certify_election(eid):
    e = fetch_or_404(db.board_elections, eid, "BoardElection")
    if e["status"] != "CLOSED_QUORUM_MET":
        raise_err(ERR_INVALID_STATE,
                  f"BoardElection must be CLOSED_QUORUM_MET to certify "
                  f"(currently {e['status']})")
    # segregation of duties: certifier must not be the secretary who issued OPEN
    if e.get("opened_by_user_id") == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Certifying BoardPresident cannot be the BoardSecretary who opened the election")
    e["status"] = "CERTIFIED"
    db.bump(e)
    return success(_serialize_election(e))


@bp.route("/hoa/elections/<eid>/invalidate", methods=["POST"])
@auth_required({"BoardPresident"})
def invalidate_election(eid):
    e = fetch_or_404(db.board_elections, eid, "BoardElection")
    if e["status"] not in {"CLOSED_QUORUM_MET", "CLOSED_NO_QUORUM"}:
        raise_err(ERR_INVALID_STATE,
                  f"BoardElection must be in a CLOSED_* state to invalidate "
                  f"(currently {e['status']})")
    e["status"] = "INVALIDATED"
    db.bump(e)
    return success(_serialize_election(e))


# ---------------------------------------------------------------------------
# Vote endpoints
# ---------------------------------------------------------------------------
@bp.route("/hoa/votes", methods=["POST"])
@auth_required({"HomeOwner"})
def cast_vote():
    body = get_json_body()
    election_id = require_str(body, "election_id")
    owner_id = require_str(body, "owner_id")
    candidate_name = require_str(body, "candidate_name")

    e = fetch_or_404(db.board_elections, election_id, "BoardElection")
    owner = fetch_or_404(db.owners, owner_id, "Owner")

    # The voter must be the calling owner
    if g.user_id != owner_id:
        raise_err(ERR_UNAUTHORIZED,
                  "Vote can only be cast on behalf of the calling owner")

    # business_temporal (priority 10): election must be OPEN and current_utc < closes_at
    now = db.get_current_utc()
    closes_at = db.parse_iso(e["closes_at"])
    if e["status"] != "OPEN" or now >= closes_at:
        raise_err(ERR_ELECTION_NOT_OPEN,
                  "Election is not OPEN or ballot window has closed")

    # business_referential (priority 11): voter must be eligible AND have a property in this community
    if owner["community_id"] != e["community_id"]:
        raise_err(ERR_VOTER_INELIGIBLE,
                  "Voter is not a member of this community")
    if not _is_eligible_voter(owner):
        raise_err(ERR_VOTER_INELIGIBLE,
                  "Voter is not eligible (owns no property or has a filed lien)")

    # business_referential / constraint (priority 12): one CAST vote per (election, owner)
    for existing in db.votes.values():
        if (existing["election_id"] == election_id
                and existing["owner_id"] == owner_id
                and existing["state"] == "CAST"):
            raise_err(ERR_DUPLICATE_VOTE,
                      "Owner has already cast a vote in this election")

    now_s = db.iso_now()
    vote = {
        "id": db.new_id(),
        "election_id": election_id,
        "owner_id": owner_id,
        "candidate_name": candidate_name,
        "state": "CAST",
        "cast_at": now_s,
        "created_at": now_s,
    }
    db.votes[vote["id"]] = vote
    _recompute_votes_cast(e)
    db.bump(e)
    return success(_serialize_vote(vote), status=201)


@bp.route("/hoa/votes/<vid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "HomeOwner"})
def fetch_vote(vid):
    v = fetch_or_404(db.votes, vid, "Vote")
    return success(_serialize_vote(v))


@bp.route("/hoa/votes", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "HomeOwner"})
def list_votes():
    limit, offset = parse_pagination()
    election_id = request.args.get("election_id")
    owner_id = request.args.get("owner_id")
    rows = list(db.votes.values())
    if election_id is not None:
        rows = [r for r in rows if r["election_id"] == election_id]
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize_vote(r) for r in page],
                        total, limit, offset)


@bp.route("/hoa/votes/<vid>/retract", methods=["POST"])
@auth_required({"HomeOwner"})
def retract_vote(vid):
    v = fetch_or_404(db.votes, vid, "Vote")
    if v["state"] != "CAST":
        raise_err(ERR_INVALID_STATE,
                  f"Vote must be CAST to retract (currently {v['state']})")
    e = fetch_or_404(db.board_elections, v["election_id"], "BoardElection")
    if e["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE,
                  "Vote can only be retracted while election is OPEN")
    # ownership check: vote must belong to caller
    if g.user_id != v["owner_id"]:
        raise_err(ERR_UNAUTHORIZED,
                  "Caller cannot retract another owner's vote")
    v["state"] = "RETRACTED"
    _recompute_votes_cast(e)
    db.bump(e)
    return success(_serialize_vote(v))
