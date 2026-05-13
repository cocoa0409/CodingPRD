"""Handler routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role
from services import handlers as svc

bp = Blueprint("handlers", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/handlers", methods=["POST"])
def create():
    require_role("PlatformAdmin")
    with db.LOCK:
        rec = svc.create_handler(request.get_json(force=True, silent=True) or {})
    return resp.success(rec, 201)


@bp.route("/handlers/<hid>", methods=["GET"])
def get_(hid):
    require_role("PlatformAdmin", "Dispatcher", "Supervisor", "DepartmentHandler")
    with db.LOCK:
        rec = svc.get_handler(hid)
    return resp.success(rec)


@bp.route("/handlers/<hid>", methods=["PATCH"])
def patch_(hid):
    require_role("PlatformAdmin")
    with db.LOCK:
        rec = svc.update_handler(hid, request.get_json(force=True, silent=True) or {})
    return resp.success(rec)
