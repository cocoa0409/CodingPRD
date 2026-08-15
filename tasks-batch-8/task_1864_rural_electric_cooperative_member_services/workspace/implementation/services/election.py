"""BoardElection and Ballot services."""
import math

from errors import ApiError
import db
from db import store, new_common, new_append_only, touch


# =============================================================================
# BoardElection
# =============================================================================

def create_election(body):
    required = ["cooperative_id", "year", "seats", "voting_opens_at", "voting_closes_at"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")

    coop = store.cooperatives.get(body["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")

    election = new_common({
        "cooperative_id": body["cooperative_id"],
        "year": body["year"],
        "status": "DRAFT",
        "seats": body["seats"],
        "voting_opens_at": body["voting_opens_at"],
        "voting_closes_at": body["voting_closes_at"],
        "quorum_met": False,
        "_candidate_names": [],
    })
    store.board_elections[election["id"]] = election
    return election


def get_election(election_id):
    e = store.board_elections.get(election_id)
    if not e:
        raise ApiError("ERR_NOT_FOUND", 404, "BoardElection not found")
    return e


def list_elections(cooperative_id=None, status=None):
    rows = list(store.board_elections.values())
    if cooperative_id is not None:
        rows = [r for r in rows if r.get("cooperative_id") == cooperative_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def open_nominations(election_id):
    e = get_election(election_id)
    if e["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Election must be DRAFT to open nominations")

    coop = store.cooperatives.get(e["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")

    e["status"] = "NOMINATION_OPEN"
    coop["active_election_id"] = e["id"]
    touch(e)
    touch(coop)
    return e


def close_nominations(election_id, body):
    e = get_election(election_id)
    if e["status"] != "NOMINATION_OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Election must be NOMINATION_OPEN to close nominations")

    candidate_names = body.get("candidate_names")
    if not isinstance(candidate_names, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "candidate_names is required")

    # Each seat must have >= 1 declared candidate. PRD §3.9 declares a flat
    # candidate_names list; untagged name entries satisfy the per-seat
    # requirement. Seat-tagged dict entries ({seat|district, name}) cover only
    # the seats they name. An empty list leaves every seat without a
    # candidate -> ERR_ELECTION_NO_CANDIDATE, election stays NOMINATION_OPEN.
    seats = [int(s) for s in e.get("seats", [])]
    seats_with_candidates = set()
    untagged = 0
    for entry in candidate_names:
        if isinstance(entry, dict):
            seat = entry.get("seat", entry.get("district"))
            if seat is not None:
                seats_with_candidates.add(int(seat))
        elif isinstance(entry, str) and entry:
            untagged += 1
    if untagged:
        seats_with_candidates.update(seats)

    for seat in seats:
        if seat not in seats_with_candidates:
            raise ApiError("ERR_ELECTION_NO_CANDIDATE", 409,
                           f"Seat {seat} has no declared candidate")

    e["_candidate_names"] = candidate_names
    e["status"] = "NOMINATION_CLOSED"
    touch(e)
    return e


def open_voting(election_id, body):
    e = get_election(election_id)
    if e["status"] != "NOMINATION_CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Election must be NOMINATION_CLOSED to open voting")

    coop = store.cooperatives.get(e["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")

    # OCC check
    expected_version = body.get("expected_cooperative_version")
    if expected_version is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_cooperative_version is required")
    if int(expected_version) != coop.get("version", 1):
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_cooperative_version does not match current Cooperative.version")

    # Temporal check: logical clock >= voting_opens_at
    now = db.logical_now()
    opens = db.parse_iso(e["voting_opens_at"])
    if now < opens:
        raise ApiError("ERR_ELECTION_WINDOW", 409,
                       "Logical clock has not reached voting_opens_at")

    e["status"] = "VOTING_OPEN"
    e["quorum_met"] = False
    touch(e)
    return e


def close_voting(election_id):
    e = get_election(election_id)
    if e["status"] != "VOTING_OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Election must be VOTING_OPEN to close voting")

    coop = store.cooperatives.get(e["cooperative_id"])
    if not coop:
        raise ApiError("ERR_NOT_FOUND", 404, "Cooperative not found")

    # Temporal check: logical clock >= voting_closes_at
    now = db.logical_now()
    closes = db.parse_iso(e["voting_closes_at"])
    if now < closes:
        raise ApiError("ERR_ELECTION_WINDOW", 409,
                       "Logical clock has not reached voting_closes_at")

    # Recompute quorum
    distinct_voters = len({
        b["member_id"] for b in store.ballots.values()
        if b.get("election_id") == election_id
    })
    active_count = sum(1 for m in store.members.values() if m.get("status") == "ACTIVE")
    quorum_threshold = math.ceil(coop.get("annual_meeting_quorum_pct", 0) * active_count)
    e["quorum_met"] = distinct_voters >= quorum_threshold

    e["status"] = "VOTING_CLOSED"
    touch(e)
    return e


def certify_election(election_id):
    e = get_election(election_id)
    if e["status"] != "VOTING_CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Election must be VOTING_CLOSED to certify")

    if not e.get("quorum_met"):
        raise ApiError("ERR_ELECTION_NO_QUORUM", 409, "Quorum not met")

    coop = store.cooperatives.get(e["cooperative_id"])
    if coop:
        coop["active_election_id"] = None
        touch(coop)

    e["status"] = "CERTIFIED"
    touch(e)
    return e


def void_election(election_id):
    e = get_election(election_id)
    if e["status"] != "VOTING_CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Election must be VOTING_CLOSED to void")

    coop = store.cooperatives.get(e["cooperative_id"])
    if coop:
        coop["active_election_id"] = None
        touch(coop)

    e["status"] = "VOIDED"
    touch(e)
    return e


# =============================================================================
# Ballot
# =============================================================================

def cast_ballot(body, user_id):
    required = ["election_id", "district", "candidate_name"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")

    election = store.board_elections.get(body["election_id"])
    if not election:
        raise ApiError("ERR_NOT_FOUND", 404, "BoardElection not found")

    # Check election is VOTING_OPEN
    if election["status"] != "VOTING_OPEN":
        raise ApiError("ERR_ELECTION_WINDOW", 409, "Election is not in VOTING_OPEN")

    # Check temporal window
    now = db.logical_now()
    opens = db.parse_iso(election["voting_opens_at"])
    closes = db.parse_iso(election["voting_closes_at"])
    if not (opens <= now < closes):
        raise ApiError("ERR_ELECTION_WINDOW", 409,
                       "Logical clock outside voting window")

    # Member must exist and be ACTIVE
    member = store.members.get(user_id)
    if not member:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_BALLOT_MEMBER_INACTIVE", 409,
                       "Ballot cast by a member not in ACTIVE status")

    # District check for non-proxy ballots
    is_proxy = body.get("is_proxy", False)
    if not is_proxy:
        if int(body["district"]) != int(member.get("district_id", 0)):
            raise ApiError("ERR_BALLOT_DISTRICT_MISMATCH", 409,
                           "Non-proxy ballot cast for a district other than the member's district_id")

    # Uniqueness: one ballot per (election_id, member_id, district)
    for b in store.ballots.values():
        if (b.get("election_id") == body["election_id"]
                and b.get("member_id") == user_id
                and int(b.get("district", 0)) == int(body["district"])):
            raise ApiError("ERR_BALLOT_ALREADY_CAST", 409,
                           "A ballot for this (election_id, member_id, district) already exists")

    ballot = new_append_only({
        "election_id": body["election_id"],
        "member_id": user_id,
        "district": body["district"],
        "candidate_name": body["candidate_name"],
        "cast_at": db.iso_logical(now),
        "is_proxy": is_proxy,
    })
    store.ballots[ballot["id"]] = ballot
    return ballot


def get_ballot(ballot_id):
    b = store.ballots.get(ballot_id)
    if not b:
        raise ApiError("ERR_NOT_FOUND", 404, "Ballot not found")
    return b


def list_ballots(election_id=None, district=None, member_id=None):
    rows = list(store.ballots.values())
    if election_id is not None:
        rows = [r for r in rows if r.get("election_id") == election_id]
    if district is not None:
        rows = [r for r in rows if str(r.get("district")) == str(district)]
    if member_id is not None:
        rows = [r for r in rows if r.get("member_id") == member_id]
    return rows
