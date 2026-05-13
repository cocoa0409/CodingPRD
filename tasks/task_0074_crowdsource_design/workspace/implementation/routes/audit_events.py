"""Audit events listing route."""
from flask import Blueprint, request

from common import paginate
from db import db
from middleware import require_roles
from response import success


bp = Blueprint("audit_events", __name__)


@bp.route("/audit-events", methods=["GET"])
def list_audit_events():
    require_roles({"PlatformOps"})
    items = list(db.audit_events.values())
    project_id = request.args.get("project_id")
    subject_kind = request.args.get("subject_kind")
    subject_id = request.args.get("subject_id")
    action_kind = request.args.get("action_kind")
    if subject_kind:
        items = [e for e in items if e.get("subject_kind") == subject_kind]
    if subject_id:
        items = [e for e in items if e.get("subject_id") == subject_id]
    if action_kind:
        items = [e for e in items if e.get("action_kind") == action_kind]
    if project_id:
        # Filter to events whose subject ultimately belongs to this project.
        kept = []
        for e in items:
            kind = e.get("subject_kind")
            sid = e.get("subject_id")
            pid = _project_of(kind, sid)
            if pid == project_id:
                kept.append(e)
        items = kept
    page, meta = paginate(items, sort_key=lambda x: (x.get("occurred_at", ""), x.get("id", "")))
    return success(page, response_type="array", pagination=meta)


def _project_of(subject_kind, subject_id):
    if subject_kind == "SUBMISSION":
        s = db.submissions.get(subject_id)
        return s.get("project_id") if s else None
    if subject_kind == "REVIEW_ASSIGNMENT":
        a = db.review_assignments.get(subject_id)
        if not a:
            return None
        stage = db.review_stages.get(a.get("review_stage_id"))
        return stage.get("project_id") if stage else None
    if subject_kind == "REVIEW_STAGE":
        s = db.review_stages.get(subject_id)
        return s.get("project_id") if s else None
    if subject_kind == "COPYRIGHT_TRANSFER":
        t = db.copyright_transfers.get(subject_id)
        return t.get("project_id") if t else None
    if subject_kind == "DISPUTE":
        d = db.disputes.get(subject_id)
        return d.get("project_id") if d else None
    if subject_kind == "PRIZE_PAYMENT":
        p = db.prize_payments.get(subject_id)
        return p.get("project_id") if p else None
    return None
