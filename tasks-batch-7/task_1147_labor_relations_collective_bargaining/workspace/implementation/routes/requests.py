"""InformationRequest endpoints with BUSINESS/CALENDAR deadline arithmetic."""

from flask import Blueprint, request

import calc
import clock
from db import db
from errors import (
    ERR_EXTENSION_LIMIT_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED_ROLE,
    ERR_UNION_DECERTIFIED,
    ERR_UNION_MISMATCH,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, opt_string, page,
    parse_pagination, req_datetime, req_int, req_string, serialize, sort_items, touch,
    recompute_open_request_count,
)
from response import success_list, success_object

bp = Blueprint("requests", __name__)

REQUEST_STATUSES = ("RECEIVED", "ACKNOWLEDGED", "IN_PROGRESS", "FULFILLED", "PARTIALLY_FULFILLED", "OBJECTED")
OPEN_STATUSES = ("RECEIVED", "ACKNOWLEDGED", "IN_PROGRESS", "OBJECTED")


def _deadline_mode(info_request):
    if info_request["agreement_id"] is None:
        return "BUSINESS"
    agreement = db.agreements.get(info_request["agreement_id"])
    if agreement is None:
        return "BUSINESS"
    return agreement["deadline_mode"]


@bp.post("/labor-relations/information-requests")
def create_request():
    user_id, role = authenticate(["UnionRepresentative"])
    body = get_body()
    union_id = req_string(body, "union_id")
    agreement_id = opt_string(body, "agreement_id")
    subject = req_string(body, "subject")
    received_at = req_datetime(body, "received_at")

    # Ownership (priority 3): union_id must equal X-User-ID
    if union_id != user_id:
        raise_err(ERR_UNION_MISMATCH, "union_id must equal X-User-ID for UnionRepresentative")

    # Resolution, left-to-right: union, then agreement
    union = lookup(db.unions, union_id, "Union")
    agreement = None
    if agreement_id is not None:
        agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
        if agreement["status"] in ("ARCHIVED", "REPLACED"):
            raise_err(ERR_INVALID_STATE, "Cannot file a request against a %s agreement" % agreement["status"])

    # Union standing (priority 8): DECERTIFIED blocks filing
    if union["status"] == "DECERTIFIED":
        raise_err(ERR_UNION_DECERTIFIED, "Union is DECERTIFIED; filing information requests is blocked")

    mode = agreement["deadline_mode"] if agreement is not None else "BUSINESS"
    due_at = calc.compute_due_at(received_at, mode)

    info = new_entity()
    info.update({
        "union_id": union_id,
        "agreement_id": agreement_id,
        "subject": subject,
        "received_at": received_at,
        "status": "RECEIVED",
        "due_at": due_at,
        "is_overdue": clock.now() > due_at,
        "extension_count": 0,
        "response_note": None,
        "objection_basis": None,
    })
    db.requests[info["id"]] = info

    union["open_information_request_count"] += 1
    touch(union)
    return success_object(serialize(info), status=201)


@bp.get("/labor-relations/information-requests")
def list_requests():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    union_id = request.args.get("union_id")
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    is_overdue = request.args.get("is_overdue")
    items = list(db.requests.values())
    if union_id is not None:
        items = [i for i in items if i["union_id"] == union_id]
    if agreement_id is not None:
        items = [i for i in items if i["agreement_id"] == agreement_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if is_overdue is not None:
        wanted = is_overdue.strip().lower() == "true"
        items = [i for i in items if i["is_overdue"] == wanted]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(i) for i in slice_], limit, offset, total)


@bp.get("/labor-relations/information-requests/<request_id>")
def get_request(request_id):
    authenticate(ALL_ROLES)
    info = lookup(db.requests, request_id, "InformationRequest")
    return success_object(serialize(info))


@bp.post("/labor-relations/information-requests/<request_id>/state")
def transition_request(request_id):
    user_id, role = authenticate(["LRManager", "LegalCounsel"])
    info = lookup(db.requests, request_id, "InformationRequest")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in REQUEST_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown information-request status: %s" % to_status)
    if to_status == "RECEIVED":
        raise_err(ERR_INVALID_STATE, "Cannot transition a request back to RECEIVED")

    status = info["status"]

    # Per-transition role gating
    if to_status in ("ACKNOWLEDGED", "FULFILLED", "PARTIALLY_FULFILLED") and role != "LRManager":
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only LRManager may transition a request to %s" % to_status)
    if to_status == "OBJECTED" and role != "LegalCounsel":
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only LegalCounsel may object to a request")
    if to_status == "IN_PROGRESS":
        # ACKNOWLEDGED -> IN_PROGRESS is LRManager; OBJECTED -> IN_PROGRESS is LegalCounsel
        if status == "OBJECTED":
            if role != "LegalCounsel":
                raise_err(ERR_UNAUTHORIZED_ROLE, "Only LegalCounsel may withdraw an objection")
        elif role != "LRManager":
            raise_err(ERR_UNAUTHORIZED_ROLE, "Only LRManager may start work on a request")

    if to_status == "ACKNOWLEDGED":
        if status != "RECEIVED":
            raise_err(ERR_INVALID_STATE, "Only a RECEIVED request can be acknowledged")
        info["status"] = "ACKNOWLEDGED"

    elif to_status == "IN_PROGRESS":
        if status not in ("ACKNOWLEDGED", "OBJECTED"):
            raise_err(ERR_INVALID_STATE, "Only an ACKNOWLEDGED or OBJECTED request can enter IN_PROGRESS")
        # objection_basis is retained for audit on the objection-withdrawn cycle
        info["status"] = "IN_PROGRESS"

    elif to_status == "OBJECTED":
        objection_basis = body.get("objection_basis")
        if not isinstance(objection_basis, str) or not objection_basis.strip():
            raise_err(ERR_INVALID_REQUEST, "objection_basis is required for OBJECTED")
        if status != "IN_PROGRESS":
            raise_err(ERR_INVALID_STATE, "Only an IN_PROGRESS request can be objected to")
        info["objection_basis"] = objection_basis
        info["status"] = "OBJECTED"

    elif to_status in ("FULFILLED", "PARTIALLY_FULFILLED"):
        response_note = body.get("response_note")
        if not isinstance(response_note, str) or not response_note.strip():
            raise_err(ERR_INVALID_REQUEST, "response_note is required for %s" % to_status)
        if to_status == "FULFILLED":
            if status not in ("IN_PROGRESS", "PARTIALLY_FULFILLED"):
                raise_err(ERR_INVALID_STATE, "Only an IN_PROGRESS or PARTIALLY_FULFILLED request can be fulfilled")
        else:
            if status != "IN_PROGRESS":
                raise_err(ERR_INVALID_STATE, "Only an IN_PROGRESS request can be partially fulfilled")
        info["response_note"] = response_note
        info["status"] = to_status
        # Every transition into FULFILLED or PARTIALLY_FULFILLED decrements the
        # union's open count and bumps the union version
        union = lookup(db.unions, info["union_id"], "Union")
        recompute_open_request_count(union)
        touch(union)

    touch(info)
    return success_object(serialize(info))


@bp.post("/labor-relations/information-requests/<request_id>/extend")
def extend_request(request_id):
    user_id, role = authenticate(["LRManager"])
    info = lookup(db.requests, request_id, "InformationRequest")
    body = get_body()
    extra_business_days = req_int(body, "extra_business_days")
    if extra_business_days < 1:
        raise_err(ERR_INVALID_REQUEST, "extra_business_days must be >= 1")
    if info["extension_count"] >= calc.EXTENSION_MAX_COUNT or extra_business_days > calc.EXTENSION_MAX_DAYS:
        raise_err(ERR_EXTENSION_LIMIT_EXCEEDED,
                  "At most %d extensions of at most %d days each" % (calc.EXTENSION_MAX_COUNT, calc.EXTENSION_MAX_DAYS))

    mode = _deadline_mode(info)
    info["due_at"] = calc.extend_due_at(info["due_at"], extra_business_days, mode)
    info["extension_count"] += 1
    info["is_overdue"] = info["status"] in OPEN_STATUSES and clock.now() > info["due_at"]
    touch(info)
    return success_object(serialize(info))
