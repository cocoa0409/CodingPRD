"""Submittal endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success

bp = Blueprint("submittals", __name__)

DECISIONS = {"APPROVED", "APPROVED_AS_NOTED", "REVISE_AND_RESUBMIT"}


def _get_or_404(sid):
    s = db.submittals.get(sid)
    if s is None:
        raise err(ERR_NOT_FOUND, "Submittal not found.")
    return s


@bp.post("/submittals")
def create_submittal():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "spec_section", "title"])

    project_id = h.as_string(body["project_id"], "project_id")
    if db.projects.get(project_id) is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    spec_section = h.as_string(body["spec_section"], "spec_section")
    title = h.as_string(body["title"], "title")

    record = {
        "project_id": project_id,
        "spec_section": spec_section,
        "title": title,
        "revision": 0,
        "status": "PENDING",
    }
    db.stamp_create(record)
    db.submittals[record["id"]] = record
    return success(h.submittal_out(record), status=201)


@bp.get("/submittals/<sid>")
def get_submittal(sid):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.submittal_out(_get_or_404(sid)))


@bp.get("/submittals")
def list_submittals():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.submittals.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.submittal_out(r) for r in page], pagination=meta)


@bp.post("/submittals/<sid>/review")
def review_submittal(sid):
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    s = _get_or_404(sid)
    body = h.get_json()
    h.require_fields(body, ["decision"])
    decision = h.as_enum(body["decision"], "decision", DECISIONS)
    if s["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Submittal is not PENDING.")
    # Decision drives the resulting state directly.
    s["status"] = decision
    db.touch(s)
    return success(h.submittal_out(s))


@bp.post("/submittals/<sid>/resubmit")
def resubmit_submittal(sid):
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    s = _get_or_404(sid)
    if s["status"] != "REVISE_AND_RESUBMIT":
        raise err(ERR_INVALID_STATE, "Submittal is not REVISE_AND_RESUBMIT.")
    s["status"] = "PENDING"
    s["revision"] += 1
    db.touch(s)
    return success(h.submittal_out(s))


@bp.post("/submittals/<sid>/close")
def close_submittal(sid):
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    s = _get_or_404(sid)
    if s["status"] not in ("APPROVED", "APPROVED_AS_NOTED"):
        raise err(ERR_INVALID_STATE, "Submittal is not APPROVED/APPROVED_AS_NOTED.")
    s["status"] = "CLOSED"
    db.touch(s)
    return success(h.submittal_out(s))
