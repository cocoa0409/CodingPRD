"""Audit log listing."""
from flask import Blueprint, request

from common import paginate
from db import db
from middleware import require_roles
from response import success

bp = Blueprint("audit_logs", __name__)


@bp.route("/audit-logs", methods=["GET"])
def list_audit_logs():
    require_roles(["PlatformAdmin"])
    rows = list(db.audit_logs.values())

    subject_entity = request.args.get("subject_entity")
    subject_id = request.args.get("subject_id")
    change_type = request.args.get("change_type")

    if subject_entity:
        rows = [r for r in rows if r.get("subject_entity") == subject_entity]
    if subject_id:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    if change_type:
        rows = [r for r in rows if r.get("change_type") == change_type]

    page, meta = paginate(rows)
    return success(page, response_type="array", pagination=meta)
