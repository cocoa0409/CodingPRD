"""Department routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role
from services import departments as svc

bp = Blueprint("departments", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/departments", methods=["POST"])
def create():
    require_role("PlatformAdmin")
    with db.LOCK:
        rec = svc.create_department(request.get_json(force=True, silent=True) or {})
    return resp.success(rec, 201)


@bp.route("/departments", methods=["GET"])
def list_():
    require_role("PlatformAdmin", "Dispatcher", "Supervisor")
    limit, offset = resp.parse_pagination()
    with db.LOCK:
        rows, total = svc.list_departments(
            limit, offset,
            status=request.args.get("status"),
            jurisdiction_code=request.args.get("jurisdiction_code"),
        )
    return resp.success_list(rows, total, limit, offset)


@bp.route("/departments/<dept_id>", methods=["GET"])
def get_(dept_id):
    require_role("PlatformAdmin", "Dispatcher", "Supervisor", "DepartmentHandler")
    with db.LOCK:
        rec = svc.get_department(dept_id)
    return resp.success(rec)


@bp.route("/departments/<dept_id>", methods=["PATCH"])
def patch_(dept_id):
    require_role("PlatformAdmin")
    with db.LOCK:
        rec = svc.update_department(dept_id, request.get_json(force=True, silent=True) or {})
    return resp.success(rec)
