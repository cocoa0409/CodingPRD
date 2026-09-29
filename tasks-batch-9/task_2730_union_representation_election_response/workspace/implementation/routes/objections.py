"""Objections to the conduct of an election, and the four-hop set-aside cascade."""

from flask import Blueprint

import auth
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("objections", __name__)

BASE = "/labor-relations/objections"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)
TALLY_STATES = ("TALLY_POSTED", "TALLY_REVISED")


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.DIRECTOR, auth.UNION])
def create_objection(user_id, role):
    schema = validate.Schema(validate.body())
    election_round_id = schema.reference("election_round_id")
    related_supervisor_id = schema.reference("related_supervisor_id", required=False)
    filed_by_party = schema.enum("filed_by_party", common.PARTIES)
    ground_code = schema.enum("ground_code", common.OBJECTION_GROUNDS)
    conduct_occurred_at = schema.datetime("conduct_occurred_at")
    alleged_affected_voter_count = schema.integer("alleged_affected_voter_count", minimum=0)
    description = schema.string("description")

    rnd = gates.must_exist("election_rounds", election_round_id)
    if related_supervisor_id is not None:
        gates.must_exist("supervisors", related_supervisor_id)

    if rnd["status"] not in TALLY_STATES:
        raise ApiError("ERR_ROUND_STATUS_INVALID",
                       "An objection may only be filed against a posted or revised tally.")
    window_close = clockutil.parse_dt(rnd.get("objection_window_close_at"))
    if window_close is not None and clockutil.now() > window_close:
        raise ApiError("ERR_OBJECTION_WINDOW_CLOSED",
                       "The objection window on that round has closed.")

    row = {
        "election_round_id": election_round_id,
        "related_supervisor_id": related_supervisor_id,
        "filed_by_party": filed_by_party,
        "ground_code": ground_code,
        "conduct_occurred_at": conduct_occurred_at,
        "alleged_affected_voter_count": alleged_affected_voter_count,
        "description": description,
        "filed_at": clockutil.now_dt_str(),
        "status": "FILED",
        "affects_results": alleged_affected_voter_count >= abs(rnd["provisional_margin"] or 0),
        "rerun_directed": False,
        "disposition_rationale": None,
        "ruled_at": None,
    }
    store.insert("objections", row)

    petition = store.petition(rnd["petition_id"])
    if petition is not None:
        petition["pending_objection_count"] += 1
        if petition["case_status"] == "TALLY_POSTED":
            petition["case_status"] = "OBJECTIONS_PENDING"
        store.touch(petition)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_objections(user_id, role):
    election_round_id = validate.query_string("election_round_id")
    related_supervisor_id = validate.query_string("related_supervisor_id")
    status = validate.query_enum("status", common.OBJECTION_STATUSES)
    rows = store.ordered("objections")
    if election_round_id is not None:
        rows = [r for r in rows if r["election_round_id"] == election_round_id]
    if related_supervisor_id is not None:
        rows = [r for r in rows if r.get("related_supervisor_id") == related_supervisor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.list_response(rows)


@bp.route(BASE + "/<oid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_objection(user_id, role, oid):
    return common.one(gates.must_exist("objections", oid))


@bp.route(BASE + "/<oid>/rule", methods=["POST"])
@auth.endpoint([auth.BOARD])
def rule_objection(user_id, role, oid):
    schema = validate.Schema(validate.body())
    disposition = schema.enum("disposition", common.OBJECTION_DISPOSITIONS)
    rationale = schema.string("disposition_rationale")

    objection = gates.must_exist("objections", oid)
    if objection["status"] != "FILED":
        raise ApiError("ERR_OBJECTION_ALREADY_RULED",
                       "That objection has already been ruled on.")

    rnd = store.get("election_rounds", objection["election_round_id"])
    petition = store.petition(rnd["petition_id"]) if rnd else None

    if disposition == "SUSTAIN":
        if not objection["affects_results"]:
            raise ApiError("ERR_OBJECTION_NOT_DETERMINATIVE",
                           "Conduct that could not have changed the outcome may not set "
                           "an election aside.")
        if rnd is None or rnd["status"] not in TALLY_STATES:
            raise ApiError("ERR_ROUND_STATUS_INVALID",
                           "The objected round must be in a posted or revised tally state.")

        objection["status"] = "SUSTAINED"
        objection["rerun_directed"] = True
        objection["ruled_at"] = clockutil.now_dt_str()
        objection["disposition_rationale"] = rationale
        store.touch(objection)

        rnd["status"] = "SET_ASIDE"
        store.touch(rnd)

        petition["case_status"] = "RERUN_DIRECTED"
        petition["pending_objection_count"] = 0
        store.touch(petition)
        gates.rerun_blackout_cascade(petition)
        return common.one(objection)

    objection["status"] = "OVERRULED"
    objection["ruled_at"] = clockutil.now_dt_str()
    objection["disposition_rationale"] = rationale
    store.touch(objection)

    if petition is not None:
        if petition["pending_objection_count"] > 0:
            petition["pending_objection_count"] -= 1
        sustained = any(o["status"] == "SUSTAINED"
                        for o in store.objections_of_round(objection["election_round_id"]))
        if (petition["pending_objection_count"] == 0 and not sustained
                and petition["case_status"] == "OBJECTIONS_PENDING"):
            petition["case_status"] = "TALLY_POSTED"
        store.touch(petition)
    return common.one(objection)
