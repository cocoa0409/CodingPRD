"""Election rounds: reads, opening the polls, and the provisional / revised tallies."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("rounds", __name__)

BASE = "/labor-relations/election-rounds"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)


def session_ballot_total(rnd):
    """Every ballot that entered the box across the round (PRD 3.8)."""
    total = 0
    for session in store.sessions_of(rnd["id"]):
        if session["status"] == "CLOSED":
            total += (session["votes_for_count"] + session["votes_against_count"]
                      + session["void_count"])
        total += session["challenged_ballot_count"]
    return total


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_rounds(user_id, role):
    petition_id = validate.query_string("petition_id")
    agreement_id = validate.query_string("election_agreement_id")
    prior_round_id = validate.query_string("prior_round_id")
    status = validate.query_enum("status", common.ROUND_STATUSES)
    rows = store.ordered("election_rounds")
    if petition_id is not None:
        rows = [r for r in rows if r["petition_id"] == petition_id]
    if agreement_id is not None:
        rows = [r for r in rows if r.get("election_agreement_id") == agreement_id]
    if prior_round_id is not None:
        rows = [r for r in rows if r.get("prior_round_id") == prior_round_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.list_response(rows)


@bp.route(BASE + "/<rid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_round(user_id, role, rid):
    return common.one(gates.must_exist("election_rounds", rid))


@bp.route(BASE + "/<rid>/open-polls", methods=["POST"])
@auth.endpoint([auth.BOARD])
def open_polls(user_id, role, rid):
    validate.body()
    rnd = gates.must_exist("election_rounds", rid)
    petition = store.petition(rnd["petition_id"])

    gates.require_open_posture(petition)
    if rnd["status"] != "SCHEDULED":
        raise ApiError("ERR_ROUND_NOT_SCHEDULED",
                       "Only a SCHEDULED round may have its polls opened.")

    accepted = [vl for vl in store.voter_lists_of(petition["id"]) if vl["status"] == "ACCEPTED"]
    if not accepted:
        raise ApiError("ERR_VOTER_LIST_NOT_ACCEPTED",
                       "The case holds no voter list in ACCEPTED status.")
    if rnd["scheduled_session_count"] < 1:
        raise ApiError("ERR_ROUND_STATUS_INVALID",
                       "At least one polling session must be scheduled on the round.")
    polls_open_at = clockutil.parse_dt(rnd.get("polls_open_at"))
    if polls_open_at is not None and clockutil.now() < polls_open_at:
        raise ApiError("ERR_POLLS_NOT_YET_OPEN",
                       "The logical clock has not reached polls_open_at.")

    rnd["status"] = "POLLS_OPEN"
    store.touch(rnd)
    return common.one(rnd)


@bp.route(BASE + "/<rid>/post-tally", methods=["POST"])
@auth.endpoint([auth.BOARD])
def post_tally(user_id, role, rid):
    validate.body()
    rnd = gates.must_exist("election_rounds", rid)
    petition = store.petition(rnd["petition_id"])

    gates.require_open_posture(petition)
    if rnd["status"] != "POLLS_CLOSED":
        raise ApiError("ERR_ROUND_STATUS_INVALID",
                       "Only a POLLS_CLOSED round may have its provisional tally posted.")
    if rnd["ballots_impounded"]:
        raise ApiError("ERR_BALLOTS_IMPOUNDED",
                       "The ballots are impounded while a blocking charge is pending.")
    if session_ballot_total(rnd) != rnd["ballots_cast_total"]:
        raise ApiError("ERR_TALLY_RECONCILIATION_FAILED",
                       "The closed sessions' ballot counts do not reconcile with "
                       "ballots_cast_total.")

    now = clockutil.now()
    votes_for = rnd["provisional_votes_for"]
    votes_against = rnd["provisional_votes_against"]
    rnd["provisional_margin"] = votes_for - votes_against
    valid = votes_for + votes_against
    rnd["valid_votes_cast"] = valid
    rnd["majority_threshold"] = calc.majority_threshold(valid)
    rnd["determinative_challenges"] = (
        rnd["challenged_open_count"] >= abs(rnd["provisional_margin"]))
    rnd["tally_posted_at"] = clockutil.fmt_dt(now)
    rnd["objection_window_close_at"] = clockutil.fmt_dt(clockutil.business_deadline(
        now.date(), calc.OBJECTION_WINDOW_BUSINESS_DAYS))
    rnd["status"] = "TALLY_POSTED"
    store.touch(rnd)

    petition["case_status"] = "TALLY_POSTED"
    store.touch(petition)
    return common.one(rnd)


@bp.route(BASE + "/<rid>/revise-tally", methods=["POST"])
@auth.endpoint([auth.BOARD])
def revise_tally(user_id, role, rid):
    validate.body()
    rnd = gates.must_exist("election_rounds", rid)
    petition = store.petition(rnd["petition_id"])

    gates.require_open_posture(petition)
    if rnd["status"] not in ("TALLY_POSTED", "TALLY_REVISED"):
        raise ApiError("ERR_ROUND_STATUS_INVALID",
                       "Only a posted or already revised tally may be revised.")
    if rnd["challenged_open_count"] != 0:
        raise ApiError("ERR_CHALLENGES_UNRESOLVED",
                       "Every challenged ballot must be resolved before the tally is revised.")

    revised_for = rnd["provisional_votes_for"] + rnd["challenged_counted_for_count"]
    revised_against = rnd["provisional_votes_against"] + rnd["challenged_counted_against_count"]
    revised_void = rnd["provisional_void_count"] + rnd["challenged_voided_count"]
    rnd["revised_votes_for"] = revised_for
    rnd["revised_votes_against"] = revised_against
    rnd["revised_void_count"] = revised_void
    rnd["revised_margin"] = revised_for - revised_against
    valid = revised_for + revised_against
    rnd["valid_votes_cast"] = valid
    rnd["majority_threshold"] = calc.majority_threshold(valid)
    # determinative_challenges is a historical finding about the provisional margin and
    # objection_window_close_at still runs from the provisional posting date: neither moves.
    rnd["tally_revised_at"] = clockutil.now_dt_str()
    rnd["status"] = "TALLY_REVISED"
    gates.check_ballot_conservation(rnd)
    store.touch(rnd)
    return common.one(rnd)
