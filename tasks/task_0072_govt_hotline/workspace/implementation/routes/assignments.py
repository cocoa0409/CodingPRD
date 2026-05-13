"""Assignment routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role
from services import assignments as svc

bp = Blueprint("assignments", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/work-orders/<wo_id>/assignments", methods=["GET"])
def list_(wo_id):
    require_role("PlatformAdmin", "Dispatcher", "Supervisor", "DepartmentHandler")
    limit, offset = resp.parse_pagination()
    with db.LOCK:
        rows = svc.list_assignments(wo_id)
        total = len(rows)
        rows = rows[offset: offset + limit]
    return resp.success_list(rows, total, limit, offset)


@bp.route("/work-orders/<wo_id>/assignments/<aid>/accept", methods=["POST"])
def accept(wo_id, aid):
    require_role("DepartmentHandler")
    with db.LOCK:
        a = svc.accept(wo_id, aid)
    return resp.success(a)


@bp.route("/work-orders/<wo_id>/assignments/<aid>/reject", methods=["POST"])
def reject(wo_id, aid):
    require_role("DepartmentHandler")
    with db.LOCK:
        a = svc.reject(wo_id, aid, request.get_json(force=True, silent=True) or {})
    return resp.success(a)


@bp.route("/work-orders/<wo_id>/assignments/<aid>/reassign", methods=["POST"])
def reassign(wo_id, aid):
    require_role("Dispatcher")
    with db.LOCK:
        a = svc.reassign(wo_id, aid, request.get_json(force=True, silent=True) or {})
    return resp.success(a)


@bp.route("/work-orders/<wo_id>/assignments/<aid>/opinion", methods=["POST"])
def opinion(wo_id, aid):
    require_role("DepartmentHandler")
    with db.LOCK:
        a = svc.submit_opinion(wo_id, aid, request.get_json(force=True, silent=True) or {})
    return resp.success(a)


@bp.route("/work-orders/<wo_id>/assignments/<aid>/escalate", methods=["POST"])
def escalate(wo_id, aid):
    require_role("DepartmentHandler")
    with db.LOCK:
        a = svc.escalate(wo_id, aid)
    return resp.success(a)
