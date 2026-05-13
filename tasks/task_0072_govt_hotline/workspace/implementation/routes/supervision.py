"""Supervision routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role
from services import supervision as svc

bp = Blueprint("supervision", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/supervision", methods=["GET"])
def list_():
    require_role("PlatformAdmin", "Supervisor", "Dispatcher")
    limit, offset = resp.parse_pagination()
    with db.LOCK:
        rows, total = svc.list_supervision(
            limit, offset,
            status=request.args.get("status"),
            reason=request.args.get("reason"),
        )
    return resp.success_list(rows, total, limit, offset)


@bp.route("/supervision/<tid>/ack", methods=["POST"])
def ack(tid):
    require_role("Supervisor")
    with db.LOCK:
        rec = svc.ack(tid)
    return resp.success(rec)


@bp.route("/supervision/<tid>/close", methods=["POST"])
def close(tid):
    require_role("Supervisor")
    with db.LOCK:
        rec = svc.close_task(tid)
    return resp.success(rec)
