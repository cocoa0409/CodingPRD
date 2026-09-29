"""The multidisciplinary surgical candidacy conference."""
import cascade
import clock
import config
import derive
import response
import validation
from db import base_record, db, insert
from errors import ApiError
from web import (ListResult, ObjectResult, bp, endpoint, get_admission, get_case,
                 get_export)

CASE_READ_ROLES = ("UnitCoordinator", "Epileptologist")


@bp.route("/neurodiagnostics/conference-cases", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def create_case(user_id, role):
    data = validation.body()
    admission_id = validation.req_id(data, "admission_id")
    export_id = validation.req_id(data, "export_id")
    get_admission(admission_id)
    get_export(export_id)
    case = base_record("case")
    case.update({
        "admission_id": admission_id,
        "export_id": export_id,
        "status": "DRAFT",
        "presenter_user_id": None,
        "defer_round": 0,
        "eligible_vote_count": 0,
        "candidate_votes": 0,
        "non_candidate_votes": 0,
        "defer_votes": 0,
        "distinct_specialty_count": 0,
        "quorum_met": False,
        "decision_at": None,
    })
    insert("cases", case)
    return ObjectResult(case, 201)


@bp.route("/neurodiagnostics/conference-cases", methods=["GET"])
@endpoint(roles=CASE_READ_ROLES)
def list_cases(user_id, role):
    from flask import request
    args = request.args
    limit, offset = response.read_pagination(args)
    admission_id = validation.query_string(args, "admission_id")
    export_id = validation.query_string(args, "export_id")
    status = validation.query_enum(args, "status", config.CASE_STATUSES)
    records = []
    for case in db.cases.values():
        if admission_id and case["admission_id"] != admission_id:
            continue
        if export_id and case["export_id"] != export_id:
            continue
        if status and case["status"] != status:
            continue
        records.append(case)
    return ListResult(derive.ordered(records), limit, offset)


@bp.route("/neurodiagnostics/conference-cases/<case_id>", methods=["GET"])
@endpoint(roles=CASE_READ_ROLES)
def read_case(user_id, role, case_id):
    return ObjectResult(get_case(case_id))


@bp.route("/neurodiagnostics/conference-cases/<case_id>/present", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def present_case(user_id, role, case_id):
    case = get_case(case_id)
    # rung 6
    if case["status"] not in ("DRAFT", "DEFERRED"):
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "Only a DRAFT or DEFERRED case may be presented.")
    # rung 18 — the conference reviews delivered data only
    package = db.exports.get(case["export_id"])
    if package is None or package["status"] != "DELIVERED":
        raise ApiError("ERR_EXPORT_NOT_DELIVERED",
                       "The referenced export package is not DELIVERED.")
    # rung 23 — round cap on re-presentation
    if (case["status"] == "DEFERRED"
            and case["defer_round"] >= config.MAX_DEFER_ROUNDS):
        raise ApiError("ERR_DEFER_LIMIT", "The deferral limit for this case is reached.")
    case["status"] = "PRESENTED"
    case["presenter_user_id"] = user_id
    derive.apply_case_tally(case)
    return ObjectResult(case)


@bp.route("/neurodiagnostics/conference-cases/<case_id>/votes", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def cast_vote(user_id, role, case_id):
    data = validation.body()
    specialty = validation.req_enum(data, "specialty", config.SPECIALTIES)
    choice = validation.req_enum(data, "vote", config.VOTES)
    rationale = validation.opt_string(data, "rationale")
    case = get_case(case_id)
    # rung 6
    if case["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "Ballots may only be cast on a PRESENTED case.")
    # rung 24 — one ballot per operator per round
    for existing in derive.votes_of_case(case["id"]):
        if (existing["voter_user_id"] == user_id
                and existing["round_index"] == case["defer_round"]):
            raise ApiError("ERR_DUPLICATE_VOTE",
                           "This operator has already voted in the current round.")
    vote = base_record("vote", full_preamble=False)
    vote.update({
        "case_id": case["id"],
        "voter_user_id": user_id,
        "specialty": specialty,
        "vote": choice,
        "rationale": rationale,
        "counted": user_id != case.get("presenter_user_id"),
        "round_index": case["defer_round"],
    })
    insert("votes", vote)
    derive.apply_case_tally(case)
    return ObjectResult(vote, 201)


@bp.route("/neurodiagnostics/conference-cases/<case_id>/votes", methods=["GET"])
@endpoint(roles=CASE_READ_ROLES)
def list_case_votes(user_id, role, case_id):
    from flask import request
    get_case(case_id)
    limit, offset = response.read_pagination(request.args)
    return ListResult(derive.ordered(derive.votes_of_case(case_id)), limit, offset)


@bp.route("/neurodiagnostics/conference-cases/<case_id>/close-vote", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def close_vote(user_id, role, case_id):
    case = get_case(case_id)
    # rung 6
    if case["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "Only a PRESENTED case may have its round closed.")
    derive.apply_case_tally(case)
    # T1 / rung 25 — quorum
    if not case["quorum_met"]:
        raise ApiError("ERR_QUORUM_NOT_MET", "The voting round has not met quorum.")
    candidate = case["candidate_votes"]
    non_candidate = case["non_candidate_votes"]
    defer = case["defer_votes"]
    # T2 — a deferral plurality wins ties against both other options
    if defer >= candidate and defer >= non_candidate:
        outcome = "DEFERRED"
    # T3
    elif candidate > non_candidate:
        outcome = "CANDIDATE"
    # T4
    elif non_candidate > candidate:
        outcome = "NON_CANDIDATE"
    # T5 — an exact candidate/non-candidate tie above the defer count
    else:
        outcome = "DEFERRED"

    if outcome == "DEFERRED":
        case["status"] = "DEFERRED"
        case["defer_round"] += 1
    else:
        case["status"] = outcome
        case["decision_at"] = clock.now()
    return ObjectResult(case)
