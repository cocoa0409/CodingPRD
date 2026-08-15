"""OverloadRequest endpoints (PRD §3.9): submission with snapshot, chair
endorsement, dean approval under segregation of duties and the term budget,
the DENIED -> SUBMITTED resubmission loop, and withdrawal."""

import db
from errors import (
    ApiError,
    ERR_OVERLOAD_REQUEST_NOT_FOUND,
    ERR_TERM_NOT_FOUND,
    ERR_FACULTY_NOT_FOUND,
    ERR_INVALID_OVERLOAD_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NO_OVERLOAD,
    ERR_OVERLOAD_REQUEST_EXISTS,
    ERR_COMP_BUDGET_EXCEEDED,
)
from middleware import authenticate, require_to_state_role, ALL_ROLES, CHAIR, DEAN
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, dec
import services

bp = make_blueprint("overload")

OVERLOAD_STATUSES = ["SUBMITTED", "CHAIR_ENDORSED", "DEAN_APPROVED", "DENIED", "WITHDRAWN"]

TO_STATE_ROLES = {
    "CHAIR_ENDORSED": {CHAIR},
    "SUBMITTED": {CHAIR},       # resubmission from DENIED
    "WITHDRAWN": {CHAIR},
    "DEAN_APPROVED": {DEAN},
    "DENIED": {DEAN},
}


def require_request(request_id):
    req = db.get("overload_requests", request_id)
    if req is None:
        raise ApiError(ERR_OVERLOAD_REQUEST_NOT_FOUND, 404, "overload request not found")
    return req


@bp.post("/overload-requests")
def create_overload_request():
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "term_id": {"type": "string", "required": True},
        "faculty_id": {"type": "string", "required": True},
    })
    # Existence (priority 4), body FKs in declared input order.
    term = db.get("workload_terms", body["term_id"])
    if term is None:
        raise ApiError(ERR_TERM_NOT_FOUND, 404, "term not found")
    faculty = db.get("faculty_members", body["faculty_id"])
    if faculty is None:
        raise ApiError(ERR_FACULTY_NOT_FOUND, 404, "faculty member not found")
    # Submission requires a live overload on the pair's load sheet.
    sheet = services.find_sheet(term["id"], faculty["id"])
    if sheet is None or dec(sheet["overload_credits"]) <= 0:
        raise ApiError(ERR_NO_OVERLOAD, 422,
                       "no overload: the pair's load sheet has overload_credits 0")
    # One non-terminal request per (faculty, term).
    for existing in db.all_of("overload_requests"):
        if (existing["term_id"] == term["id"] and existing["faculty_id"] == faculty["id"]
                and existing["status"] in services.NON_TERMINAL_OVERLOAD_STATUSES):
            raise ApiError(ERR_OVERLOAD_REQUEST_EXISTS, 409,
                           "a non-terminal overload request already exists for this faculty and term")
    overload = sheet["overload_credits"]
    req = db.new_entity("overload_requests", {
        "term_id": term["id"],
        "faculty_id": faculty["id"],
        "overload_credits": overload,
        "comp_cents": services.overload_comp_cents(overload, term),
        "endorsed_by_user_id": None,
        "status": "SUBMITTED",
    })
    return success_obj(db.public(req), 201)


@bp.get("/overload-requests")
def list_overload_requests():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("overload_requests"), ["term_id", "faculty_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total, has_more)


@bp.get("/overload-requests/<requestId>")
def get_overload_request(requestId):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_request(requestId)), 200)


@bp.post("/overload-requests/<requestId>/transition")
def transition_overload_request(requestId):
    user_id, role = authenticate([CHAIR, DEAN])
    body = body_json()
    check_shape(body, {"to_state": {"type": "enum", "values": OVERLOAD_STATUSES, "required": True}})
    to_state = body["to_state"]
    require_to_state_role(role, to_state, TO_STATE_ROLES)
    req = require_request(requestId)
    # Segregation of duties (priority 2.2): the DEAN_APPROVED approver must
    # differ from the chair who endorsed.
    if to_state == "DEAN_APPROVED" and req["endorsed_by_user_id"] is not None \
            and user_id == req["endorsed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "the approver must differ from the endorsing chair")
    from_state = req["status"]
    if to_state == "CHAIR_ENDORSED":
        if from_state != "SUBMITTED":
            raise ApiError(ERR_INVALID_OVERLOAD_TRANSITION, 409,
                           f"cannot move a {from_state} overload request to CHAIR_ENDORSED")
        req["endorsed_by_user_id"] = user_id
        req["status"] = "CHAIR_ENDORSED"
        db.touch(req)
        return success_obj(db.public(req), 200)
    if to_state == "DEAN_APPROVED":
        if from_state != "CHAIR_ENDORSED":
            raise ApiError(ERR_INVALID_OVERLOAD_TRANSITION, 409,
                           f"cannot move a {from_state} overload request to DEAN_APPROVED")
        term = db.get("workload_terms", req["term_id"])
        # Fiscal check (priority 9): last gate before money moves.
        if term["comp_budget_spent_cents"] + req["comp_cents"] > term["comp_budget_cents"]:
            raise ApiError(ERR_COMP_BUDGET_EXCEEDED, 402,
                           "approving this comp would exceed the term compensation budget")
        term["comp_budget_spent_cents"] += req["comp_cents"]
        db.touch(term)
        req["status"] = "DEAN_APPROVED"
        db.touch(req)
        return success_obj(db.public(req), 200)
    if to_state == "DENIED":
        if from_state != "CHAIR_ENDORSED":
            raise ApiError(ERR_INVALID_OVERLOAD_TRANSITION, 409,
                           f"cannot move a {from_state} overload request to DENIED")
        req["status"] = "DENIED"
        db.touch(req)
        return success_obj(db.public(req), 200)
    if to_state == "SUBMITTED":
        # Resubmission (chair, from DENIED): both snapshot fields are
        # recomputed from the CURRENT load sheet.
        if from_state != "DENIED":
            raise ApiError(ERR_INVALID_OVERLOAD_TRANSITION, 409,
                           f"cannot move a {from_state} overload request to SUBMITTED")
        term = db.get("workload_terms", req["term_id"])
        sheet = services.find_sheet(req["term_id"], req["faculty_id"])
        if sheet is None or dec(sheet["overload_credits"]) <= 0:
            raise ApiError(ERR_NO_OVERLOAD, 422,
                           "no overload: the current load sheet has overload_credits 0")
        req["overload_credits"] = sheet["overload_credits"]
        req["comp_cents"] = services.overload_comp_cents(sheet["overload_credits"], term)
        req["status"] = "SUBMITTED"
        db.touch(req)
        return success_obj(db.public(req), 200)
    # WITHDRAWN (chair, from SUBMITTED or CHAIR_ENDORSED).
    if from_state not in ("SUBMITTED", "CHAIR_ENDORSED"):
        raise ApiError(ERR_INVALID_OVERLOAD_TRANSITION, 409,
                       f"cannot move a {from_state} overload request to WITHDRAWN")
    req["status"] = "WITHDRAWN"
    db.touch(req)
    return success_obj(db.public(req), 200)
