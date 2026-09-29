"""Poll sessions: layout against a read-consistent round, observers, and closing."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("sessions", __name__)

BASE = "/labor-relations/poll-sessions"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.BOARD])
def create_session(user_id, role):
    schema = validate.Schema(validate.body())
    election_round_id = schema.reference("election_round_id")
    location_code = schema.string("location_code")
    session_start_at = schema.datetime("session_start_at")
    session_end_at = schema.datetime("session_end_at")
    method = schema.enum("method", common.SESSION_METHODS)
    expected_version = schema.integer("expected_election_round_version")
    validate.time_window(session_start_at, session_end_at)

    rnd = gates.must_exist("election_rounds", election_round_id)
    if expected_version != rnd["version"]:
        raise ApiError("ERR_STALE_ROUND_VERSION",
                       "The asserted election round version is stale.")
    if rnd["status"] != "SCHEDULED":
        raise ApiError("ERR_ROUND_NOT_SCHEDULED",
                       "A session may only be laid out against a SCHEDULED round.")

    candidate = {"session_start_at": session_start_at, "session_end_at": session_end_at}
    proposed = calc.session_occupancy(candidate)
    for existing in store.sessions_of(election_round_id):
        if existing["location_code"] != location_code:
            continue
        if existing["status"] not in ("SCHEDULED", "CLOSED"):
            continue
        if calc.half_open_overlap(proposed, calc.session_occupancy(existing)):
            raise ApiError("ERR_POLL_SESSION_LOCATION_CONFLICT",
                           "The polling location is still occupied at that time.")

    row = {
        "election_round_id": election_round_id,
        "location_code": location_code,
        "session_start_at": session_start_at,
        "session_end_at": session_end_at,
        "method": method,
        "status": "SCHEDULED",
        "votes_for_count": 0,
        "votes_against_count": 0,
        "void_count": 0,
        "challenged_ballot_count": 0,
        "employer_observer_count": 0,
        "union_observer_count": 0,
        "observer_roster": [],
        "closed_at": None,
    }
    store.insert("poll_sessions", row)
    rnd["scheduled_session_count"] += 1
    store.touch(rnd)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_sessions(user_id, role):
    election_round_id = validate.query_string("election_round_id")
    status = validate.query_enum("status", common.SESSION_STATUSES)
    rows = store.ordered("poll_sessions")
    if election_round_id is not None:
        rows = [r for r in rows if r["election_round_id"] == election_round_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.list_response(rows)


@bp.route(BASE + "/<sid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_session(user_id, role, sid):
    return common.one(gates.must_exist("poll_sessions", sid))


@bp.route(BASE + "/<sid>/designate-observer", methods=["POST"])
@auth.endpoint([auth.DIRECTOR, auth.UNION, auth.BOARD])
def designate_observer(user_id, role, sid):
    schema = validate.Schema(validate.body())
    party = schema.enum("party", common.PARTIES)
    observer_name = schema.string("observer_name")
    supervisor_id = schema.reference("supervisor_id", required=False)

    session = gates.must_exist("poll_sessions", sid)
    supervisor = None
    if supervisor_id is not None:
        supervisor = gates.must_exist("supervisors", supervisor_id)
        petition = store.petition_of_session(session)
        if petition is not None:
            gates.require_same_petition(petition["id"], supervisor["petition_id"])

    if supervisor is not None and supervisor.get("has_hire_fire_authority"):
        raise ApiError("ERR_SUPERVISOR_OBSERVER_PROHIBITED",
                       "A supervisor holding Section 2(11) authority may never be seated.")

    field = "employer_observer_count" if party == "EMPLOYER" else "union_observer_count"
    if session[field] >= calc.MAX_OBSERVERS_PER_PARTY:
        raise ApiError("ERR_OBSERVER_CAPACITY_EXCEEDED",
                       "That party already seats the maximum number of observers.")

    session[field] += 1
    session["observer_roster"] = list(session["observer_roster"]) + [{
        "party": party,
        "observer_name": observer_name,
        "supervisor_id": supervisor_id,
    }]
    store.touch(session)
    return common.one(session)


@bp.route(BASE + "/<sid>/close", methods=["POST"])
@auth.endpoint([auth.BOARD])
def close_session(user_id, role, sid):
    schema = validate.Schema(validate.body())
    votes_for = schema.integer("votes_for_count", minimum=0)
    votes_against = schema.integer("votes_against_count", minimum=0)
    void_count = schema.integer("void_count", minimum=0)

    session = gates.must_exist("poll_sessions", sid)
    rnd = store.round_of_session(session)
    petition = store.petition_of_session(session)

    if petition is not None:
        gates.require_open_posture(petition)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_POLL_SESSION_STATUS_INVALID",
                       "Only a SCHEDULED session may be closed.")
    if rnd is None or rnd["status"] != "POLLS_OPEN":
        raise ApiError("ERR_ROUND_STATUS_INVALID",
                       "The session's round must have its polls open.")
    session_end_at = clockutil.parse_dt(session.get("session_end_at"))
    if session_end_at is not None and clockutil.now() < session_end_at:
        raise ApiError("ERR_POLL_SESSION_STATUS_INVALID",
                       "The logical clock has not reached session_end_at.")
    if (session["employer_observer_count"] > calc.MAX_OBSERVERS_PER_PARTY
            or session["union_observer_count"] > calc.MAX_OBSERVERS_PER_PARTY):
        raise ApiError("ERR_OBSERVER_CAPACITY_EXCEEDED",
                       "A party seats more observers than the statutory cap allows.")

    session["votes_for_count"] = votes_for
    session["votes_against_count"] = votes_against
    session["void_count"] = void_count
    session["status"] = "CLOSED"
    session["closed_at"] = clockutil.now_dt_str()
    store.touch(session)

    rnd["closed_session_count"] += 1
    rnd["scheduled_session_count"] -= 1

    if rnd["scheduled_session_count"] == 0 and rnd["closed_session_count"] >= 1:
        closed = [s for s in store.sessions_of(rnd["id"]) if s["status"] == "CLOSED"]
        rnd["provisional_votes_for"] = sum(s["votes_for_count"] for s in closed)
        rnd["provisional_votes_against"] = sum(s["votes_against_count"] for s in closed)
        rnd["provisional_void_count"] = sum(s["void_count"] for s in closed)
        rnd["ballots_cast_total"] = (
            sum(s["votes_for_count"] + s["votes_against_count"] + s["void_count"]
                for s in closed)
            + sum(s["challenged_ballot_count"] for s in store.sessions_of(rnd["id"])))
        rnd["status"] = "POLLS_CLOSED"
        gates.check_ballot_conservation(rnd)
        store.touch(rnd)
        if petition is not None:
            petition["case_status"] = "VOTING_CLOSED"
            store.touch(petition)
    else:
        store.touch(rnd)

    return common.one(session)
