"""Clinical criteria submissions and reviews (PRD 3.3)."""
from flask import Blueprint

from db import db, next_seq, touch
from errors import raise_error, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES
from middleware import authorized
from response import success_object
from routes.helpers import get_request, get_submission, check_request_not_terminal, list_response
from serializers import serialize
from util import new_id, CLOCK
from validate import get_body, req_str, req_enum

bp = Blueprint("criteria", __name__)


@bp.post("/infusion/authorization-requests/<rid>/criteria-submissions")
def create_submission(rid):
    caller = authorized(["AuthCoordinator"])
    body = get_body()
    criterion_code = req_str(body, "criterion_code")
    response_value = req_str(body, "response_value")

    req = get_request(rid)
    check_request_not_terminal(req)
    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "authorization_request_id": req["id"],
        "criterion_code": criterion_code,
        "response_value": response_value,
        "status": "SUBMITTED",
        "created_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["criteria_submissions"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests/<rid>/criteria-submissions")
def list_submissions(rid):
    authorized(["AuthCoordinator", "MedicalDirector"])
    get_request(rid)
    items = [c for c in db["criteria_submissions"].values()
             if c["authorization_request_id"] == rid]
    return list_response(items)


@bp.post("/infusion/criteria-submissions/<sid>/reviews")
def review_submission(sid):
    caller = authorized(["MedicalDirector"])
    body = get_body()
    outcome = req_enum(body, "outcome", ["ACCEPTED", "REJECTED"])

    submission = get_submission(sid)
    # segregation of duties: reviewer != filer
    if caller.user_id == submission["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the submission creator may not review it")
    if submission["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"criteria submission is {submission['status']}, not SUBMITTED")

    submission["status"] = outcome
    submission["reviewed_by_user_id"] = caller.user_id
    touch(submission, CLOCK.now())
    return success_object(serialize(submission))
