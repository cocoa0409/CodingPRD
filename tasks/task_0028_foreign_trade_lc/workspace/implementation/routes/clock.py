"""Clock test-driving endpoints."""

from flask import Blueprint, request
import middleware
import response
from services import clock as svc

bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def advance():
    middleware.require_auth()
    middleware.require_role("Operator")
    return response.success(svc.advance(request.get_json(silent=True) or {}))


@bp.route("/_clock", methods=["GET"])
def get():
    middleware.require_auth()
    middleware.require_role("Operator", "Auditor")
    return response.success(svc.get_clock())
