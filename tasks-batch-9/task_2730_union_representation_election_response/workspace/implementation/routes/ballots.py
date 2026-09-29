"""Challenged ballots: segregation, resolution and the compensating reopen."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("ballots", __name__)

BASE = "/labor-relations/challenged-ballots"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)
TALLY_STATES = ("TALLY_POSTED", "TALLY_REVISED")


def _require_tally_round(ballot):
    session = store.get("poll_sessions", ballot["poll_session_id"])
    rnd = store.round_of_session(session) if session else None
    if rnd is None or rnd["status"] not in TALLY_STATES:
        raise ApiError("ERR_ROUND_STATUS_INVALID",
                       "The round's tally must be posted or revised.")
    return rnd


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.BOARD])
def create_ballot(user_id, role):
    schema = validate.Schema(validate.body())
    poll_session_id = schema.reference("poll_session_id")
    voter_list_entry_id = schema.reference("voter_list_entry_id", required=False)
    challenger_party = schema.enum("challenger_party", common.CHALLENGER_PARTIES)
    basis = schema.enum("basis", common.CHALLENGE_BASES)

    session = gates.must_exist("poll_sessions", poll_session_id)
    entry = None
    if voter_list_entry_id is not None:
        entry = gates.must_exist("voter_list_entries", voter_list_entry_id)

    rnd = store.round_of_session(session)
    petition = store.petition_of_session(session)
    if entry is not None:
        entry_list = store.list_of_entry(entry)
        if petition is not None and entry_list is not None:
            gates.require_same_petition(petition["id"], entry_list["petition_id"])
        if entry_list is None or entry_list["status"] != "ACCEPTED":
            raise ApiError("ERR_BALLOT_VOTER_NOT_ON_ACCEPTED_LIST",
                           "The named voter entry does not sit on an ACCEPTED voter list.")
        for existing in store.ballots_of_session(poll_session_id):
            if existing.get("voter_list_entry_id") == voter_list_entry_id:
                raise ApiError("ERR_DUPLICATE_CHALLENGED_BALLOT",
                               "That voter's ballot was already challenged at this session.")

    row = {
        "poll_session_id": poll_session_id,
        "voter_list_entry_id": voter_list_entry_id,
        "challenger_party": challenger_party,
        "basis": basis,
        "resolution": "OPEN",
        "resolved_at": None,
        "reopen_count": 0,
    }
    store.insert("challenged_ballots", row)

    session["challenged_ballot_count"] += 1
    store.touch(session)
    if rnd is not None:
        rnd["challenged_open_count"] += 1
        rnd["ballots_cast_total"] += 1
        gates.check_ballot_conservation(rnd)
        store.touch(rnd)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_ballots(user_id, role):
    poll_session_id = validate.query_string("poll_session_id")
    voter_list_entry_id = validate.query_string("voter_list_entry_id")
    resolution = validate.query_enum("resolution", common.BALLOT_RESOLUTIONS)
    rows = store.ordered("challenged_ballots")
    if poll_session_id is not None:
        rows = [r for r in rows if r["poll_session_id"] == poll_session_id]
    if voter_list_entry_id is not None:
        rows = [r for r in rows if r.get("voter_list_entry_id") == voter_list_entry_id]
    if resolution is not None:
        rows = [r for r in rows if r["resolution"] == resolution]
    return common.list_response(rows)


@bp.route(BASE + "/<bid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_ballot(user_id, role, bid):
    return common.one(gates.must_exist("challenged_ballots", bid))


@bp.route(BASE + "/<bid>/resolve", methods=["POST"])
@auth.endpoint([auth.BOARD])
def resolve_ballot(user_id, role, bid):
    schema = validate.Schema(validate.body())
    resolution = schema.enum("resolution", common.RESOLUTION_CHOICES)
    withdrawing_party = schema.enum("withdrawing_party", common.CHALLENGER_PARTIES,
                                    required=(resolution == "WITHDRAWN"))

    ballot = gates.must_exist("challenged_ballots", bid)
    if ballot["resolution"] != "OPEN":
        raise ApiError("ERR_BALLOT_STATUS_INVALID",
                       "Only an OPEN challenged ballot may be resolved.")
    rnd = _require_tally_round(ballot)
    if resolution == "WITHDRAWN" and withdrawing_party != ballot["challenger_party"]:
        raise validate.invalid(
            "withdrawing_party must be the party recorded in challenger_party.")

    ballot["resolution"] = resolution
    ballot["resolved_at"] = clockutil.now_dt_str()
    rnd["challenged_open_count"] -= 1
    rnd[common.BALLOT_BUCKET[resolution]] += 1
    gates.check_ballot_conservation(rnd)
    store.touch(ballot)
    store.touch(rnd)
    return common.one(ballot)


@bp.route(BASE + "/<bid>/reopen", methods=["POST"])
@auth.endpoint([auth.BOARD])
def reopen_ballot(user_id, role, bid):
    schema = validate.Schema(validate.body())
    schema.string("reopen_reason", required=False, allow_empty=True)

    ballot = gates.must_exist("challenged_ballots", bid)
    if ballot["resolution"] == "OPEN":
        raise ApiError("ERR_BALLOT_STATUS_INVALID",
                       "An OPEN challenged ballot has no resolution to undo.")
    rnd = _require_tally_round(ballot)
    if ballot["reopen_count"] >= calc.MAX_BALLOT_REOPENS:
        raise ApiError("ERR_REOPEN_LIMIT_EXCEEDED",
                       "The reopen ceiling for this ballot has been reached.")

    prior = ballot["resolution"]
    ballot["resolution"] = "OPEN"
    ballot["resolved_at"] = None
    ballot["reopen_count"] += 1
    rnd[common.BALLOT_BUCKET[prior]] -= 1
    rnd["challenged_open_count"] += 1
    gates.check_ballot_conservation(rnd)
    store.touch(ballot)
    store.touch(rnd)
    return common.one(ballot)
