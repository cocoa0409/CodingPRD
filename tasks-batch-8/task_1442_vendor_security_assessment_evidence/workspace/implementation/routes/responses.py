"""QuestionnaireResponse lifecycle (PRD §3.4): DRAFT -> SUBMITTED ->
RETURNED -> ... -> ACCEPTED, the deadline guard, and pinned-template
completeness checks.
"""
from flask import Blueprint

import db
import errors
import helpers
import util
from errors import ApiError
from middleware import body, require_roles, scope_vendor_or_403
from response import ok
from serializers import serialize

bp = Blueprint("responses", __name__, url_prefix="/vsa/vendors/<vid>/cycles/<cid>/responses")

ANSWER_VALUES = ("YES", "PARTIAL", "NO", "NA")


def _resolve(vid, cid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    cycle = helpers.get_cycle_for_vendor(vendor, cid)
    return vendor, cycle


def _pinned_template(cycle):
    return db.templates.get(cycle.get("template_id"))


@bp.post("")
@require_roles("VendorContact")
def create_response(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Responses can only be drafted against an ISSUED cycle")
    data = body()
    submitted_by = data.get("submitted_by")
    answers = data.get("answers")
    if not isinstance(submitted_by, str) or not submitted_by:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "submitted_by is required")
    if not isinstance(answers, list):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "answers must be a list")
    template = _pinned_template(cycle)
    known_keys = {i.get("item_key") for i in (template or {}).get("items", [])}
    for ans in answers:
        if not isinstance(ans, dict):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "each answer must be an object")
        if ans.get("item_key") not in known_keys:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "item_key %r is not in the pinned template"
                           % ans.get("item_key"))
        if ans.get("answer_value") not in ANSWER_VALUES:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "answer_value must be one of %s" % (ANSWER_VALUES,))
    response = {
        "cycle_id": cid,
        "submitted_by": submitted_by,
        "answers": answers,
        "status": "DRAFT",
        "submitted_at": None,
        "raw_score": None,
        "revision_count": 0,
    }
    helpers.stamp_new("responses", response)
    db.responses[response["id"]] = response
    return ok(serialize("response", response), 201)


@bp.post("/<rid>/submit")
@require_roles("VendorContact")
def submit_response(vid, cid, rid):
    vendor, cycle = _resolve(vid, cid)
    response = helpers.get_child(db.responses, "cycle_id", cycle, rid,
                                 "QuestionnaireResponse")
    first_submission = response["status"] == "DRAFT"
    if first_submission:
        if cycle["status"] != "ISSUED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Cycle is not ISSUED")
    elif response["status"] == "RETURNED":
        if cycle["status"] != "RESPONSE_RECEIVED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Cycle is not awaiting resubmission")
    else:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Response in status %s cannot be submitted" % response["status"])
    # Deadline (priority 7): first submission must arrive by response_due_at.
    if first_submission and cycle.get("response_due_at"):
        if util.now() > util.parse_dt(cycle["response_due_at"]):
            raise ApiError(errors.ERR_DEADLINE_PASSED, 422,
                           "response_due_at has passed")
    # Completeness (priority 16): every pinned-template item answered or
    # carried by an na_justification.
    template = _pinned_template(cycle)
    answers = {a.get("item_key"): a for a in response.get("answers", [])}
    for item in (template or {}).get("items", []):
        ans = answers.get(item.get("item_key"))
        if ans is None:
            raise ApiError(errors.ERR_RESPONSE_INCOMPLETE, 422,
                           "Item %s is unanswered" % item.get("item_key"))
        justified = bool(ans.get("na_justification"))
        if ans.get("answer_value") in (None, "NA") and not justified:
            raise ApiError(errors.ERR_RESPONSE_INCOMPLETE, 422,
                           "Item %s is unanswered and lacks na_justification"
                           % item.get("item_key"))
    response["status"] = "SUBMITTED"
    if first_submission:
        response["submitted_at"] = util.iso(util.now())
        cycle["status"] = "RESPONSE_RECEIVED"
        helpers.touch("cycles", cycle)
    helpers.touch("responses", response)
    return ok(serialize("response", response))


@bp.post("/<rid>/return")
@require_roles("RiskAnalyst")
def return_response(vid, cid, rid):
    vendor, cycle = _resolve(vid, cid)
    response = helpers.get_child(db.responses, "cycle_id", cycle, rid,
                                 "QuestionnaireResponse")
    if response["status"] != "SUBMITTED" or cycle["status"] != "RESPONSE_RECEIVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED response on a RESPONSE_RECEIVED cycle "
                       "can be returned")
    response["status"] = "RETURNED"
    response["revision_count"] += 1
    helpers.touch("responses", response)
    return ok(serialize("response", response))
