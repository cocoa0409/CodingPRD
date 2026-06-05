"""RFI endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success

bp = Blueprint("rfis", __name__)


def _get_or_404(rid):
    r = db.rfis.get(rid)
    if r is None:
        raise err(ERR_NOT_FOUND, "Rfi not found.")
    return r


@bp.post("/rfis")
def create_rfi():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "subject", "question"])

    project_id = h.as_string(body["project_id"], "project_id")
    if db.projects.get(project_id) is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    subject = h.as_string(body["subject"], "subject")
    question = h.as_string(body["question"], "question")

    record = {
        "project_id": project_id,
        "subject": subject,
        "question": question,
        "ball_in_court": "ARCHITECT",
        "status": "OPEN",
        "answer": None,
    }
    db.stamp_create(record)
    db.rfis[record["id"]] = record
    return success(h.rfi_out(record), status=201)


@bp.get("/rfis/<rid>")
def get_rfi(rid):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.rfi_out(_get_or_404(rid)))


@bp.get("/rfis")
def list_rfis():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    ball = request.args.get("ball_in_court")
    records = list(db.rfis.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    if ball:
        records = [r for r in records if r["ball_in_court"] == ball]
    page, meta = h.paginate(records, limit, offset)
    return success([h.rfi_out(r) for r in page], pagination=meta)


@bp.post("/rfis/<rid>/answer")
def answer_rfi(rid):
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    r = _get_or_404(rid)
    body = h.get_json()
    h.require_fields(body, ["answer"])
    answer = h.as_string(body["answer"], "answer")
    if r["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Rfi is not OPEN.")
    r["status"] = "ANSWERED"
    r["ball_in_court"] = "CONTRACTOR"
    r["answer"] = answer
    db.touch(r)
    return success(h.rfi_out(r))


@bp.post("/rfis/<rid>/close")
def close_rfi(rid):
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    r = _get_or_404(rid)
    if r["status"] != "ANSWERED":
        raise err(ERR_INVALID_STATE, "Rfi is not ANSWERED.")
    r["status"] = "CLOSED"
    db.touch(r)
    return success(h.rfi_out(r))
