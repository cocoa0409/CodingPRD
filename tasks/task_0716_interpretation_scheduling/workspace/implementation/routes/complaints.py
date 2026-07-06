from flask import Blueprint, request as flask_request

from db import db
from errors import err
from middleware import authenticate, require_role
from response import ok, ok_list
from helpers import get_body, paginate, sort_by_created, require_fields, check_enum
from services import constants as C

bp = Blueprint("complaints", __name__)


def _session_request_client(session):
    a = db.assignments.get(session["assignment_id"])
    if not a:
        return None
    req = db.requests.get(a["request_id"])
    if not req:
        return None
    return req["client_id"]


@bp.post("/interpretation/complaints")
def file_complaint():
    uid, role = authenticate()
    require_role(role, {"ClientAccount"})
    body = get_body()
    require_fields(body, ["session_id", "category"])
    session = db.sessions.get(body["session_id"])
    if session is None:
        raise err("ERR_FK_NOT_FOUND", "session_id not found")
    check_enum(body["category"], C.COMPLAINT_CATEGORIES, "category")
    owner_client = _session_request_client(session)
    if owner_client != uid:
        raise err("ERR_NOT_OWNER", "Client does not own this session")
    entity = db.base_fields()
    entity.update({
        "session_id": body["session_id"],
        "client_id": owner_client,
        "category": body["category"],
        "status": "FILED",
        "remedy_credit_cents": 0,
    })
    db.complaints[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/complaints/<cid>")
def get_complaint(cid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    c = db.complaints.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Complaint not found")
    return ok(c)


@bp.get("/interpretation/complaints")
def list_complaints():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    rows = list(db.complaints.values())
    cid = flask_request.args.get("client_id")
    sid = flask_request.args.get("session_id")
    status = flask_request.args.get("status")
    if cid is not None:
        rows = [r for r in rows if r["client_id"] == cid]
    if sid is not None:
        rows = [r for r in rows if r["session_id"] == sid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/interpretation/complaints/<cid>/review")
def review_complaint(cid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    c = db.complaints.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Complaint not found")
    if c["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Complaint is not FILED")
    c["status"] = "UNDER_REVIEW"
    db.touch(c)
    return ok(c)


@bp.post("/interpretation/complaints/<cid>/request-info")
def request_info(cid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    c = db.complaints.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Complaint not found")
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Complaint is not UNDER_REVIEW")
    c["status"] = "NEEDS_INFO"
    db.touch(c)
    return ok(c)


@bp.post("/interpretation/complaints/<cid>/resubmit")
def resubmit_complaint(cid):
    uid, role = authenticate()
    require_role(role, {"ClientAccount"})
    c = db.complaints.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Complaint not found")
    if c["status"] != "NEEDS_INFO":
        raise err("ERR_INVALID_STATE", "Complaint is not NEEDS_INFO")
    if c["client_id"] != uid:
        raise err("ERR_NOT_OWNER", "Client does not own this complaint")
    c["status"] = "UNDER_REVIEW"
    db.touch(c)
    return ok(c)


@bp.post("/interpretation/complaints/<cid>/resolve")
def resolve_complaint(cid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    c = db.complaints.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Complaint not found")
    body = get_body()
    require_fields(body, ["disposition"])
    disposition = body["disposition"]
    if disposition not in ("UPHELD", "DISMISSED"):
        raise err("ERR_INVALID_REQUEST", "disposition must be UPHELD or DISMISSED")
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Complaint is not UNDER_REVIEW")
    if disposition == "DISMISSED":
        c["status"] = "DISMISSED"
        db.touch(c)
        return ok(c)
    # UPHELD
    if c["category"] in ("BILLING", "NO_SHOW"):
        session = db.sessions.get(c["session_id"])
        if session:
            a = db.assignments.get(session["assignment_id"])
            was_invoiced = a is not None and a["billing_status"] == "INVOICED"
            if a is not None:
                a["billing_status"] = "WAIVED"
                db.touch(a)
            credit = session["billed_amount_cents"]
            c["remedy_credit_cents"] = credit
            if was_invoiced:
                client = db.clients.get(c["client_id"])
                if client:
                    client["outstanding_balance_cents"] = client["outstanding_balance_cents"] - credit
                    db.touch(client)
    c["status"] = "UPHELD"
    db.touch(c)
    return ok(c)
