"""ExamDocumentRequest endpoints (PRD 3.9): regulator books-and-records requests."""
from flask import Blueprint, request

from errors import raise_error, ERR_EXAM_REQUEST_INVALID_STATE, ERR_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from util import clock_ts, parse_date, today
from validate import (
    get_body, req_date, req_enum, req_str, require_path_resource,
)

bp = Blueprint("exam_requests", __name__)

REGULATORS = ("SEC", "FINRA", "STATE")
DOCUMENT_TYPES = ("TRADE_BLOTTER", "CORRESPONDENCE_LOG", "COMPLAINT_FILE",
                  "WSP_COPY", "OBA_REGISTER")


@bp.post("/exam-requests")
def create_exam_request():
    authorized(["ComplianceAnalyst"])
    body = get_body()
    # Priority 3: optional branch scope FK must resolve when provided
    branch_id = body.get("branch_id")
    if branch_id is not None:
        from db import db
        if not isinstance(branch_id, str) or db["branches"].get(branch_id) is None:
            raise_error(ERR_NOT_FOUND, f"branch_id does not resolve: {branch_id}")
    # Priority 8: schema
    regulator = req_enum(body, "regulator", REGULATORS)
    request_ref = req_str(body, "request_ref")
    document_type = req_enum(body, "document_type", DOCUMENT_TYPES)
    due_date = req_date(body, "due_date")

    rec = new_record("exam_requests", {
        "regulator": regulator,
        "request_ref": request_ref,
        "document_type": document_type,
        "branch_id": branch_id,
        "due_date": due_date,
        "produced_document_ref": None,
        "fulfilled_at": None,
        "is_late": None,
        "status": "OPEN",
    })
    return success_object(public(rec), status=201)


@bp.get("/exam-requests")
def list_exam_requests():
    return list_response("exam_requests", filters={
        "branch_id": request.args.get("branch_id"),
        "status": request.args.get("status"),
    })


@bp.get("/exam-requests/<rid>")
def get_exam_request(rid):
    return get_one("exam_requests", rid)


@bp.post("/exam-requests/<rid>/fulfill")
def fulfill_exam_request(rid):
    authorized(["ComplianceAnalyst"])
    req = require_path_resource("exam_requests", rid)
    if req["status"] not in ("OPEN", "OVERDUE"):
        raise_error(ERR_EXAM_REQUEST_INVALID_STATE,
                    "fulfill is allowed only from OPEN or OVERDUE")
    body = get_body()
    req["produced_document_ref"] = req_str(body, "produced_document_ref")
    req["fulfilled_at"] = clock_ts()
    req["is_late"] = today() > parse_date(req["due_date"])
    req["status"] = "FULFILLED"
    touch(req)
    return success_object(public(req))
