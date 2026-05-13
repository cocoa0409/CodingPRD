"""Stats routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role
from services import stats as svc

bp = Blueprint("stats", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/stats/satisfaction", methods=["GET"])
def satisfaction():
    require_role("PlatformAdmin", "Supervisor")
    with db.LOCK:
        result = svc.satisfaction_index(
            group_by=request.args.get("group_by"),
            period_start=request.args.get("period_start"),
            period_end=request.args.get("period_end"),
            department_id=request.args.get("department_id"),
            handler_id=request.args.get("handler_id"),
        )
    return resp.success(result)


@bp.route("/stats/breach-rate", methods=["GET"])
def breach_rate():
    require_role("PlatformAdmin", "Supervisor")
    with db.LOCK:
        result = svc.breach_rate(
            group_by=request.args.get("group_by"),
            period_start=request.args.get("period_start"),
            period_end=request.args.get("period_end"),
            department_id=request.args.get("department_id"),
            category_code=request.args.get("category_code"),
        )
    return resp.success(result)


@bp.route("/stats/trend", methods=["GET"])
def trend():
    require_role("PlatformAdmin", "Supervisor")
    with db.LOCK:
        result = svc.trend(
            period_start=request.args.get("period_start"),
            period_end=request.args.get("period_end"),
            bucket=request.args.get("bucket"),
        )
    return resp.success(result)
