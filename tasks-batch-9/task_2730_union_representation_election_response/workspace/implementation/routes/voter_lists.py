"""Eligible voter lists: opening, attesting, grading, Board review and curing."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("voter_lists", __name__)

BASE = "/labor-relations/voter-lists"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.DIRECTOR, auth.ANALYST])
def create_voter_list(user_id, role):
    schema = validate.Schema(validate.body())
    petition_id = schema.reference("petition_id")
    election_agreement_id = schema.reference("election_agreement_id")
    expected_petition_version = schema.integer("expected_petition_version")

    petition = gates.must_exist("petitions", petition_id)
    agreement = gates.must_exist("election_agreements", election_agreement_id)

    if expected_petition_version != petition["version"]:
        raise ApiError("ERR_STALE_PETITION_VERSION",
                       "The asserted petition version does not match the current version.")
    gates.require_same_petition(petition_id, agreement["petition_id"])

    for existing in store.voter_lists_of(petition_id):
        if existing["status"] in ("SUBMITTED", "ACCEPTED"):
            raise ApiError("ERR_DUPLICATE_VOTER_LIST",
                           "The case already holds a list that has been filed.")
    for existing in store.voter_lists_of(petition_id):
        if existing["status"] in ("DRAFT", "DEFICIENT"):
            existing["status"] = "SUPERSEDED"
            store.touch(existing)

    row = store.insert("voter_lists", {
        "petition_id": petition_id,
        "election_agreement_id": election_agreement_id,
        "status": "DRAFT",
        "due_at": agreement.get("voter_list_due_at"),
        "submitted_at": None,
        "submitted_by_user_id": None,
        "attested_by_title": None,
        "total_entry_count": 0,
        "complete_entry_count": 0,
        "completeness_pct": None,
        "is_late": False,
        "list_grade": None,
        "cure_window_hours": None,
        "cure_deadline_at": None,
        "reviewed_at": None,
        "noted_defects": None,
        "resubmission_count": 0,
        "eligible_voter_count": 0,
    })
    store.touch(petition)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_voter_lists(user_id, role):
    petition_id = validate.query_string("petition_id")
    election_agreement_id = validate.query_string("election_agreement_id")
    status = validate.query_enum("status", common.VOTER_LIST_STATUSES)
    rows = store.ordered("voter_lists")
    if petition_id is not None:
        rows = [r for r in rows if r["petition_id"] == petition_id]
    if election_agreement_id is not None:
        rows = [r for r in rows if r["election_agreement_id"] == election_agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.list_response(rows)


@bp.route(BASE + "/<lid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_voter_list(user_id, role, lid):
    return common.one(gates.must_exist("voter_lists", lid))


@bp.route(BASE + "/<lid>/submit", methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def submit_voter_list(user_id, role, lid):
    schema = validate.Schema(validate.body())
    attested_by_title = schema.string("attested_by_title")
    late_ack = schema.boolean("late_submission_ack", required=False, default=False)

    voter_list = gates.must_exist("voter_lists", lid)
    petition = store.petition(voter_list["petition_id"])
    gates.require_open_posture(petition)
    if voter_list["status"] != "DRAFT":
        raise ApiError("ERR_VOTER_LIST_STATUS_INVALID",
                       "Only a DRAFT list may be filed.")
    if petition["case_status"] != "ELECTION_SET":
        raise ApiError("ERR_PETITION_STATUS_INVALID", "The case must be in ELECTION_SET.")
    gates.recount_list(voter_list)
    if voter_list["total_entry_count"] < 1:
        raise ApiError("ERR_VOTER_LIST_EMPTY", "A list with no entries cannot be graded.")

    now = clockutil.now()
    due_at = clockutil.parse_dt(voter_list.get("due_at"))
    if not late_ack and due_at is not None and now > due_at:
        raise ApiError("ERR_VOTER_LIST_PAST_DUE",
                       "The filing deadline has passed and no late acknowledgement was supplied.")

    voter_list["status"] = "SUBMITTED"
    voter_list["submitted_at"] = clockutil.fmt_dt(now)
    voter_list["submitted_by_user_id"] = user_id
    voter_list["attested_by_title"] = attested_by_title
    gates.grade_list(voter_list)
    store.touch(voter_list)
    return common.one(voter_list)


@bp.route(BASE + "/<lid>/resubmit", methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def resubmit_voter_list(user_id, role, lid):
    schema = validate.Schema(validate.body())
    attested_by_title = schema.string("attested_by_title")

    voter_list = gates.must_exist("voter_lists", lid)
    if voter_list["status"] != "DEFICIENT":
        raise ApiError("ERR_VOTER_LIST_STATUS_INVALID",
                       "Only a DEFICIENT list may be resubmitted.")
    now = clockutil.now()
    cure_deadline = clockutil.parse_dt(voter_list.get("cure_deadline_at"))
    if cure_deadline is not None and now > cure_deadline:
        raise ApiError("ERR_CURE_WINDOW_EXPIRED", "The cure window has expired.")
    if voter_list["resubmission_count"] >= calc.MAX_LIST_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_EXCEEDED",
                       "The cure resubmission ceiling has been reached.")

    voter_list["resubmission_count"] += 1
    voter_list["submitted_at"] = clockutil.fmt_dt(now)
    voter_list["submitted_by_user_id"] = user_id
    voter_list["attested_by_title"] = attested_by_title
    voter_list["status"] = "SUBMITTED"
    gates.grade_list(voter_list)
    store.touch(voter_list)
    return common.one(voter_list)


@bp.route(BASE + "/<lid>/review", methods=["POST"])
@auth.endpoint([auth.BOARD])
def review_voter_list(user_id, role, lid):
    schema = validate.Schema(validate.body())
    disposition = schema.enum("disposition", common.LIST_DISPOSITIONS)
    noted_defects = schema.string_list("noted_defects", required=False, default=None)

    voter_list = gates.must_exist("voter_lists", lid)
    petition = store.petition(voter_list["petition_id"])
    gates.require_open_posture(petition)
    if voter_list["status"] != "SUBMITTED":
        raise ApiError("ERR_VOTER_LIST_STATUS_INVALID", "Only a SUBMITTED list may be reviewed.")

    grade = voter_list["list_grade"]
    now = clockutil.now()
    reviewed_at = clockutil.fmt_dt(now)

    if disposition == "ACCEPT":
        if grade not in ("COMPLIANT", "MINOR_DEFECT"):
            raise ApiError("ERR_VOTER_LIST_STATUS_INVALID",
                           "A list graded %s may not be accepted." % grade)
        voter_list["status"] = "ACCEPTED"
        voter_list["reviewed_at"] = reviewed_at
        if noted_defects is not None:
            voter_list["noted_defects"] = noted_defects
    elif disposition == "RETURN_FOR_CURE":
        if grade not in ("MINOR_DEFECT", "MATERIAL_DEFECT"):
            raise ApiError("ERR_VOTER_LIST_STATUS_INVALID",
                           "A list graded %s may not be returned for cure." % grade)
        hours = calc.cure_hours_for(grade)
        voter_list["status"] = "DEFICIENT"
        voter_list["reviewed_at"] = reviewed_at
        voter_list["noted_defects"] = noted_defects
        voter_list["cure_window_hours"] = hours
        voter_list["cure_deadline_at"] = clockutil.fmt_dt(clockutil.add_hours(now, hours))
    else:
        if grade != "GROSSLY_DEFICIENT":
            raise ApiError("ERR_VOTER_LIST_STATUS_INVALID",
                           "A list graded %s may not be rejected outright." % grade)
        voter_list["status"] = "REJECTED"
        voter_list["reviewed_at"] = reviewed_at
        voter_list["noted_defects"] = noted_defects
        voter_list["cure_window_hours"] = 0

    store.touch(voter_list)
    return common.one(voter_list)
