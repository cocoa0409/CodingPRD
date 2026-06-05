"""SatisfactionSurvey endpoints (PRD §3.10): get, list, respond."""
from flask import Blueprint, request as flask_request

import db
import errors
import validate
import serialize
from middleware import authenticate, authorize
import response

bp = Blueprint("surveys", __name__)


@bp.route("/surveys/<sid>", methods=["GET"])
def get_survey(sid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Citizen"})
    rec = db.surveys.get(sid)
    if rec is None:
        raise errors.not_found("Survey not found.")
    return response.object_response(serialize.view("survey", rec))


@bp.route("/surveys", methods=["GET"])
def list_surveys():
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Citizen"})
    limit, offset = validate.pagination()
    args = flask_request.args
    f_request = args.get("request_id")
    f_status = args.get("status")

    def pred(r):
        if f_request is not None and r["request_id"] != f_request:
            return False
        if f_status is not None and r["status"] != f_status:
            return False
        return True

    rows = db.ordered(db.surveys, pred)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("survey", page), limit, offset, total)


@bp.route("/surveys/<sid>/respond", methods=["POST"])
def respond(sid):
    p = authenticate()
    authorize(p, {"Citizen"})
    survey = db.surveys.get(sid)
    if survey is None:
        raise errors.not_found("Survey not found.")

    req = db.service_requests.get(survey["request_id"])
    # priority 4: ownership.
    if req is None or req["citizen_id"] != p.user_id:
        raise errors.not_resource_owner()

    # priority 6: state.
    if survey["status"] != "SENT":
        raise errors.invalid_state("Survey is not SENT.")

    data = validate.body()
    # priority 17: score must be an integer in [1,5].
    if "score" not in data or data["score"] is None:
        raise errors.invalid_score()
    score = data["score"]
    if isinstance(score, bool) or not isinstance(score, int) or score < 1 or score > 5:
        raise errors.invalid_score()
    comment = validate.opt_str(data, "comment", None)

    survey["score"] = score
    survey["comment"] = comment
    survey["status"] = "COMPLETED"
    db.touch(survey)
    return response.object_response(serialize.view("survey", survey))
