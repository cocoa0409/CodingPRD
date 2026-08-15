"""Vote endpoints (PRD §3.5) — casting, ballot change with OCC, retraction."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ROUND_NOT_FOUND,
    ERR_VOTE_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_INVALID_ROUND_STATE,
    ERR_INVALID_VOTE_STATE,
    ERR_DUPLICATE_BALLOT,
    ERR_VOTER_NOT_ELIGIBLE,
    ERR_STALE_VERSION,
    ERR_RECUSAL_IRREVERSIBLE,
)
from middleware import authorized, ALL_READ_ROLES
from response import success_object
from routes.helpers import public, list_sealed, check_seal_single
from services import calculations as calc
from services.core import new_record, touch, case_of_vote
from util import CLOCK, parse_dt
from validate import get_body, req_str, req_enum, req_int, require_path, raw_str, raw_int

bp = Blueprint("votes", __name__)

BALLOTS = {"YES", "NO", "ABSTAIN", "RECUSE"}


def _membership(round_rec, user_id):
    """The caller's CommitteeMember record within the round's committee."""
    for m in db["members"].values():
        if m["committee_id"] == round_rec["committee_id"] and m["id"] == user_id:
            return m
    return None


def _require_membership(caller, round_rec):
    """Priority 5: the voter must be a CommitteeMember of the round's committee."""
    member = _membership(round_rec, caller.user_id)
    if member is None:
        raise_error(ERR_OWNERSHIP_MISMATCH,
                    "acting user is not a member of this round's committee")
    return member


def _require_voting_open(round_rec):
    if round_rec["status"] != "VOTING_OPEN":
        raise_error(ERR_INVALID_ROUND_STATE,
                    f"ballot operations require VOTING_OPEN, not {round_rec['status']}")


@bp.post("/votes")
def cast_vote():
    caller = authorized(["CommitteeVoter"])
    body = get_body()
    # Priority 4: round FK existence.
    round_rec = None
    round_id_raw = raw_str(body, "round_id")
    if round_id_raw is not None:
        round_rec = db["rounds"].get(round_id_raw)
        if round_rec is None:
            raise_error(ERR_ROUND_NOT_FOUND, "round_id does not resolve")
    member = _require_membership(caller, round_rec) if round_rec is not None else None
    if round_rec is not None:
        _require_voting_open(round_rec)
    # Priority 9, listed order: duplicate ballot -> voter eligibility -> shape.
    if round_rec is not None and member is not None:
        for v in db["votes"].values():
            if (v["round_id"] == round_rec["id"] and v["member_id"] == member["id"]
                    and v["status"] == "CAST"):
                raise_error(ERR_DUPLICATE_BALLOT,
                            "member already holds a non-retracted ballot in this round")
        if not member["is_active"] or not (
            parse_dt(member["service_start"]) <= parse_dt(round_rec["opened_at"]) <= parse_dt(member["service_end"])
        ):
            raise_error(ERR_VOTER_NOT_ELIGIBLE,
                        "voter is inactive or outside the service window at round open")
    round_id = req_str(body, "round_id")
    ballot = req_enum(body, "ballot", BALLOTS)
    rec = new_record("votes", {
        "round_id": round_id,
        "member_id": caller.user_id,  # resolved from X-User-ID, never the body
        "ballot": ballot,
        "status": "CAST",
        "cast_at": CLOCK.now_iso(),
        "retracted_at": None,
    })
    calc.recompute_round_tallies(round_rec)
    touch(round_rec)
    return success_object(public(rec), status=201)


@bp.get("/votes")
def list_votes():
    def case_id_of(v):
        rnd = db["rounds"].get(v["round_id"])
        return rnd["case_id"] if rnd else None
    return list_sealed("votes", {
        "round_id": request.args.get("round_id"),
        "member_id": request.args.get("member_id"),
    }, case_id_of=case_id_of)


@bp.get("/votes/<rid>")
def get_vote(rid):
    from middleware import get_caller, check_role_allowed
    caller = get_caller()
    check_role_allowed(caller, ALL_READ_ROLES)
    vote = require_path("votes", rid, ERR_VOTE_NOT_FOUND)
    check_seal_single(caller, case_of_vote(vote))
    return success_object(public(vote))


@bp.patch("/votes/<rid>")
def patch_vote(rid):
    caller = authorized(["CommitteeVoter"])
    vote = require_path("votes", rid, ERR_VOTE_NOT_FOUND)
    body = get_body()
    # Priority 5: only the vote's own member may change it.
    if caller.user_id != vote["member_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting user is not this vote's member")
    # Priority 6: OCC on the vote version.
    expected = raw_int(body, "expected_vote_version")
    if expected is not None and expected != vote["version"]:
        raise_error(ERR_STALE_VERSION, "expected_vote_version does not match the vote version")
    # Priority 7: round must be VOTING_OPEN; vote must be CAST.
    round_rec = db["rounds"].get(vote["round_id"])
    if round_rec is not None:
        _require_voting_open(round_rec)
    if vote["status"] != "CAST":
        raise_error(ERR_INVALID_VOTE_STATE,
                    f"cannot change a vote in status {vote['status']}")
    # Priority 8: recusal is irrevocable through the change path.
    new_ballot = raw_str(body, "ballot")
    if new_ballot in BALLOTS and (vote["ballot"] == "RECUSE" or new_ballot == "RECUSE"):
        raise_error(ERR_RECUSAL_IRREVERSIBLE,
                    "ballot changes from or to RECUSE are forbidden; retract and re-cast")
    # Priority 9: shape.
    ballot = req_enum(body, "ballot", BALLOTS)
    req_int(body, "expected_vote_version")  # non-optional OCC field (PRD §2.11)
    vote["ballot"] = ballot
    touch(vote)  # ballot change increments Vote.version by 1
    calc.recompute_round_tallies(round_rec)
    touch(round_rec)
    return success_object(public(vote))


@bp.post("/votes/<rid>/retract")
def retract_vote(rid):
    caller = authorized(["CommitteeVoter"])
    vote = require_path("votes", rid, ERR_VOTE_NOT_FOUND)
    if caller.user_id != vote["member_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting user is not this vote's member")
    round_rec = db["rounds"].get(vote["round_id"])
    if round_rec is not None:
        _require_voting_open(round_rec)
    if vote["status"] != "CAST":
        raise_error(ERR_INVALID_VOTE_STATE,
                    f"cannot retract a vote in status {vote['status']}")
    vote["status"] = "RETRACTED"
    vote["retracted_at"] = CLOCK.now_iso()
    touch(vote)
    calc.recompute_round_tallies(round_rec)
    touch(round_rec)
    return success_object(public(vote))
