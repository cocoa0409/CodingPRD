"""Audit log + clock + sweep endpoints."""
from flask import Blueprint, request

from db import store
from errors import raise_api
from middleware import require_roles
from response import list_success, success
from services.pagination import paginate, parse_pagination
from services.progress import sweep_at_risk

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/audit-logs", methods=["GET"])
def list_audit_logs():
    require_roles("AcademicAdmin")
    limit, offset = parse_pagination()
    items = list(store.audit_logs.values())
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    action = request.args.get("action")
    if subject_type:
        items = [a for a in items if a["subject_type"] == subject_type]
    if subject_id:
        items = [a for a in items if a["subject_id"] == subject_id]
    if action:
        items = [a for a in items if a["action"] == action]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return list_success([dict(a) for a in page], limit, offset, total)


@admin_bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    require_roles("AcademicAdmin")
    body = request.get_json(silent=True) or {}
    try:
        seconds = int(body["seconds"])
    except (KeyError, TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "seconds required")
    store.clock_now_ts = int(store.clock_now_ts) + seconds
    sweep_at_risk()
    return success({"now_ts": store.clock_now_ts})


@admin_bp.route("/_sweep/at-risk", methods=["POST"])
def sweep_endpoint():
    require_roles("AcademicAdmin")
    sweep_at_risk()
    return success({})
