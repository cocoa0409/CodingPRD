"""ORAccessPass routes."""

from datetime import timedelta

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body, req_str, req_enum
from response import success_object, success_list, parse_pagination
from services import core
from services.core import ACCESS_LEAD_MINUTES, ACCESS_TRAIL_MINUTES

bp = Blueprint("passes", __name__)


def _get_pass_or_404(pass_id):
    p = db.access_passes.get(pass_id)
    if p is None:
        raise_err("ERR_PASS_NOT_FOUND", "Access pass not found")
    return p


@bp.post("/access-passes")
def create_pass():
    user_id, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["VendorRep", "VendorCoordinator"])

    rep_id = req_str(body, "rep_id")
    case_id = req_str(body, "case_id")

    # Existence, body field order: rep_id then case_id.
    rep = db.reps.get(rep_id)
    if rep is None:
        raise_err("ERR_REP_NOT_FOUND", "Representative not found")
    case = db.cases.get(case_id)
    if case is None:
        raise_err("ERR_CASE_NOT_FOUND", "Case not found")

    # A VendorRep caller may only request a pass for themselves.
    if role == "VendorRep" and rep_id != user_id:
        raise_err("ERR_REP_VENDOR_MISMATCH", "A rep may only request a pass for themselves")

    if case["status"] != "SCHEDULED":
        raise_err("ERR_CASE_INVALID_STATE", "The case must be SCHEDULED")

    p = {
        "rep_id": rep_id,
        "case_id": case_id,
        "window_start_at": None,
        "window_end_at": None,
        "status": "REQUESTED",
        "denial_reason": None,
    }
    core.stamp_new(p)
    db.access_passes[p["id"]] = p
    return success_object(core.serialize(p), status=201)


@bp.get("/access-passes")
def list_passes():
    get_auth()
    rep_id = flask_request.args.get("rep_id")
    case_id = flask_request.args.get("case_id")
    status = flask_request.args.get("status")
    items = sorted(db.access_passes.values(), key=lambda p: p["_seq"])
    if rep_id:
        items = [p for p in items if p["rep_id"] == rep_id]
    if case_id:
        items = [p for p in items if p["case_id"] == case_id]
    if status:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(p) for p in page], limit, offset, total)


@bp.get("/access-passes/<id>")
def get_pass(id):
    get_auth()
    p = _get_pass_or_404(id)
    return success_object(core.serialize(p))


@bp.post("/access-passes/<id>/decide")
def decide_pass(id):
    _, role = get_auth()
    body = get_body(required=True)

    decision = req_enum(body, "decision", {"APPROVE", "DENY"})

    require_role(role, ["VendorCoordinator"])
    p = _get_pass_or_404(id)

    if p["status"] != "REQUESTED":
        raise_err("ERR_PASS_INVALID_STATE", "Only a REQUESTED pass can be decided")

    if decision == "DENY":
        reason = body.get("reason")
        p["status"] = "DENIED"
        p["denial_reason"] = reason if isinstance(reason, str) else None
        core.touch(p)
        return success_object(core.serialize(p))

    # APPROVE guards in workflow order: case SCHEDULED; vendor ACTIVE; rep
    # credential ACTIVE; credential outlives the case.
    case = db.cases.get(p["case_id"])
    rep = db.reps.get(p["rep_id"])
    if case is None or case["status"] != "SCHEDULED":
        raise_err("ERR_CASE_INVALID_STATE", "The case must be SCHEDULED")
    vendor = db.vendors.get(rep["vendor_id"]) if rep else None
    if vendor is None or vendor["status"] != "ACTIVE":
        raise_err("ERR_VENDOR_NOT_ACTIVE", "The rep's vendor is not ACTIVE")
    if rep["credential_status"] != "ACTIVE":
        raise_err("ERR_REP_CREDENTIAL_NOT_ACTIVE", "Rep credential is not ACTIVE")
    expires = db.parse_dt(rep["credential_expires_at"])
    scheduled_end = db.parse_dt(case["scheduled_end_at"])
    if expires is None or expires <= scheduled_end:
        raise_err("ERR_CREDENTIAL_WINDOW_INSUFFICIENT", "Credential must outlive the case scheduled end")

    start = db.parse_dt(case["scheduled_start_at"])
    p["window_start_at"] = db.fmt_ts(start - timedelta(minutes=ACCESS_LEAD_MINUTES))
    p["window_end_at"] = db.fmt_ts(scheduled_end + timedelta(minutes=ACCESS_TRAIL_MINUTES))
    p["status"] = "APPROVED"
    core.touch(p)
    return success_object(core.serialize(p))


@bp.post("/access-passes/<id>/admit")
def admit_pass(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["ORCirculatorNurse"])
    p = _get_pass_or_404(id)

    if p["status"] != "APPROVED":
        raise_err("ERR_PASS_INVALID_STATE", "Only an APPROVED pass can be admitted")

    start = db.parse_dt(p["window_start_at"])
    end = db.parse_dt(p["window_end_at"])
    now = db.now_dt()
    if start is None or end is None or not (start <= now < end):
        raise_err("ERR_ACCESS_WINDOW_CLOSED", "Outside the access window")

    p["status"] = "ADMITTED"
    core.touch(p)
    return success_object(core.serialize(p))
