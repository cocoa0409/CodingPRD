"""Election arrangements: the stipulated branch and the hearing branch."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("agreements", __name__)

BASE = "/labor-relations/election-agreements"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def create_agreement(user_id, role):
    schema = validate.Schema(validate.body())
    petition_id = schema.reference("petition_id")
    agreement_type = schema.enum("agreement_type", common.AGREEMENT_TYPES)
    proposed_election_date = schema.date("proposed_election_date")
    proposed_voting_method = schema.enum("proposed_voting_method", common.VOTING_METHODS)

    gates.must_exist("petitions", petition_id)
    for existing in store.agreements_of(petition_id):
        if existing["status"] != "VOID":
            raise ApiError("ERR_DUPLICATE_ELECTION_AGREEMENT",
                           "The case already holds an arrangement that is not VOID.")

    row = store.insert("election_agreements", {
        "petition_id": petition_id,
        "agreement_type": agreement_type,
        "proposed_election_date": proposed_election_date,
        "proposed_voting_method": proposed_voting_method,
        "status": "PROPOSED",
        "route": "PENDING",
        "approved_election_date": None,
        "voting_method": None,
        "polls_open_at": None,
        "polls_close_at": None,
        "hearing_requested_at": None,
        "hearing_requested_by_party": None,
        "decision_date": None,
        "voter_list_due_at": None,
    })
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_agreements(user_id, role):
    petition_id = validate.query_string("petition_id")
    status = validate.query_enum("status", common.AGREEMENT_STATUSES)
    rows = store.ordered("election_agreements")
    if petition_id is not None:
        rows = [r for r in rows if r["petition_id"] == petition_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.list_response(rows)


@bp.route(BASE + "/<aid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_agreement(user_id, role, aid):
    return common.one(gates.must_exist("election_agreements", aid))


def _fix_election(agreement, petition, voting_method, approved_election_date,
                  polls_open_at, polls_close_at, route, due_anchor_date):
    agreement["approved_election_date"] = approved_election_date
    agreement["voting_method"] = voting_method
    agreement["polls_open_at"] = polls_open_at
    agreement["polls_close_at"] = polls_close_at
    agreement["route"] = route
    agreement["voter_list_due_at"] = clockutil.fmt_dt(
        clockutil.business_deadline(due_anchor_date, calc.VOTER_LIST_BUSINESS_DAYS))
    gates.create_election_round(petition, agreement, 1, None, voting_method,
                               approved_election_date, polls_open_at, polls_close_at)
    petition["case_status"] = "ELECTION_SET"
    store.touch(agreement)
    store.touch(petition)


@bp.route(BASE + "/<aid>/stipulate", methods=["POST"])
@auth.endpoint([auth.BOARD])
def stipulate(user_id, role, aid):
    schema = validate.Schema(validate.body())
    approved_election_date = schema.date("approved_election_date")
    voting_method = schema.enum("voting_method", common.VOTING_METHODS)
    polls_open_at = schema.datetime("polls_open_at")
    polls_close_at = schema.datetime("polls_close_at")
    validate.time_window(polls_open_at, polls_close_at)

    agreement = gates.must_exist("election_agreements", aid)
    petition = store.petition(agreement["petition_id"])
    gates.require_open_posture(petition)
    if agreement["status"] != "PROPOSED":
        raise ApiError("ERR_AGREEMENT_STATUS_INVALID",
                       "Only a PROPOSED arrangement may be stipulated.")
    if petition["case_status"] != "SOI_VERIFIED" or petition["showing_verdict"] != "SUFFICIENT":
        raise ApiError("ERR_PETITION_STATUS_INVALID",
                       "The case must be SOI_VERIFIED with a SUFFICIENT showing.")

    agreement["status"] = "STIPULATED_APPROVED"
    _fix_election(agreement, petition, voting_method, approved_election_date,
                  polls_open_at, polls_close_at, "STIPULATED", clockutil.now().date())
    return common.one(agreement)


@bp.route(BASE + "/<aid>/request-hearing", methods=["POST"])
@auth.endpoint([auth.DIRECTOR, auth.UNION])
def request_hearing(user_id, role, aid):
    schema = validate.Schema(validate.body())
    party = schema.enum("hearing_requested_by_party", common.PARTIES)
    agreement = gates.must_exist("election_agreements", aid)
    petition = store.petition(agreement["petition_id"])
    if agreement["status"] != "PROPOSED":
        raise ApiError("ERR_AGREEMENT_STATUS_INVALID",
                       "Only a PROPOSED arrangement may be taken to hearing.")
    if petition["case_status"] != "SOI_VERIFIED":
        raise ApiError("ERR_PETITION_STATUS_INVALID", "The case must be SOI_VERIFIED.")

    agreement["status"] = "HEARING_REQUESTED"
    agreement["hearing_requested_at"] = clockutil.now_dt_str()
    agreement["hearing_requested_by_party"] = party
    store.touch(agreement)
    return common.one(agreement)


@bp.route(BASE + "/<aid>/direct-election", methods=["POST"])
@auth.endpoint([auth.BOARD])
def direct_election(user_id, role, aid):
    schema = validate.Schema(validate.body())
    decision_date = schema.date("decision_date")
    approved_election_date = schema.date("approved_election_date")
    voting_method = schema.enum("voting_method", common.VOTING_METHODS)
    polls_open_at = schema.datetime("polls_open_at")
    polls_close_at = schema.datetime("polls_close_at")
    validate.time_window(polls_open_at, polls_close_at)

    agreement = gates.must_exist("election_agreements", aid)
    petition = store.petition(agreement["petition_id"])
    gates.require_open_posture(petition)
    if agreement["status"] != "HEARING_REQUESTED":
        raise ApiError("ERR_AGREEMENT_STATUS_INVALID",
                       "Only an arrangement in HEARING_REQUESTED may be directed.")
    if petition["case_status"] != "SOI_VERIFIED":
        raise ApiError("ERR_PETITION_STATUS_INVALID", "The case must be SOI_VERIFIED.")
    for classification in store.classifications_of(petition["id"]):
        if classification["scope_ruling"] == "PENDING":
            raise ApiError("ERR_SCOPE_RULINGS_INCOMPLETE",
                           "Every classification must be ruled before the election is directed.")

    agreement["status"] = "DIRECTED"
    agreement["decision_date"] = decision_date
    _fix_election(agreement, petition, voting_method, approved_election_date,
                  polls_open_at, polls_close_at, "DIRECTED",
                  clockutil.parse_date(decision_date))
    return common.one(agreement)
