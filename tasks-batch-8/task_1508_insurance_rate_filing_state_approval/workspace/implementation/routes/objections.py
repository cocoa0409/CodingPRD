"""Objection and ObjectionResponse routes: the interrogatory/SLA cycle."""
from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from envelope import list_response, serialize, success
from errors import err, ERR_INVALID_STATE, ERR_STALE_VERSION
from fields import OBJECTION, OBJECTION_RESPONSE
from store import db, now, touch
from validate import (
    apply_filters, get_json_body, paginate, v_int, v_string, validate_body,
)
from workflows import (
    base_entity,
    create_calendar_entry,
    entry_mark_met,
    entry_waive,
    find_entries,
    get_or_404,
    recompute_filing_objections,
    _withdraw_objection,
)

bp = Blueprint("objections", __name__)

DRAFTABLE_STATUSES = {"RAISED", "REOPENED", "OVERDUE", "RESPONSE_DRAFTED"}


@bp.route("/objections", methods=["POST"])
def create_objection():
    authenticate({"StateRegulator"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "filing_id": (True, v_string),
        "question_text": (True, v_string),
    })
    with db.lock:
        filing = get_or_404(db.rate_filings, data["filing_id"])
        if filing["status"] not in ("SUBMITTED", "UNDER_OBJECTION"):
            raise err(ERR_INVALID_STATE)
        profile = db.state_profiles.get(filing["profile_id"])
        raised = now()
        due_at = raised + timedelta(days=profile["objection_response_sla_days"])
        objection = base_entity()
        objection.update({
            "filing_id": filing["id"],
            "question_text": data["question_text"],
            "raised_at": raised,
            "due_at": due_at,
            "status": "RAISED",
            "reopen_count": 0,
            "late_breach": False,
            "resolved_at": None,
        })
        db.objections[objection["id"]] = objection
        create_calendar_entry(
            "OBJECTION_RESPONSE_DUE",
            due_at,  # objection deadlines keep their exact timestamp
            filing_id=filing["id"],
            objection_id=objection["id"],
        )
        if filing["status"] == "SUBMITTED":
            filing["status"] = "UNDER_OBJECTION"
            touch(filing)
        recompute_filing_objections(filing)
    return success(serialize(objection, OBJECTION), code=201)


@bp.route("/objections/<objectionId>", methods=["GET"])
def get_objection(objectionId):
    authenticate(ALL_ROLES)
    objection = get_or_404(db.objections, objectionId)
    return success(serialize(objection, OBJECTION), code=200)


@bp.route("/objections", methods=["GET"])
def list_objections():
    authenticate(ALL_ROLES)
    filters = {
        "filing_id": request.args.get("filing_id"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.objections.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(o, OBJECTION) for o in page], total, limit, offset)


@bp.route("/objections/<objectionId>/responses", methods=["POST"])
def draft_response(objectionId):
    user_id, _ = authenticate({"FilingAnalyst"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "response_text": (True, v_string),
        "expected_objection_version": (True, v_int),
    })
    with db.lock:
        objection = get_or_404(db.objections, objectionId)
        # OCC guard: the client's view of the objection must be current
        if data["expected_objection_version"] != objection["version"]:
            raise err(ERR_STALE_VERSION)
        if objection["status"] not in DRAFTABLE_STATUSES:
            raise err(ERR_INVALID_STATE)
        # supersede any prior DRAFT response on this objection
        for r in db.objection_responses.values():
            if r["objection_id"] == objection["id"] and r["status"] == "DRAFT":
                r["status"] = "SUPERSEDED"
                touch(r)
        response = base_entity()
        response.update({
            "objection_id": objection["id"],
            "response_text": data["response_text"],
            "status": "DRAFT",
            "drafted_by_user_id": user_id,
            "submitted_at": None,
        })
        db.objection_responses[response["id"]] = response
        objection["status"] = "RESPONSE_DRAFTED"
        touch(objection)
        filing = db.rate_filings.get(objection["filing_id"])
        if filing is not None:
            recompute_filing_objections(filing)
    return success(serialize(response, OBJECTION_RESPONSE), code=201)


@bp.route("/responses/<responseId>", methods=["GET"])
def get_response(responseId):
    authenticate(ALL_ROLES)
    response = get_or_404(db.objection_responses, responseId)
    return success(serialize(response, OBJECTION_RESPONSE), code=200)


@bp.route("/responses", methods=["GET"])
def list_responses():
    authenticate(ALL_ROLES)
    filters = {
        "objection_id": request.args.get("objection_id"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.objection_responses.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(r, OBJECTION_RESPONSE) for r in page], total, limit, offset)


@bp.route("/responses/<responseId>/submit", methods=["POST"])
def submit_response(responseId):
    authenticate({"ComplianceOfficer"})
    with db.lock:
        response = get_or_404(db.objection_responses, responseId)
        objection = db.objections.get(response["objection_id"])
        # the response must be the objection's live DRAFT
        if (
            response["status"] != "DRAFT"
            or objection is None
            or objection["status"] != "RESPONSE_DRAFTED"
        ):
            raise err(ERR_INVALID_STATE)
        submitted = now()
        response["status"] = "SUBMITTED"
        response["submitted_at"] = submitted
        touch(response)
        objection["status"] = "RESPONSE_SUBMITTED"
        # on time iff submitted_at <= due_at (equality is on time)
        if submitted > objection["due_at"]:
            objection["late_breach"] = True
        else:
            for e in find_entries("OBJECTION_RESPONSE_DUE",
                                  objection_id=objection["id"], status="PENDING"):
                entry_mark_met(e)
        touch(objection)
        filing = db.rate_filings.get(objection["filing_id"])
        if filing is not None:
            recompute_filing_objections(filing)
    return success(serialize(response, OBJECTION_RESPONSE), code=200)


@bp.route("/objections/<objectionId>/resolve", methods=["POST"])
def resolve_objection(objectionId):
    authenticate({"StateRegulator"})
    with db.lock:
        objection = get_or_404(db.objections, objectionId)
        if objection["status"] != "RESPONSE_SUBMITTED":
            raise err(ERR_INVALID_STATE)
        objection["status"] = "RESOLVED"
        objection["resolved_at"] = now()
        touch(objection)
        filing = db.rate_filings.get(objection["filing_id"])
        if filing is not None:
            recompute_filing_objections(filing)
    return success(serialize(objection, OBJECTION), code=200)


@bp.route("/objections/<objectionId>/reopen", methods=["POST"])
def reopen_objection(objectionId):
    authenticate({"StateRegulator"})
    with db.lock:
        objection = get_or_404(db.objections, objectionId)
        if objection["status"] != "RESPONSE_SUBMITTED":
            raise err(ERR_INVALID_STATE)
        filing = db.rate_filings.get(objection["filing_id"])
        profile = db.state_profiles.get(filing["profile_id"]) if filing else None
        objection["status"] = "REOPENED"
        objection["reopen_count"] += 1
        objection["due_at"] = now() + timedelta(
            days=profile["objection_response_sla_days"]
        )
        touch(objection)
        create_calendar_entry(
            "OBJECTION_RESPONSE_DUE",
            objection["due_at"],
            filing_id=objection["filing_id"],
            objection_id=objection["id"],
        )
        if filing is not None and filing["status"] in ("SUBMITTED", "UNDER_OBJECTION"):
            if filing["status"] != "UNDER_OBJECTION":
                filing["status"] = "UNDER_OBJECTION"
                touch(filing)
            recompute_filing_objections(filing)
    return success(serialize(objection, OBJECTION), code=200)


@bp.route("/objections/<objectionId>/withdraw", methods=["POST"])
def withdraw_objection(objectionId):
    authenticate({"StateRegulator"})
    with db.lock:
        objection = get_or_404(db.objections, objectionId)
        if objection["status"] in ("RESOLVED", "WITHDRAWN"):
            raise err(ERR_INVALID_STATE)
        _withdraw_objection(objection)
        filing = db.rate_filings.get(objection["filing_id"])
        if filing is not None:
            recompute_filing_objections(filing)
    return success(serialize(objection, OBJECTION), code=200)
