"""SearchAssignment endpoints: dispatch with committed work windows,
submission, examination accept/return, and resume."""

import db
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_ORDER_TERMINAL,
    ERR_WINDOW_INVALID,
    ERR_WINDOW_OVERLAP,
    ERR_EMPTY_ASSIGNMENT,
    ERR_DOCUMENTS_NOT_EXAMINED,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    TERMINAL_ORDER_STATES,
    assignment_view,
    documents_of_assignment,
    order_of,
    reevaluate_search_completion,
)
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    parse_dt,
)

bp = make_blueprint("assignments")

_CREATE_SPEC = {
    "order_id": {"type": "string", "required": True},
    "abstracter_ref": {"type": "string", "required": True},
    "search_type": {"type": "enum", "required": True, "values": {"CHAIN_OF_TITLE", "LIEN_JUDGMENT_TAX"}},
    "window_start": {"type": "datetime", "required": True},
    "window_end": {"type": "datetime", "required": True},
}

_RETURN_SPEC = {
    "reason": {"type": "string", "required": True},
}


def _get_assignment_or_404(aid):
    return require_fk("assignments", aid, ERR_ASSIGNMENT_NOT_FOUND, "assignment")


def _require_order_not_terminal(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        raise ApiError(ERR_ORDER_TERMINAL, 409, "parent order is terminal")


@bp.post("/search-assignments")
def create_assignment():
    uid, role = authenticate(["OperationsManager"])
    body = body_json()
    check_shape(body, _CREATE_SPEC)
    order = require_fk("orders", body["order_id"], ERR_ORDER_NOT_FOUND, "order")
    _require_order_not_terminal(order)

    window_start = parse_dt(body["window_start"], "window_start")
    window_end = parse_dt(body["window_end"], "window_end")
    if not window_end > window_start:
        raise ApiError(ERR_WINDOW_INVALID, 422, "window_end must be later than window_start")

    # Half-open window overlap against the same abstracter's non-CANCELLED
    # assignments; touching endpoints (end == start) are permitted.
    for other in db.all_of("assignments"):
        if other["abstracter_ref"] != body["abstracter_ref"] or other["status"] == "CANCELLED":
            continue
        o_start = parse_dt(other["window_start"], "window_start")
        o_end = parse_dt(other["window_end"], "window_end")
        if window_start < o_end and o_start < window_end:
            raise ApiError(ERR_WINDOW_OVERLAP, 409, "window overlaps an existing assignment of this abstracter")

    assignment = db.new_entity("assignments", {
        "order_id": body["order_id"],
        "abstracter_ref": body["abstracter_ref"],
        "search_type": body["search_type"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "revision_count": 0,
        "return_reason": None,
        "status": "IN_PROGRESS",
    })
    # First assignment moves the order RECEIVED -> SEARCH_IN_PROGRESS.
    if order["status"] == "RECEIVED":
        order["status"] = "SEARCH_IN_PROGRESS"
        db.touch(order)
    return success_obj(assignment_view(assignment), 201)


@bp.get("/search-assignments/<aid>")
def get_assignment(aid):
    authenticate(ALL_ROLES)
    assignment = _get_assignment_or_404(aid)
    return success_obj(assignment_view(assignment), 200)


@bp.get("/search-assignments")
def list_assignments():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("assignments"), ["order_id", "abstracter_ref", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([assignment_view(a) for a in page], limit, offset, total, has_more)


@bp.post("/search-assignments/<aid>/submit")
def submit_assignment(aid):
    uid, role = authenticate(["Abstracter"])
    assignment = _get_assignment_or_404(aid)
    if assignment["abstracter_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "only the assigned abstracter may submit")
    _require_order_not_terminal(order_of(assignment))
    if assignment["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not IN_PROGRESS")
    linked = [d for d in documents_of_assignment(aid) if d["status"] != "VOID"]
    if not linked:
        raise ApiError(ERR_EMPTY_ASSIGNMENT, 422, "no non-VOID documents linked to this assignment")
    if any(d["status"] == "REPORTED" for d in linked):
        raise ApiError(ERR_DOCUMENTS_NOT_EXAMINED, 409, "a linked document is still REPORTED")
    assignment["status"] = "SUBMITTED"
    db.touch(assignment)
    return success_obj(assignment_view(assignment), 200)


@bp.post("/search-assignments/<aid>/accept")
def accept_assignment(aid):
    uid, role = authenticate(["Examiner"])
    assignment = _get_assignment_or_404(aid)
    order = order_of(assignment)
    _require_order_not_terminal(order)
    if assignment["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not SUBMITTED")
    assignment["status"] = "ACCEPTED"
    db.touch(assignment)
    reevaluate_search_completion(order)
    return success_obj(assignment_view(assignment), 200)


@bp.post("/search-assignments/<aid>/return")
def return_assignment(aid):
    uid, role = authenticate(["Examiner"])
    body = body_json()
    check_shape(body, _RETURN_SPEC)
    assignment = _get_assignment_or_404(aid)
    _require_order_not_terminal(order_of(assignment))
    if assignment["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not SUBMITTED")
    assignment["status"] = "RETURNED_FOR_CORRECTION"
    assignment["revision_count"] = assignment.get("revision_count", 0) + 1
    assignment["return_reason"] = body["reason"]
    db.touch(assignment)
    return success_obj(assignment_view(assignment), 200)


@bp.post("/search-assignments/<aid>/resume")
def resume_assignment(aid):
    uid, role = authenticate(["Abstracter"])
    assignment = _get_assignment_or_404(aid)
    if assignment["abstracter_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "only the assigned abstracter may resume")
    _require_order_not_terminal(order_of(assignment))
    if assignment["status"] != "RETURNED_FOR_CORRECTION":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not RETURNED_FOR_CORRECTION")
    assignment["status"] = "IN_PROGRESS"
    db.touch(assignment)
    return success_obj(assignment_view(assignment), 200)
