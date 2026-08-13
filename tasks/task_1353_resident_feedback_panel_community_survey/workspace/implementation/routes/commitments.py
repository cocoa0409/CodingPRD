from flask import Blueprint, g, request

from core import (ApiError, body, db, list_response, new_resource, now, ok,
                  parse_dt, req_str, require_roles, touch)
from serializers import ser_commitment

bp = Blueprint("commitments", __name__)


def get_commitment_or_404(commitment_id):
    c = db.commitments.get(commitment_id)
    if c is None:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND", 404, "Follow-up commitment not found")
    return c


def _check_department(c):
    if c["department_name"] != g.user_id:
        raise ApiError("ERR_FORBIDDEN_DEPARTMENT", 403,
                       "DepartmentLiaison may only act on their own department's commitments")


@bp.post("/feedback-panel/follow-up-commitments")
@require_roles("DepartmentLiaison")
def create_commitment():
    data = body()
    publication_id = req_str(data, "publication_id")
    pub = db.publications.get(publication_id)
    if pub is None:
        raise ApiError("ERR_PUBLICATION_NOT_FOUND", 404, "Publication not found")
    department_name = req_str(data, "department_name")
    summary = req_str(data, "summary")
    due_at = parse_dt(data.get("due_at"), "due_at")
    if pub["status"] != "PUBLISHED":
        raise ApiError("ERR_PUBLICATION_NOT_PUBLISHED", 409,
                       "Commitment creation requires publication status PUBLISHED")
    c = new_resource()
    c.update({
        "publication_id": publication_id,
        "department_name": department_name,
        "summary": summary,
        "due_at": due_at,
        "breached_at": None,
        "status": "COMMITTED",
    })
    db.commitments[c["id"]] = c
    return ok(ser_commitment(c), 201)


@bp.get("/feedback-panel/follow-up-commitments")
@require_roles("DepartmentLiaison", "PanelManager", "PrivacyOfficer")
def list_commitments():
    items = list(db.commitments.values())
    publication_id = request.args.get("publication_id")
    if publication_id is not None:
        items = [c for c in items if c["publication_id"] == publication_id]
    department_name = request.args.get("department_name")
    if department_name is not None:
        items = [c for c in items if c["department_name"] == department_name]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, ser_commitment)


@bp.get("/feedback-panel/follow-up-commitments/<commitment_id>")
@require_roles("DepartmentLiaison", "PanelManager", "PrivacyOfficer")
def get_commitment(commitment_id):
    return ok(ser_commitment(get_commitment_or_404(commitment_id)))


@bp.post("/feedback-panel/follow-up-commitments/<commitment_id>/start")
@require_roles("DepartmentLiaison")
def start(commitment_id):
    c = get_commitment_or_404(commitment_id)
    _check_department(c)
    if c["status"] != "COMMITTED":
        raise ApiError("ERR_COMMITMENT_NOT_OPEN", 409,
                       "Start requires commitment status COMMITTED")
    c["status"] = "IN_PROGRESS"
    touch(c)
    return ok(ser_commitment(c))


@bp.post("/feedback-panel/follow-up-commitments/<commitment_id>/fulfill")
@require_roles("DepartmentLiaison")
def fulfill(commitment_id):
    c = get_commitment_or_404(commitment_id)
    _check_department(c)
    if c["status"] != "IN_PROGRESS":
        raise ApiError("ERR_COMMITMENT_NOT_OPEN", 409,
                       "Fulfill requires commitment status IN_PROGRESS")
    if now() > c["due_at"]:
        raise ApiError("ERR_COMMITMENT_OVERDUE", 409,
                       "Fulfill is only permitted at or before due_at")
    c["status"] = "FULFILLED"
    touch(c)
    return ok(ser_commitment(c))


@bp.post("/feedback-panel/follow-up-commitments/<commitment_id>/mark-breached")
@require_roles("PanelManager")
def mark_breached(commitment_id):
    c = get_commitment_or_404(commitment_id)
    if c["status"] not in ("COMMITTED", "IN_PROGRESS"):
        raise ApiError("ERR_COMMITMENT_NOT_OPEN", 409,
                       "Mark-breached requires commitment status COMMITTED or IN_PROGRESS")
    if now() <= c["due_at"]:
        raise ApiError("ERR_COMMITMENT_NOT_OVERDUE", 409,
                       "Mark-breached requires the current time to be past due_at")
    c["status"] = "BREACHED"
    c["breached_at"] = now()
    touch(c)
    return ok(ser_commitment(c))


@bp.post("/feedback-panel/follow-up-commitments/<commitment_id>/renegotiate")
@require_roles("DepartmentLiaison")
def renegotiate(commitment_id):
    c = get_commitment_or_404(commitment_id)
    _check_department(c)
    if c["status"] != "BREACHED":
        raise ApiError("ERR_COMMITMENT_NOT_OPEN", 409,
                       "Renegotiate requires commitment status BREACHED")
    data = body()
    new_due_at = parse_dt(data.get("new_due_at"), "new_due_at")
    if new_due_at <= now():
        raise ApiError("ERR_COMMITMENT_OVERDUE", 409,
                       "new_due_at must lie strictly in the future")
    c["due_at"] = new_due_at
    c["breached_at"] = None
    c["status"] = "COMMITTED"
    touch(c)
    return ok(ser_commitment(c))
