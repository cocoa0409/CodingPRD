"""Survey routes (nested under work-orders + top-level /surveys/{id}/respond)."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role
from services import surveys as svc

bp = Blueprint("surveys", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/work-orders/<wo_id>/surveys", methods=["GET"])
def list_(wo_id):
    require_role("PlatformAdmin", "Dispatcher", "Supervisor", "HotlineOperator")
    limit, offset = resp.parse_pagination()
    with db.LOCK:
        rows = svc.list_surveys(wo_id)
        total = len(rows)
        rows = rows[offset: offset + limit]
    return resp.success_list(rows, total, limit, offset)


@bp.route("/work-orders/<wo_id>/surveys", methods=["POST"])
def dispatch_(wo_id):
    require_role("HotlineOperator")
    with db.LOCK:
        rec = svc.manual_dispatch(wo_id, request.get_json(force=True, silent=True) or {})
    return resp.success(rec, 201)


@bp.route("/surveys/<sid>/respond", methods=["POST"])
def respond(sid):
    require_role("SurveyAgent")
    with db.LOCK:
        rec = svc.respond(sid, request.get_json(force=True, silent=True) or {})
    return resp.success(rec)
